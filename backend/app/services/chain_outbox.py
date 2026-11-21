"""Short database claims shared by the Ganache and Fabric workers."""

from datetime import datetime, timedelta
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import or_, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models import ChainOp, EvidenceRecord, WorkTrade

Job = TypeVar("Job", ChainOp, EvidenceRecord, WorkTrade)


def due(model: type[Job], now: datetime):
    return or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now)


def claim(session: Session, model: type[Job], candidates: Select, now: datetime) -> Job | None:
    token = uuid4().hex
    job = session.scalar(
        update(model)
        .where(
            model.id == candidates.order_by(model.id).limit(1).scalar_subquery(),
            or_(model.lease_until.is_(None), model.lease_until <= now),
            due(model, now),
        )
        .values(lease_token=token, lease_until=now + timedelta(minutes=3))
        .returning(model)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    if job is not None:
        session.expunge(job)
    session.commit()
    return job


def save(session: Session, job: Job, **values) -> bool:
    model = type(job)
    result = session.execute(
        update(model)
        .where(model.id == job.id, model.lease_token == job.lease_token)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return result.rowcount == 1


def release(session: Session, job: Job, **values) -> None:
    save(session, job, lease_token=None, lease_until=None, **values)
