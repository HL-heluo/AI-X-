import asyncio
import hashlib
import json

import httpx
from sqlalchemy import select

from _helpers import new_user
from app.database import get_session_factory
from app.enums import AssetKind, TaskKind, TaskStatus
from app.models import Asset, ChainOp, EvidenceRecord, Task, WorkHolding, WorkTrade
from app.services import chain_credits, evidence, storage, work_trade_sync
from app.types import utcnow
from test_local_chain_workflows import ganache_rpc  # noqa: F401


ORIGINAL = b"video fixture bytes"
PROMPT = "a private video prompt"
PUBLIC = {"title": "Public title", "author_name": "Author display name", "description": "Story"}


def committed_work(user_id):
    with get_session_factory()() as session:
        task = Task(
            user_id=user_id, kind=TaskKind.image_to_video, status=TaskStatus.succeeded,
            prompt=PROMPT, settled_amount=0,
        )
        session.add(task)
        session.flush()
        asset = Asset(
            user_id=user_id, task_id=task.id, kind=AssetKind.video,
            storage_key=f"test/{task.id}/video.mp4", public_url="http://test/video.mp4",
            mime="video/mp4", size_bytes=len(ORIGINAL),
        )
        session.add(asset)
        session.flush()
        storage.build_storage().put_bytes(asset.storage_key, ORIGINAL, content_type=asset.mime)
        digest = hashlib.sha256(ORIGINAL).hexdigest()
        evidence.enqueue(session, asset, task, digest)
        session.flush()
        receipt = session.scalar(select(EvidenceRecord).where(EvidenceRecord.asset_id == asset.id))
        receipt.status = "committed"
        receipt.tx_id = "a" * 64
        receipt.recorded_at = utcnow()
        session.commit()
        return asset.id, receipt.evidence_id, digest


async def test_publication_controls_access_to_confirmed_evidence(api, settings_env):
    settings_env(FABRIC_ENABLED="1", STORAGE="local")
    author, session = await new_user(api, "public_author")
    other, _ = await new_user(api, "different_user")
    asset_id, evidence_id, digest = committed_work(session["user"]["id"])
    edit = f"/assets/{asset_id}/publication"
    verify = f"/public/evidence/{evidence_id}"

    missing = await api.get(verify)
    assert missing.status_code == 404
    assert (await api.get("/public/evidence/not-an-id")).json() == missing.json()
    assert (await api.post(edit, headers=other, json=PUBLIC)).status_code == 404
    publication = await api.post(edit, headers=author, json={**PUBLIC, "show_prompt": True})
    assert publication.status_code == 200, publication.text
    proof = await api.get(verify)
    assert proof.status_code == 200, proof.text
    assert proof.headers["cache-control"] == "no-store"
    assert proof.json() == {
        **PUBLIC, "prompt": PROMPT, "sha256": digest, "evidence_id": evidence_id,
        "tx_id": "a" * 64, "channel": "videochannel", "recorded_at": proof.json()["recorded_at"],
        "transfers": [],
    }
    assert (await api.post(edit, headers=author, json=PUBLIC)).status_code == 200
    assert (await api.get(verify)).json()["prompt"] is None
    assert (await api.delete(edit, headers=other)).status_code == 404
    assert (await api.delete(edit, headers=author)).status_code == 200
    assert (await api.get(verify)).json() == missing.json()


