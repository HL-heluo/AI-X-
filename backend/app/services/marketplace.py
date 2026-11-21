"""Trading transfers the platform holding and VCR credits in one transaction."""

from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AssetKind, ErrorCode
from app.errors import AppError
from app.models import (
    Asset, CreditAccount, EvidenceRecord, User, WorkHolding, WorkListing,
    WorkPublication, WorkTrade,
)
from app.services import accounts, assets, credits
from app.services.unit import atomic


def _receipt(session: Session, asset_id: int) -> EvidenceRecord:
    receipt = session.scalar(select(EvidenceRecord).where(
        EvidenceRecord.asset_id == asset_id, EvidenceRecord.status == "committed",
    ))
    if receipt is None:
        raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
    return receipt


def _check_registry(receipt: EvidenceRecord) -> None:
    settings = get_settings()
    if not settings.fabric_enabled or (
        receipt.network_id, receipt.channel, receipt.chaincode
    ) != (settings.fabric_network_id, settings.fabric_channel, settings.fabric_chaincode):
        raise AppError(ErrorCode.INVALID_REQUEST, "此作品的存证账本当前未启用")


def _holder(session: Session, asset: Asset, receipt: EvidenceRecord) -> WorkHolding:
    holding = session.get(WorkHolding, receipt.id)
    return holding or WorkHolding(evidence_record_id=receipt.id, holder_id=asset.user_id, sequence=0)


def _active(session: Session, receipt_id: int) -> WorkListing | None:
    return session.scalar(select(WorkListing).where(
        WorkListing.evidence_record_id == receipt_id, WorkListing.status == "active",
    ))


def _labels(session: Session, receipt: EvidenceRecord) -> tuple[str, str]:
    publication = session.get(WorkPublication, receipt.id)
    if publication is not None and publication.visible:
        return publication.title, publication.author_name
    return f"视频作品 {receipt.evidence_id[:8]}", "作者未公开署名"


def _work_data(session: Session, user: User, asset: Asset, receipt: EvidenceRecord) -> dict:
    holder_id = _holder(session, asset, receipt).holder_id
    holder_name = session.scalar(select(User.username).where(User.id == holder_id))
    title, author_name = _labels(session, receipt)
    listing = _active(session, receipt.id)
    return {
        "asset_id": asset.id,
        "evidence_id": receipt.evidence_id,
        "title": title,
        "author_name": author_name,
        "holder_name": holder_name,
        "is_holder": holder_id == user.id,
        "active_listing_id": listing.id if listing and listing.seller_id == user.id else None,
    }


def work_info(session: Session, user: User, asset_id: int) -> dict:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
    receipt = _receipt(session, asset_id)
    if user.id not in (asset.user_id, _holder(session, asset, receipt).holder_id):
        raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
    return _work_data(session, user, asset, receipt)


def _listing_data(session: Session, listing: WorkListing, receipt: EvidenceRecord, user_id: int) -> dict:
    title, author_name = _labels(session, receipt)
    return {
        "id": listing.id,
        "asset_id": receipt.asset_id,
        "evidence_id": receipt.evidence_id,
        "title": title,
        "author_name": author_name,
        "seller_name": session.scalar(select(User.username).where(User.id == listing.seller_id)),
        "price": listing.price,
        "status": listing.status,
        "created_at": listing.created_at,
        "is_seller": listing.seller_id == user_id,
        "reserved": listing.buyer_id is not None,
    }


