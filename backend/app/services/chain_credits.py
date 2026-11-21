"""Mirror committed credit movements on the explicitly configured local Ganache deployment."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

import requests
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, aliased
from web3 import Web3
from web3.exceptions import TransactionNotFound, Web3RPCError
from web3.logs import DISCARD

from app.config import get_settings
from app.models import ChainOp, ChainState, ChainWallet, CreditAccount
from app.services import chain_outbox
from app.types import utcnow

logger = logging.getLogger("aivideo.chain")
CONTRACT_STATE_KEY = "video_credit_contract"
DEPLOYMENT_STATE_KEY = "video_credit_deployment"
ARCHIVE_STATE_KEY = "video_credit_deployment_history"
STANDING_ALLOWANCE = 10**9
TX_GAS = 300_000
ACTIVE = ("pending", "submitted")


class ChainError(RuntimeError):
    pass


class ChainRejected(ChainError):
    pass


@dataclass(frozen=True)
class Deployment:
    chain_id: int
    address: str
    operation_namespace: str
    first_block: int


def deployment_of(session: Session) -> Deployment | None:
    state = session.get(ChainState, DEPLOYMENT_STATE_KEY)
    return Deployment(**json.loads(state.value)) if state else None


class _Chain:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.http = requests.Session()
        self.http.trust_env = False
        self.w3 = Web3(Web3.HTTPProvider(
            self.settings.chain_rpc_url, request_kwargs={"timeout": 4}, session=self.http
        ))
        self.artifact = json.loads(Path(self.settings.chain_artifact_path).read_text(encoding="utf-8"))
        self.key = self.settings.chain_platform_private_key.strip()

    def close(self) -> None:
        self.http.close()

    def check_network(self) -> int:
        actual = self.w3.eth.chain_id
        if actual != self.settings.chain_id:
            raise ChainError("Ganache 链 ID 与配置不一致")
        return actual

    def signer(self) -> str:
        if self.key:
            return self.w3.eth.account.from_key(self.key).address
        accounts = self.w3.eth.accounts
        if not accounts:
            raise ChainError("Ganache 没有可用的测试签名账户")
        return self.w3.to_checksum_address(accounts[0])

    def contract_at(self, address: str):
        return self.w3.eth.contract(address=self.w3.to_checksum_address(address), abi=self.artifact["abi"])

    def contract(self, deployment: Deployment):
        if self.check_network() != deployment.chain_id:
            raise ChainError("链部署与账套不一致")
        configured = self.settings.chain_contract_address.strip()
        if configured and self.w3.to_checksum_address(configured) != deployment.address:
            raise ChainError("合约地址与账套不一致")
        contract = self.contract_at(deployment.address)
        marker = self.w3.to_hex(contract.functions.shadowDeployment().call())
        if marker != deployment.operation_namespace:
            raise ChainError("演示链已更换，请核对账套和合约")
        return contract

    def prepare(self, fn, signer: str, private_key: str = "", gas: int = TX_GAS) -> tuple[str, str]:
        tx = fn.build_transaction(self._params(signer, gas))
        return self._sign(tx, private_key)

    def _params(self, signer: str, gas: int) -> dict:
        return {
            "from": signer,
            "nonce": self.w3.eth.get_transaction_count(signer, "pending"),
            "gas": gas,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.settings.chain_id,
        }

    def _sign(self, tx: dict, private_key: str) -> tuple[str, str]:
        if tx.get("to") in (None, "", "0x", b""):
            tx.pop("to", None)
        if private_key:
            signed = self.w3.eth.account.sign_transaction(tx, private_key)
            return self.w3.to_hex(signed.hash), self.w3.to_hex(signed.raw_transaction)
        # Ganache signs without broadcasting for unlocked local test accounts.
        rpc_tx = {key: hex(value) if isinstance(value, int) else value for key, value in tx.items()}
        raw = self.w3.manager.request_blocking("eth_signTransaction", [rpc_tx])
        return self.w3.to_hex(self.w3.keccak(hexstr=raw)), raw

    def _send_and_wait(self, raw: str):
        tx_id = self.w3.eth.send_raw_transaction(raw)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_id, timeout=8, poll_latency=0.25)
        if receipt["status"] != 1:
            raise ChainRejected("链上交易执行失败")
        return receipt

    def provision(self) -> Deployment:
        chain_id = self.check_network()
        signer = self.signer()
        configured = self.settings.chain_contract_address.strip()
        if configured:
            contract = self.contract_at(configured)
            if contract.functions.totalSupply().call() != 0:
                raise ChainError("指定合约已有余额，需要使用独立的新测试合约")
        else:
            factory = self.w3.eth.contract(abi=self.artifact["abi"], bytecode=self.artifact["bytecode"])
            _, raw = self.prepare(factory.constructor(False), signer, self.key, gas=3_000_000)
            receipt = self._send_and_wait(raw)
            contract = self.contract_at(receipt["contractAddress"])
        if contract.functions.transferable().call() or contract.functions.decimals().call() != 0:
            raise ChainError("VCR 合约配置与本地积分规则不一致")
        marker = "0x" + secrets.token_hex(32)
        _, raw = self.prepare(contract.functions.configureShadow(marker_bytes(marker)), signer, self.key)
        receipt = self._send_and_wait(raw)
        return Deployment(chain_id, contract.address, marker, receipt["blockNumber"])

    def wallet(self, session: Session, user_id: int) -> ChainWallet:
        wallet = session.get(ChainWallet, user_id)
        if wallet is None:
            account = self.w3.eth.account.create()
            wallet = ChainWallet(
                user_id=user_id, address=account.address, private_key=self.w3.to_hex(account.key)
            )
            session.add(wallet)
        session.commit()
        return wallet

    def ensure_allowance(self, contract, wallet: ChainWallet, signer: str, amount: int) -> None:
        if contract.functions.allowance(wallet.address, signer).call() >= amount:
            return
        if self.w3.eth.get_balance(wallet.address) < TX_GAS * self.w3.eth.gas_price:
            funding = self._params(signer, 21_000)
            funding.update(to=wallet.address, value=max(10**16, 2 * TX_GAS * funding["gasPrice"]))
            _, raw = self._sign(funding, self.key)
            self._send_and_wait(raw)
        approve = contract.functions.approve(signer, max(amount, STANDING_ALLOWANCE))
        _, raw = self.prepare(approve, wallet.address, wallet.private_key)
        self._send_and_wait(raw)

    def receipt(self, tx_hash: str):
        try:
            return self.w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None


def marker_bytes(value: str) -> bytes:
    return bytes.fromhex(value.removeprefix("0x"))


def provision(session: Session, *, replace: bool = False) -> Deployment:
    """Run from setup_chain.py with the web server stopped."""
    current = deployment_of(session)
    legacy = session.get(ChainState, CONTRACT_STATE_KEY)
    legacy_address = legacy.value if legacy else None
    session.rollback()

    chain = _Chain()
    try:
        if current and not replace:
            chain.contract(current)
            return current
        if legacy_address and not replace:
            raise ChainError("发现旧测试合约，请先预览，再显式选择 --new-deployment")
        deployment = chain.provision()
    finally:
        chain.close()

    # Snapshot the authoritative ledger once. Archive old jobs under their original
    # identifiers so a switch does not replay historical transactions on the new contract.
    if current or legacy_address:
        archive = session.get(ChainState, ARCHIVE_STATE_KEY)
        deployments = json.loads(archive.value) if archive else []
        deployments.append(asdict(current) if current else {"address": legacy_address})
        session.merge(ChainState(key=ARCHIVE_STATE_KEY, value=json.dumps(deployments), updated_at=utcnow()))
    session.execute(
        update(ChainOp)
        .where(ChainOp.status.in_((*ACTIVE, "failed")))
        .values(status="superseded", signed_tx=None, lease_token=None, lease_until=None)
    )
    for account in session.scalars(select(CreditAccount).where(CreditAccount.balance > 0)):
        session.add(ChainOp(
            user_id=account.user_id,
            kind="mint",
            amount=account.balance,
            ref=f"opening:{deployment.operation_namespace[2:26]}:{account.user_id}",
            deployment_id=deployment.operation_namespace,
        ))
    for key, value in (
        (CONTRACT_STATE_KEY, deployment.address),
        (DEPLOYMENT_STATE_KEY, json.dumps(asdict(deployment))),
    ):
        session.merge(ChainState(key=key, value=value, updated_at=utcnow()))
    session.commit()
    return deployment


def enqueue(session: Session, *, user_id: int, kind: str, amount: int, ref: str) -> ChainOp | None:
    if not get_settings().chain_enabled or amount <= 0:
        return None
    if kind not in ("mint", "consume"):
        raise ValueError("unknown credit movement")
    existing = session.scalar(select(ChainOp).where(ChainOp.ref == ref))
    if existing is not None:
        return existing
    deployment = deployment_of(session)
    job = ChainOp(
        user_id=user_id, kind=kind, amount=amount, ref=ref,
        deployment_id=deployment.operation_namespace if deployment else None,
    )
    session.add(job)
    return job


def _sync(session: Session, chain: _Chain, deployment: Deployment, job: ChainOp) -> None:
    contract = chain.contract(deployment)
    wallet = chain.wallet(session, job.user_id)
    operation_id = chain.w3.keccak(text=f"{deployment.operation_namespace}:{job.ref}")
    credited = job.kind == "mint"
    event = contract.events.ShadowOperation()

    def confirm(receipt) -> None:
        for log in event.process_receipt(receipt, errors=DISCARD):
            args = log["args"]
            if (
                log["address"] == deployment.address and args["operationId"] == operation_id
                and args["user"] == wallet.address and args["amount"] == job.amount
                and args["credited"] == credited
            ):
                return
        raise ChainRejected("交易回执与积分流水不一致")

    tx_hash, raw = job.tx_hash, job.signed_tx
    if tx_hash is None or raw is None:
        # A previously applied operation is recoverable from its indexed event.
        if contract.functions.shadowApplied(operation_id).call():
            logs = event.get_logs(
                from_block=deployment.first_block, argument_filters={"operationId": operation_id}
            )
            if len(logs) != 1:
                raise ChainRejected("无法关联已执行的积分操作")
            tx_hash = chain.w3.to_hex(logs[0]["transactionHash"])
            receipt = chain.receipt(tx_hash)
            if receipt is None:
                raise ChainError("已执行交易的回执暂不可用")
            confirm(receipt)
            chain_outbox.release(session, job, status="done", tx_hash=tx_hash, error=None)
            return
        signer = chain.signer()
        if credited:
            fn = contract.functions.mintWithRef(wallet.address, job.amount, operation_id)
        else:
            chain.ensure_allowance(contract, wallet, signer, job.amount)
            fn = contract.functions.consume(wallet.address, job.amount, operation_id)
        tx_hash, raw = chain.prepare(fn, signer, chain.key)
        if not chain_outbox.save(
            session, job, tx_hash=tx_hash, signed_tx=raw, status="submitted",
            video_id_hash=chain.w3.to_hex(operation_id),
        ):
            return
    receipt = chain.receipt(tx_hash)
    if receipt is None:
        try:
            chain.w3.eth.send_raw_transaction(raw)
        except Web3RPCError:
            if chain.receipt(tx_hash) is None:
                raise
        receipt = chain.receipt(tx_hash)
    if receipt is None:
        chain_outbox.release(
            session, job, status="submitted", next_attempt_at=utcnow() + timedelta(seconds=1)
        )
        return
    if receipt["status"] != 1:
        raise ChainRejected("积分交易在测试链执行失败")
    confirm(receipt)
    chain_outbox.release(
        session, job, status="done", signed_tx=None, error=None,
        next_attempt_at=None, updated_at=utcnow(),
    )


def execute_pending(session: Session, limit: int = 10) -> int:
    settings = get_settings()
    if not settings.chain_enabled or settings.chain_sync_paused:
        return 0
    deployment = deployment_of(session)
    session.commit()
    if deployment is None:
        return 0
    failed = aliased(ChainOp)
    candidates = select(ChainOp.id).where(
        ChainOp.deployment_id == deployment.operation_namespace,
        ChainOp.status.in_(ACTIVE),
        ~select(failed.id).where(
            failed.deployment_id == ChainOp.deployment_id, failed.user_id == ChainOp.user_id,
            failed.id < ChainOp.id, failed.status == "failed",
        ).exists(),
    )
    chain = _Chain()
    processed = 0
    try:
        for _ in range(limit):
            now = utcnow()
            # Always claim the head first so different workers cannot allocate competing nonces.
            job = chain_outbox.claim(session, ChainOp, candidates, now)
            if job is None:
                break
            try:
                _sync(session, chain, deployment, job)
            except ChainRejected:
                chain_outbox.release(
                    session, job, status="failed", error="chain_rejected", updated_at=utcnow()
                )
            except Exception as exc:
                logger.warning("VCR operation %s will retry (%s)", job.id, type(exc).__name__)
                session.rollback()
                count = job.attempts + 1
                chain_outbox.release(
                    session, job, attempts=count, error="chain_unavailable", updated_at=utcnow(),
                    next_attempt_at=utcnow() + timedelta(seconds=min(2 ** min(count, 6), 60)),
                )
            processed += 1
    finally:
        chain.close()
    return processed


def chain_summary(session: Session, user_id: int) -> dict:
    settings = get_settings()
    account = session.get(CreditAccount, user_id)
    ledger = account.balance if account else 0
    result = {
        "enabled": settings.chain_enabled,
        "ledger_balance": ledger,
        "available_balance": ledger - (account.frozen if account else 0),
        "sync_status": "disabled",
    }
    if not settings.chain_enabled:
        return result

    deployment = deployment_of(session)
    wallet = session.get(ChainWallet, user_id)
    recent = select(ChainOp).where(ChainOp.user_id == user_id)
    if deployment is not None:
        recent = recent.where(ChainOp.deployment_id == deployment.operation_namespace)
    ops = session.scalars(recent.order_by(ChainOp.id.desc()).limit(10))
    result["recent_ops"] = [
        {
            "id": op.id, "kind": op.kind, "amount": op.amount, "ref": op.ref,
            "tx_hash": op.tx_hash, "status": op.status, "created_at": op.created_at.isoformat(),
        }
        for op in ops
    ]
    if deployment is None:
        result["sync_status"] = "setup_required"
        return result

    result.update(
        chain_id=deployment.chain_id, contract=deployment.address,
        address=wallet.address if wallet else None,
    )
    statuses = set(session.scalars(select(ChainOp.status).where(
        ChainOp.user_id == user_id, ChainOp.deployment_id == deployment.operation_namespace,
        ChainOp.status.in_((*ACTIVE, "failed")),
    )))
    chain = None
    try:
        chain = _Chain()
        contract = chain.contract(deployment)
        balance = int(contract.functions.balanceOf(wallet.address).call()) if wallet else 0
        result.update(on_chain_balance=balance, total_supply=int(contract.functions.totalSupply().call()))
    except Exception:
        result.update(sync_status="unavailable", error="暂时无法读取本地测试链")
        return result
    finally:
        if chain is not None:
            chain.close()
    if "failed" in statuses:
        result["sync_status"] = "failed"
    elif settings.chain_sync_paused:
        result["sync_status"] = "paused"
    elif statuses:
        result["sync_status"] = "pending"
    else:
        result["sync_status"] = "synced" if ledger == balance else "out_of_sync"
    return result
