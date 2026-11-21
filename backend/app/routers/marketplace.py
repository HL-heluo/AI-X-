"""Public verification and authenticated work trading."""

from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, StringConstraints

from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.enums import ErrorCode
from app.errors import AppError
from app.security import JWT_ALGORITHM
from app.services import marketplace, work_publication
from app.services.storage import build_storage
from app.types import utcnow

router = APIRouter(tags=["作品交易与公开核验"])

Price = Annotated[int, Field(strict=True, ge=1, le=1_000_000_000)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


class PublicationIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    author_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    show_prompt: bool = False


class ListingIn(BaseModel):
    asset_id: Annotated[int, Field(strict=True, ge=1)]
    price: Price
    buyer_username: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None


class PurchaseIn(BaseModel):
    price: Price


@router.get("/public/evidence/{evidence_id}")
def public_evidence(evidence_id: str, session: DbSession, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return work_publication.verify_public(session, evidence_id)


@router.get("/assets/{asset_id}/publication")
def publication(asset_id: int, user: CurrentUser, session: DbSession) -> dict:
    return work_publication.get_publication(session, user, asset_id)


@router.post("/assets/{asset_id}/publication")
def publish(asset_id: int, body: PublicationIn, user: CurrentUser, session: DbSession) -> dict:
    return work_publication.publish(session, user, asset_id, **body.model_dump())


@router.delete("/assets/{asset_id}/publication")
def revoke(asset_id: int, user: CurrentUser, session: DbSession) -> dict:
    work_publication.revoke(session, user, asset_id)
    return {"ok": True}


@router.get("/marketplace/works/{asset_id}")
def work_info(asset_id: int, user: CurrentUser, session: DbSession) -> dict:
    return marketplace.work_info(session, user, asset_id)


@router.get("/marketplace/listings")
def listings(user: CurrentUser, session: DbSession, page: Page = 1, page_size: PageSize = 30) -> dict:
    return marketplace.listings(session, user, page, page_size)


@router.post("/marketplace/listings", status_code=201)
def list_work(body: ListingIn, user: CurrentUser, session: DbSession) -> dict:
    return marketplace.list_work(session, user, body.asset_id, body.price, body.buyer_username)


@router.delete("/marketplace/listings/{listing_id}")
def cancel(listing_id: int, user: CurrentUser, session: DbSession) -> dict:
    marketplace.cancel(session, user, listing_id)
    return {"ok": True}


@router.post("/marketplace/listings/{listing_id}/purchase")
def buy(listing_id: int, body: PurchaseIn, user: CurrentUser, session: DbSession) -> dict:
    return marketplace.buy(session, user, listing_id, body.price)


@router.get("/marketplace/trades")
def trades(user: CurrentUser, session: DbSession, page: Page = 1, page_size: PageSize = 30) -> dict:
    return marketplace.trades(session, user, page, page_size)


@router.get("/marketplace/holdings")
def holdings(user: CurrentUser, session: DbSession, page: Page = 1, page_size: PageSize = 30) -> dict:
    return marketplace.holdings(session, user, page, page_size)


@router.post("/marketplace/works/{asset_id}/download-link")
def download_link(asset_id: int, user: CurrentUser, session: DbSession, response: Response) -> dict:
    marketplace.download_asset(session, user.id, asset_id)
    token = jwt.encode(
        {"uid": user.id, "asset": asset_id, "aud": "work-download", "exp": utcnow() + timedelta(minutes=2)},
        get_settings().jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"path": f"/marketplace/download/{token}"}


@router.get("/marketplace/download/{token}")
def download(token: str, session: DbSession) -> Response:
    try:
        claims = jwt.decode(
            token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM], audience="work-download",
            options={"require": ["exp", "uid", "asset"]},
        )
    except jwt.PyJWTError:
        raise AppError(ErrorCode.NOT_FOUND, "下载链接无效或已过期") from None
    asset = marketplace.download_asset(session, claims["uid"], claims["asset"])
    storage = build_storage()
    if not storage.exists(asset.storage_key):
        raise AppError(ErrorCode.NOT_FOUND, "作品原片暂不可用")
    try:
        original = storage.read_bytes(asset.storage_key)
    except FileNotFoundError:
        raise AppError(ErrorCode.NOT_FOUND, "作品原片暂不可用") from None
    return Response(
        content=original, media_type=asset.mime or "video/mp4",
        headers={"Content-Disposition": f'attachment; filename="video-{asset.id}.mp4"', "Cache-Control": "no-store"},
    )