def listings(session: Session, user: User, page: int, page_size: int) -> dict:
    conditions = (
        WorkListing.status == "active", EvidenceRecord.status == "committed",
        EvidenceRecord.asset_id.is_not(None),
        or_(WorkListing.buyer_id.is_(None), WorkListing.buyer_id == user.id, WorkListing.seller_id == user.id),
    )
    query = select(WorkListing, EvidenceRecord).join(
        EvidenceRecord, EvidenceRecord.id == WorkListing.evidence_record_id,
    ).where(*conditions)
    rows = session.execute(query.order_by(WorkListing.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "items": [_listing_data(session, listing, receipt, user.id) for listing, receipt in rows],
        "page": page,
        "page_size": page_size,
        "total": session.scalar(select(func.count()).select_from(query.subquery())),
    }


def list_work(session: Session, user: User, asset_id: int, price: int, buyer_username: str | None) -> dict:
    with atomic(session):
        asset = assets.lock_asset(session, asset_id)
        receipt = _receipt(session, asset_id)
        holding = _holder(session, asset, receipt)
        if holding.holder_id != user.id:
            raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
        _check_registry(receipt)
        if asset.kind != AssetKind.video or not asset.storage_key:
            raise AppError(ErrorCode.INVALID_REQUEST, "此作品没有可交付的视频文件")
        if _active(session, receipt.id) is not None:
            raise AppError(ErrorCode.INVALID_REQUEST, "此作品已有有效挂单")
        buyer_id = None
        if buyer_username:
            buyer_id = session.scalar(select(User.id).where(
                User.username_canonical == accounts.canonicalize(buyer_username), User.is_active.is_(True),
            ))
            if buyer_id is None or buyer_id == user.id:
                raise AppError(ErrorCode.INVALID_REQUEST, "请选择另一位有效的买家")
        listing = WorkListing(evidence_record_id=receipt.id, seller_id=user.id, buyer_id=buyer_id, price=price)
        session.add(listing)
        session.flush()
        result = _listing_data(session, listing, receipt, user.id)
    return result


def _lock_listing(session: Session, listing_id: int) -> tuple[WorkListing, Asset, EvidenceRecord]:
    asset_id = session.scalar(select(EvidenceRecord.asset_id).join(
        WorkListing, WorkListing.evidence_record_id == EvidenceRecord.id,
    ).where(WorkListing.id == listing_id))
    if asset_id is None:
        raise AppError(ErrorCode.NOT_FOUND, "没有此挂单")
    asset = assets.lock_asset(session, asset_id)
    listing = session.get(WorkListing, listing_id, populate_existing=True)
    receipt = _receipt(session, asset_id)
    return listing, asset, receipt


def cancel(session: Session, user: User, listing_id: int) -> None:
    with atomic(session):
        listing, _, _ = _lock_listing(session, listing_id)
        if listing.seller_id != user.id:
            raise AppError(ErrorCode.NOT_FOUND, "没有此挂单")
        if listing.status == "sold":
            raise AppError(ErrorCode.INVALID_REQUEST, "此挂单已成交")
        listing.status = "cancelled"


def _trade_data(session: Session, user: User, trade: WorkTrade, receipt: EvidenceRecord) -> dict:
    title, author_name = _labels(session, receipt)
    return {
        "trade_id": trade.trade_id,
        "asset_id": receipt.asset_id,
        "evidence_id": receipt.evidence_id,
        "title": title,
        "author_name": author_name,
        "side": "buy" if trade.buyer_id == user.id else "sell",
        "price": trade.price,
        "status": trade.status,
        "tx_id": trade.tx_id,
        "recorded_at": trade.recorded_at,
        "created_at": trade.created_at,
    }


def buy(session: Session, user: User, listing_id: int, price: int) -> dict:
    with atomic(session):
        listing, asset, receipt = _lock_listing(session, listing_id)
        if listing.buyer_id not in (None, user.id) or listing.seller_id == user.id:
            raise AppError(ErrorCode.NOT_FOUND, "没有此挂单")
        if listing.price != price:
            raise AppError(ErrorCode.INVALID_REQUEST, "价格已变化，请重新确认")
        existing = session.scalar(select(WorkTrade).where(WorkTrade.listing_id == listing.id))
        if existing is not None and existing.buyer_id == user.id:
            return _trade_data(session, user, existing, receipt)
        holding = _holder(session, asset, receipt)
        if listing.status != "active" or holding.holder_id != listing.seller_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "此挂单已成交或撤销")
        _check_registry(receipt)

        parties = sorted((user.id, listing.seller_id))
        # Acquire credit locks in the same order for simultaneous opposite trades.
        session.scalars(select(CreditAccount.user_id).where(
            CreditAccount.user_id.in_(parties),
        ).order_by(CreditAccount.user_id).with_for_update()).all()
        trade_id = str(uuid4())
        credits.adjust(session, user.id, -price, f"购买作品 {trade_id}")
        credits.adjust(session, listing.seller_id, price, f"出售作品 {trade_id}")
        refs = {}
        for party in parties:
            refs[party] = session.scalar(update(User).where(User.id == party).values(
                evidence_ref=func.coalesce(User.evidence_ref, uuid4().hex),
            ).returning(User.evidence_ref))
        if holding.sequence == 0:
            session.add(holding)
        holding.holder_id = user.id
        holding.sequence += 1
        listing.status = "sold"
        trade = WorkTrade(
            trade_id=trade_id, listing_id=listing.id, evidence_record_id=receipt.id,
            buyer_id=user.id, seller_id=listing.seller_id, price=price, sequence=holding.sequence,
            payload={
                "tradeId": trade_id, "videoId": receipt.evidence_id, "sequence": holding.sequence,
                "fromHolder": refs[listing.seller_id], "toHolder": refs[user.id], "price": price,
            },
        )
        session.add(trade)
        session.flush()
        result = _trade_data(session, user, trade, receipt)
    return result


def trades(session: Session, user: User, page: int, page_size: int) -> dict:
    query = select(WorkTrade, EvidenceRecord).join(
        EvidenceRecord, EvidenceRecord.id == WorkTrade.evidence_record_id,
    ).where(or_(WorkTrade.buyer_id == user.id, WorkTrade.seller_id == user.id))
    rows = session.execute(query.order_by(WorkTrade.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "items": [_trade_data(session, user, trade, receipt) for trade, receipt in rows],
        "page": page,
        "page_size": page_size,
        "total": session.scalar(select(func.count()).select_from(query.subquery())),
    }


def holdings(session: Session, user: User, page: int, page_size: int) -> dict:
    query = select(Asset, EvidenceRecord).join(
        EvidenceRecord, EvidenceRecord.asset_id == Asset.id,
    ).outerjoin(WorkHolding, WorkHolding.evidence_record_id == EvidenceRecord.id).where(
        EvidenceRecord.status == "committed",
        func.coalesce(WorkHolding.holder_id, Asset.user_id) == user.id,
    )
    rows = session.execute(query.order_by(Asset.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "items": [_work_data(session, user, asset, receipt) for asset, receipt in rows],
        "page": page,
        "page_size": page_size,
        "total": session.scalar(select(func.count()).select_from(query.subquery())),
    }


def download_asset(session: Session, user_id: int, asset_id: int) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or not asset.storage_key:
        raise AppError(ErrorCode.NOT_FOUND, "没有可下载的作品")
    receipt = _receipt(session, asset_id)
    user = session.get(User, user_id)
    if user is None or not user.is_active or _holder(session, asset, receipt).holder_id != user_id:
        raise AppError(ErrorCode.NOT_FOUND, "没有可下载的作品")
    return asset
