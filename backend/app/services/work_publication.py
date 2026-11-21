"""Author-selected, public fields for a confirmed video receipt."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ErrorCode
from app.errors import AppError
from app.models import Asset, EvidenceRecord, Task, User, WorkPublication, WorkTrade
from app.services import assets
from app.services.unit import atomic
from app.types import utcnow


def _author_receipt(session: Session, user: User, asset_id: int, *, write: bool) -> tuple[Asset, EvidenceRecord]:
    asset = assets.lock_asset(session, asset_id) if write else assets.get_asset(session, user, asset_id)
    if asset.user_id != user.id:
        raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
    receipt = session.scalar(select(EvidenceRecord).where(
        EvidenceRecord.asset_id == asset_id, EvidenceRecord.status == "committed",
    ))
    if receipt is None:
        raise AppError(ErrorCode.NOT_FOUND, "作品尚未完成存证")
    return asset, receipt


def _publication_data(publication: WorkPublication | None) -> dict:
    return {
        "visible": publication.visible if publication else False,
        "title": publication.title if publication else "",
        "author_name": publication.author_name if publication else "",
        "description": publication.description if publication else "",
        "show_prompt": publication is not None and publication.prompt is not None,
    }


def get_publication(session: Session, user: User, asset_id: int) -> dict:
    _, receipt = _author_receipt(session, user, asset_id, write=False)
    return _publication_data(session.get(WorkPublication, receipt.id))


def publish(
    session: Session, user: User, asset_id: int, *,
    title: str, author_name: str, description: str, show_prompt: bool,
) -> dict:
    with atomic(session):
        asset, receipt = _author_receipt(session, user, asset_id, write=True)
        task = session.get(Task, asset.task_id) if show_prompt and asset.task_id is not None else None
        publication = session.get(WorkPublication, receipt.id)
        if publication is None:
            publication = WorkPublication(evidence_record_id=receipt.id)
            session.add(publication)
        publication.title = title
        publication.author_name = author_name
        publication.description = description
        publication.prompt = task.prompt if task is not None else None
        publication.visible = True
        publication.published_at = utcnow()
    return _publication_data(publication)


def revoke(session: Session, user: User, asset_id: int) -> None:
    with atomic(session):
        _, receipt = _author_receipt(session, user, asset_id, write=True)
        publication = session.get(WorkPublication, receipt.id)
        if publication is not None:
            publication.visible = False
            publication.prompt = None


def verify_public(session: Session, evidence_id: str) -> dict:
    try:
        canonical_id = str(UUID(evidence_id))
    except ValueError:
        raise AppError(ErrorCode.NOT_FOUND, "未找到公开记录") from None
    row = session.execute(
        select(EvidenceRecord, WorkPublication)
        .join(WorkPublication, WorkPublication.evidence_record_id == EvidenceRecord.id)
        .where(
            EvidenceRecord.evidence_id == canonical_id,
            EvidenceRecord.asset_id.is_not(None),
            EvidenceRecord.status == "committed",
            WorkPublication.visible.is_(True),
        )
    ).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "未找到公开记录")
    receipt, publication = row
    trades = session.scalars(
        select(WorkTrade).where(
            WorkTrade.evidence_record_id == receipt.id, WorkTrade.status == "committed",
        ).order_by(WorkTrade.sequence.desc()).limit(100)
    )
    return {
        "evidence_id": receipt.evidence_id,
        "tx_id": receipt.tx_id,
        "recorded_at": receipt.recorded_at,
        "sha256": receipt.payload["sha256"],
        "channel": receipt.channel,
        "title": publication.title,
        "author_name": publication.author_name,
        "description": publication.description,
        "prompt": publication.prompt,
        "transfers": [
            {"trade_id": trade.trade_id, "tx_id": trade.tx_id, "recorded_at": trade.recorded_at}
            for trade in trades
        ],
    }
