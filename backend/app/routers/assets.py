"""资产 —— `GET /assets` / `DELETE /assets/{id}`。§9.4 / §12.1。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.enums import AssetKind, ErrorCode
from app.errors import AppError
from app.schemas import AssetOut, EvidenceOut, OkOut, PageOut
from app.services import assets, evidence

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

router = APIRouter(prefix="/assets", tags=["资产"])


@router.get("", response_model=PageOut[AssetOut], summary="我的作品（分页，最新在前）")
def list_assets(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    task_id: int | None = Query(None, description="只看某个任务的产物"),
    certified_only: bool = Query(False, description="只看存证已确认的视频"),
) -> PageOut[AssetOut]:
    """`{items, page, page_size, total}`。

    【`task_id` 过滤是干什么用的】作品详情页要看「这一条任务产出了什么」
    （视频 + 它的封面）。不传就是全部作品（作品列表页）。
    前端 `RemoteAssetRepository.fetchAssets` 用 Dart 的 null-aware element
    写法（`'task_id': ?taskId`）—— **null 时整个键都不出现**，
    而不是发一个 `task_id=`。这两种在 FastAPI 里都安全
    （空串会被当作没传），但知道它发的是前者更省事。

    ⚠️ **`public_url` 背后现在没有文件**（B2 不写字节），打开是 404。
    原因见 `services/storage.py` 的文件头 —— 这与今天 Mock 的
    `mock-oss.local` 行为一致，不是本批引入的 bug。

    ⚠️ 响应里**没有 `storage_key`**（内部路径）**也没有 `provider_url`**
    （即梦的 1 小时临时地址）。两条都是刻意的，前端有守卫测试盯着。
    """
    rows, total = assets.list_assets(
        session, user, page=page, page_size=page_size, task_id=task_id, certified_only=certified_only,
    )
    return PageOut[AssetOut](
        items=[AssetOut.from_asset(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{asset_id}/evidence", response_model=EvidenceOut, summary="视频存证回执")
def asset_evidence(asset_id: int, user: CurrentUser, session: DbSession) -> EvidenceOut:
    asset = assets.get_asset(session, user, asset_id)
    if asset.kind is not AssetKind.video:
        raise AppError(ErrorCode.NOT_FOUND, "没有此视频资产")
    return EvidenceOut(**evidence.summary(session, asset.id))


@router.delete("/{asset_id}", response_model=OkOut, summary="删除资产")
def delete_asset(asset_id: int, user: CurrentUser, session: DbSession) -> OkOut:
    """删除。返回 `{"ok": true}`。

    【为什么删一个不存在的 id 是 404 而不是「成功」】幂等地返回
    `{"ok": true}` 看起来更友好，但它会把「我删错东西了」和
    「删成功了」变成同一件事。前端 `RemoteAssetRepository.delete`
    忽略响应体，所以 404 只会走到它自己的错误处理里 —— 那是对的：
    用户点了一件已经不存在的作品，界面该刷新一下。
    """
    assets.delete_asset(session, user, asset_id)
    return OkOut()
