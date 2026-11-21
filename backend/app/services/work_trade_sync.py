"""Submit trades to Fabric in holding order and confirm by reading them back."""

from datetime import datetime, timedelta
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.models import EvidenceRecord, WorkTrade
from app.services import chain_outbox
from app.types import utcnow


def _sync(session: Session, client: httpx.Client, job: WorkTrade) -> None:
    evidence = session.get(EvidenceRecord, job.evidence_record_id)
    registry = client.get("/v1/registry").raise_for_status().json()
    if (registry["networkId"], registry["channel"], registry["chaincode"], registry["schemaVersion"]) != (
        evidence.network_id, evidence.channel, evidence.chaincode, 3,
    ):
        raise ValueError("Fabric registry differs from the work's original deployment")

    record = client.get(f"/v1/trades/{job.trade_id}").raise_for_status().json()["record"]
    if record is not None:
        if any(record.get(key) != value for key, value in job.payload.items()):
            chain_outbox.release(session, job, status="conflict", next_attempt_at=None)
            return
        tx_id = record["ledgerTxId"]
        if not isinstance(tx_id, str) or not re.fullmatch(r"[0-9a-f]{64}", tx_id):
            raise ValueError("Invalid Fabric trade transaction ID")
        chain_outbox.release(
            session, job, status="committed", tx_id=tx_id, next_attempt_at=None,
            recorded_at=datetime.fromisoformat(record["createdAtTx"]),
        )
        return

    if job.tx_id is not None and job.attempts < 3:
        chain_outbox.release(
            session, job, attempts=job.attempts + 1,
            next_attempt_at=utcnow() + timedelta(seconds=2 ** job.attempts),
        )
        return
    response = client.post("/v1/trades", json=job.payload).raise_for_status().json()
    tx_id = response["txId"]
    if not isinstance(tx_id, str) or not re.fullmatch(r"[0-9a-f]{64}", tx_id):
        raise ValueError("Invalid Fabric trade submission ID")
    chain_outbox.release(
        session, job, status="submitted", tx_id=tx_id, attempts=0,
        next_attempt_at=utcnow() + timedelta(seconds=1),
    )


def execute_pending(session: Session, limit: int = 5) -> None:
    settings = get_settings()
    if not settings.fabric_enabled:
        return
    earlier = aliased(WorkTrade)
    waiting_for_earlier = select(earlier.id).where(
        earlier.evidence_record_id == WorkTrade.evidence_record_id,
        earlier.sequence < WorkTrade.sequence, earlier.status != "committed",
    ).exists()
    with httpx.Client(
        base_url=settings.fabric_bridge_url, trust_env=False, timeout=15,
        headers={"Authorization": f"Bearer {settings.fabric_bridge_token}"},
    ) as client:
        for _ in range(limit):
            now = utcnow()
            job = chain_outbox.claim(session, WorkTrade, select(WorkTrade.id).where(
                WorkTrade.status.in_(("pending", "submitted")),
                chain_outbox.due(WorkTrade, now), ~waiting_for_earlier,
            ), now)
            if job is None:
                break
            try:
                _sync(session, client, job)
            except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError) as exc:
                code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                attempts = job.attempts + 1
                terminal = code in (400, 409, 422)
                chain_outbox.release(
                    session, job, attempts=attempts,
                    status="failed" if terminal else job.status,
                    next_attempt_at=None if terminal else now + timedelta(seconds=min(2 ** min(attempts, 6), 60)),
                )
