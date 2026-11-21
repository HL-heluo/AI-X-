import hashlib
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.database import get_session_factory
from app.errors import AppError
from app.models import Asset, ChainOp, ChainState, ChainWallet, EvidenceRecord
from app.services import chain_credits, credits, evidence, storage
from app.services.unit import atomic
from _helpers import new_user, submit_image, submit_video


async def test_adjustment_debit_and_read_only_chain_card(api, settings_env):
    settings_env(CHAIN_ENABLED="1")
    headers, account = await new_user(api, "chain_reader")
    user_id = account["user"]["id"]

    with get_session_factory()() as session:
        with atomic(session):
            credits.adjust(session, user_id, -7, "手工扣减")
        with pytest.raises(AppError), atomic(session):
            credits.adjust(session, user_id, -44, "可用额度不足")
        assert credits.account_of(session, user_id).balance == 43

    for _ in range(2):
        card = (await api.get("/credits/chain", headers=headers)).json()
        assert card["sync_status"] == "setup_required"
        assert card["available_balance"] == card["ledger_balance"] == 43
        assert "rpc" not in card
    ledger = (await api.get("/credits/ledger", headers=headers)).json()["items"]
    assert ledger[0]["amount"] == 7 and ledger[0]["adjustment_debit"] is True
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(ChainWallet)) == 0
        assert session.scalar(select(func.count()).select_from(ChainState)) == 0
        jobs = session.scalars(select(ChainOp).order_by(ChainOp.id)).all()
        assert [(job.kind, job.amount) for job in jobs] == [("mint", 50), ("consume", 7)]


async def test_video_evidence_recovers_lost_submission_and_respects_owner(api, settings_env, monkeypatch):
    settings_env(FABRIC_ENABLED="1", FABRIC_NETWORK_ID="test-fabric", CHAIN_ENABLED="0")
    owner, _ = await new_user(api, "video_author")
    other, _ = await new_user(api, "other_author")
    image = await submit_image(api, owner)
    assert image.status_code == 200, image.text
    images = (await api.get(f"/assets?task_id={image.json()['id']}", headers=owner)).json()
    video = await submit_video(api, owner, source_asset_id=images["items"][0]["id"])
    assert video.status_code == 200, video.text
    videos = (await api.get(f"/assets?task_id={video.json()['id']}", headers=owner)).json()
    asset_id = next(asset["id"] for asset in videos["items"] if asset["kind"] == "video")
    url = f"/assets/{asset_id}/evidence"
    initial = (await api.get(url, headers=owner)).json()
    assert initial["status"] == "pending"
    assert (await api.get(url, headers=other)).status_code == 404

    committed = None
    posts = 0

    def bridge(request):
        nonlocal committed, posts
        if request.url.path == "/v1/registry":
            return httpx.Response(200, json={
                "networkId": "test-fabric", "channel": "videochannel",
                "chaincode": "video-evidence", "schemaVersion": 3,
            })
        if request.method == "POST":
            posts += 1
            committed = {
                **json.loads(request.content), "ledgerTxId": "a" * 64,
                "createdAtTx": "2026-11-18T00:00:00Z",
            }
            raise httpx.ReadTimeout("simulated lost response", request=request)
        return httpx.Response(200, json={"record": committed})

    client = httpx.Client
    monkeypatch.setattr(evidence.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(bridge), **kw))
    with get_session_factory()() as session:
        asset = session.get(Asset, asset_id)
        digest = hashlib.sha256(storage.build_storage().read_bytes(asset.storage_key)).hexdigest()
        assert initial["sha256"] == digest
        session.rollback()
        evidence.execute_pending(session)
        job = session.scalar(select(EvidenceRecord))
        assert job.status == "pending"
        job.next_attempt_at = None
        session.commit()
        evidence.execute_pending(session)

    receipt = (await api.get(url, headers=owner)).json()
    assert receipt["status"] == "committed" and receipt["tx_id"] == "a" * 64
    assert posts == 1
    own = (await api.get("/assets?certified_only=true", headers=owner)).json()
    assert [asset["id"] for asset in own["items"]] == [asset_id]
    assert (await api.get("/assets?certified_only=true", headers=other)).json()["total"] == 0


@pytest.fixture
def ganache_rpc():
    workdir = Path(__file__).resolve().parents[2] / "双链存证"
    if shutil.which("node") is None or not (workdir / "node_modules" / "ganache").exists():
        pytest.skip("Requires local Ganache dependencies")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    code = (
        "const g = require('ganache').server({chain:{chainId:1337},logging:{quiet:true}});"
        f"g.listen({port}, '127.0.0.1');"
    )
    process = subprocess.Popen(["node", "-e", code], cwd=workdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    break
            except OSError:
                if process.poll() is not None:
                    pytest.fail("Ganache exited before opening RPC")
                time.sleep(0.1)
        else:
            pytest.fail("Ganache RPC was not ready")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)


async def test_ganache_sync_recovers_original_transactions(api, settings_env, ganache_rpc, monkeypatch):
    settings_env(CHAIN_ENABLED="1", CHAIN_RPC_URL=ganache_rpc, CHAIN_PLATFORM_PRIVATE_KEY="", CHAIN_CONTRACT_ADDRESS="")
    with get_session_factory()() as session:
        chain_credits.provision(session)
    headers, _ = await new_user(api, "ganache_user")
    real_receipt = chain_credits._Chain.receipt
    monkeypatch.setattr(chain_credits._Chain, "receipt", lambda *_: None)
    with get_session_factory()() as session:
        chain_credits.execute_pending(session)
        job = session.scalar(select(ChainOp))
        assert job.status == "submitted" and job.signed_tx and job.tx_hash, job.error
        original_hash = job.tx_hash
        job.next_attempt_at = None
        session.commit()
    monkeypatch.setattr(chain_credits._Chain, "receipt", real_receipt)
    with get_session_factory()() as session:
        chain_credits.execute_pending(session)
    initial = (await api.get("/credits/chain", headers=headers)).json()
    assert initial["on_chain_balance"] == 50
    assert initial["recent_ops"][0]["tx_hash"] == original_hash
    assert (await submit_image(api, headers)).status_code == 200
    with get_session_factory()() as session:
        chain_credits.execute_pending(session)
    card = (await api.get("/credits/chain", headers=headers)).json()
    assert card["sync_status"] == "synced", card
    assert card["on_chain_balance"] == card["ledger_balance"] == 46
    assert {op["status"] for op in card["recent_ops"]} == {"done"}

    with get_session_factory()() as session:
        previous = chain_credits.deployment_of(session)
        replacement = chain_credits.provision(session, replace=True)
        chain_credits.execute_pending(session)
        archived = session.get(ChainState, chain_credits.ARCHIVE_STATE_KEY)
        assert json.loads(archived.value)[-1]["address"] == previous.address
    new_card = (await api.get("/credits/chain", headers=headers)).json()
    assert new_card["contract"] == replacement.address != previous.address
    assert new_card["on_chain_balance"] == new_card["ledger_balance"] == 46
    assert len(new_card["recent_ops"]) == 1
    assert new_card["recent_ops"][0]["kind"] == "mint"