async def test_marketplace_concurrent_purchase_transfers_credits_and_recovers_receipts(
    api, settings_env, ganache_rpc, monkeypatch,
):
    settings_env(
        FABRIC_ENABLED="1", FABRIC_NETWORK_ID="market-test", STORAGE="local",
        CHAIN_ENABLED="1", CHAIN_RPC_URL=ganache_rpc,
        CHAIN_PLATFORM_PRIVATE_KEY="", CHAIN_CONTRACT_ADDRESS="",
    )
    with get_session_factory()() as session:
        chain_credits.provision(session)
    author, author_session = await new_user(api, "market_author")
    buyer, buyer_session = await new_user(api, "market_buyer")
    other, other_session = await new_user(api, "market_other")
    author_id = author_session["user"]["id"]
    asset_id, evidence_id, _ = committed_work(author_id)
    assert (await api.post(f"/assets/{asset_id}/publication", headers=author, json=PUBLIC)).status_code == 200

    async def list_for(headers, price, buyer_username=None):
        response = await api.post("/marketplace/listings", headers=headers, json={
            "asset_id": asset_id, "price": price, "buyer_username": buyer_username,
        })
        assert response.status_code == 201, response.text
        return response.json()["id"]

    expensive = await list_for(author, 51, "market_buyer")
    url = f"/marketplace/listings/{expensive}/purchase"
    assert (await api.get("/marketplace/listings", headers=other)).json()["total"] == 0
    assert (await api.post(url, headers=other, json={"price": 51})).status_code == 404
    balance_error = await api.post(url, headers=buyer, json={"price": 51})
    assert balance_error.json()["code"] == "INSUFFICIENT_CREDITS"
    assert (await api.delete(f"/marketplace/listings/{expensive}", headers=author)).status_code == 200
    assert (await api.post(url, headers=buyer, json={"price": 51})).status_code == 400

    listing = await list_for(author, 50)
    purchase = f"/marketplace/listings/{listing}/purchase"
    responses = await asyncio.gather(*(
        api.post(purchase, headers=headers, json={"price": 50}) for headers in (buyer, other)
    ))
    assert sorted(response.status_code for response in responses) == [200, 400]
    first = next(response.json() for response in responses if response.status_code == 200)
    winning_index = next(i for i, response in enumerate(responses) if response.status_code == 200)
    winner = (buyer, other)[winning_index]
    winner_session = (buyer_session, other_session)[winning_index]
    retry = await api.post(purchase, headers=winner, json={"price": 50})
    assert retry.json()["trade_id"] == first["trade_id"]

    with get_session_factory()() as session:
        chain_credits.execute_pending(session, limit=20)
    for headers, expected in ((author, 100), (winner, 0)):
        balances = (await api.get("/credits/chain", headers=headers)).json()
        assert balances["on_chain_balance"] == balances["ledger_balance"] == expected, balances
    work = (await api.get(f"/marketplace/works/{asset_id}", headers=winner)).json()
    assert work["is_holder"] and work["author_name"] == PUBLIC["author_name"]
    assert (await api.delete(f"/assets/{asset_id}", headers=author)).status_code == 400

    ticket = await api.post(f"/marketplace/works/{asset_id}/download-link", headers=winner)
    assert ticket.status_code == 200, ticket.text
    assert (await api.get(ticket.json()["path"])).content == ORIGINAL
    not_owner = await api.post(f"/marketplace/works/{asset_id}/download-link", headers=author)
    assert not_owner.status_code == 404

    resale = await list_for(winner, 10, "market_author")
    second = await api.post(f"/marketplace/listings/{resale}/purchase", headers=author, json={"price": 10})
    assert second.status_code == 200, second.text
    assert (await api.get(ticket.json()["path"])).status_code == 404

    records = {}
    submissions = []
    online = False

    def bridge(request):
        if not online:
            raise httpx.ConnectError("offline", request=request)
        if request.url.path == "/v1/registry":
            return httpx.Response(200, json={
                "networkId": "market-test", "channel": "videochannel",
                "chaincode": "video-evidence", "schemaVersion": 3,
            })
        if request.method == "GET":
            return httpx.Response(200, json={"record": records.get(request.url.path.split("/")[-1])})
        payload = json.loads(request.content)
        submissions.append(payload["sequence"])
        records[payload["tradeId"]] = {
            **payload, "ledgerTxId": str(payload["sequence"]) * 64,
            "createdAtTx": "2026-11-20T01:01:00Z",
        }
        raise httpx.ReadTimeout("lost response after commit", request=request)

    real_client = httpx.Client
    monkeypatch.setattr(work_trade_sync.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(bridge), **kwargs,
    ))
    with get_session_factory()() as session:
        work_trade_sync.execute_pending(session)
        saved = session.scalars(select(WorkTrade).order_by(WorkTrade.sequence)).all()
        assert [(trade.status, trade.attempts) for trade in saved] == [("pending", 1), ("pending", 0)]
        online = True
        for _ in range(3):
            for trade in session.scalars(select(WorkTrade)):
                trade.next_attempt_at = None
            session.commit()
            work_trade_sync.execute_pending(session)
        recorded = session.scalars(select(WorkTrade).order_by(WorkTrade.sequence)
                                    .execution_options(populate_existing=True)).all()
        assert [trade.status for trade in recorded] == ["committed", "committed"]
        assert submissions == [1, 2]
        assert session.scalar(select(WorkHolding.holder_id)) == author_id
        assert len(session.scalars(select(ChainOp).where(ChainOp.ref.like("ledger:%"))).all()) == 7
        assert recorded[0].buyer_id == winner_session["user"]["id"]

    public = (await api.get(f"/public/evidence/{evidence_id}")).json()
    assert [item["tx_id"] for item in public["transfers"]] == ["2" * 64, "1" * 64]
    assert set(public["transfers"][0]) == {"trade_id", "tx_id", "recorded_at"}
