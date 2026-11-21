"""Queue a receipt for the delivered video and reconcile it with Fabric."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, EvidenceRecord, Task, User
from app.services import chain_outbox
from app.types import utcnow


def enqueue(session: Session, asset: Asset, task: Task, sha256: str) -> None:
    settings = get_settings()
    if not settings.fabric_enabled:
        return
    owner_ref = session.scalar(
        update(User)
        .where(User.id == asset.user_id)
        .values(evidence_ref=func.coalesce(User.evidence_ref, uuid4().hex))
        .returning(User.evidence_ref)
    )
    evidence_id = str(uuid4())
    session.add(EvidenceRecord(
        asset_id=asset.id,
        evidence_id=evidence_id,
        network_id=settings.fabric_network_id,
        channel=settings.fabric_channel,
        chaincode=settings.fabric_chaincode,
        payload={
            "videoId": evidence_id,
            "ownerId": owner_ref,
            "sha256": sha256,
            "schemaVersion": 3,
            "generationParams": json.dumps({"kind": task.kind.value, "provider": task.provider}, sort_keys=True),
            "mediaMeta": json.dumps({"sizeBytes": asset.size_bytes}, sort_keys=True),
            "width": asset.width,
            "height": asset.height,
            "durationMs": asset.duration_sec * 1000 if asset.duration_sec is not None else None,
        },
    ))


def summary(session: Session, asset_id: int) -> dict:
    job = session.scalar(select(EvidenceRecord).where(EvidenceRecord.asset_id == asset_id))
    if job is None:
        return {"status": "not_recorded" if get_settings().fabric_enabled else "disabled"}
    return {
        "status": job.status,
        "evidence_id": job.evidence_id,
        "sha256": job.payload["sha256"],
        "network_id": job.network_id,
        "channel": job.channel,
        "chaincode": job.chaincode,
        "tx_id": job.tx_id,
        "recorded_at": job.recorded_at,
        "confirmed_at": job.confirmed_at,
    }


def _sync(session: Session, client: httpx.Client, job: EvidenceRecord) -> None:
    registry = client.get("/v1/registry").raise_for_status().json()
    if (registry["networkId"], registry["channel"], registry["chaincode"]) != (
        job.network_id, job.channel, job.chaincode
    ) or registry.get("schemaVersion") != 3:
        raise ValueError("Fabric registry differs from the queued deployment")

    record = client.get(f"/v1/records/{job.evidence_id}").raise_for_status().json()["record"]
    if record is not None:
        if any(record.get(field) != value for field, value in job.payload.items()):
            chain_outbox.release(session, job, status="conflict")
            return
        tx_id = record["ledgerTxId"]
        if len(tx_id) != 64 or any(c not in "0123456789abcdef" for c in tx_id):
            raise ValueError("Invalid Fabric transaction ID")
        chain_outbox.release(
            session, job, status="committed", tx_id=tx_id, next_attempt_at=None,
            recorded_at=datetime.fromisoformat(record["createdAtTx"]), confirmed_at=utcnow(),
        )
        return

    # Give an accepted proposal time to reach the ledger. An unknown prior submission
    # can be retried with the same video ID; Fabric will apply at most one creation.
    if job.tx_id is not None and job.attempts < 3:
        chain_outbox.release(
            session, job, attempts=job.attempts + 1,
            next_attempt_at=utcnow() + timedelta(seconds=2 ** job.attempts),
        )
        return
    result = client.post("/v1/records", json=job.payload).raise_for_status().json()
    chain_outbox.release(
        session, job, status="submitted", tx_id=result["txId"], attempts=0,
        next_attempt_at=utcnow() + timedelta(seconds=1),
    )


def execute_pending(session: Session, limit: int = 5) -> None:
    settings = get_settings()
    if not settings.fabric_enabled:
        return
    with httpx.Client(
        base_url=settings.fabric_bridge_url, trust_env=False, timeout=15,
        headers={"Authorization": f"Bearer {settings.fabric_bridge_token}"},
    ) as client:
        for _ in range(limit):
            now = utcnow()
            job = chain_outbox.claim(
                session, EvidenceRecord,
                select(EvidenceRecord.id).where(
                    EvidenceRecord.status.in_(("pending", "submitted")),
                    chain_outbox.due(EvidenceRecord, now),
                ), now,
            )
            if job is None:
                break
            try:
                _sync(session, client, job)
            except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                attempts = job.attempts + 1
                # An unknown commit can still be recovered by reading its video ID.
                chain_outbox.release(
                    session, job, attempts=attempts,
                    status="failed" if status in (400, 422) else job.status,
                    next_attempt_at=now + timedelta(seconds=min(2 ** min(attempts, 6), 60)),
                )
