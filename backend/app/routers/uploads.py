"""上传 —— `POST /uploads/image`。§9.4 / §12.1。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.deps import CurrentUser, DbSession
from app.schemas import UploadOut
from app.services import assets

# 【为什么 multipart 的字段名必须叫 `file`，而不是 `image` / `upload`】
#
# 因为这个字符串是**前端写死的**：`DioApiClient` 走 multipart 时用的字段名
# 就是 `'file'`。名字对不上的表现是 FastAPI 返回 400「field required」，
# 而前端看到的是一个「上传失败」但说不出为什么的错误 ——
# 排查时得同时读两端的代码才能发现是这一处。
#
# 所以这里把它写成一个具名常量、而不是让 `File()` 用参数名兜底：
# `file: Annotated[UploadFile, File()]` 恰好也会得出 `file`（FastAPI 用
# 参数名当字段名），但那是**巧合**——哪天有人把参数改名成 `image`，
# 契约会静默地跟着变。写死它，改名时至少会经过这一行。
_FILE_FIELD = "file"

router = APIRouter(prefix="/uploads", tags=["上传"])


@router.post(
    "/image",
    response_model=UploadOut,
    summary="上传参考图 → {asset_id, public_url}",
)
async def upload_image(
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(alias=_FILE_FIELD)],
) -> UploadOut:
    """收一张参考图，存成 `assets` 里的一行。

    ─────────────────────────────────────────────────────────
    【为什么这一条是 `async def`，而其它端点都是 `def`】

    因为读 `UploadFile` 必须 `await`（大文件被 Starlette 缓冲在临时文件里，
    读它是真正的 IO）。其余端点只碰同步的 SQLAlchemy 会话，写成 `def`
    让 FastAPI 丢进线程池就行。

    ⚠️ 由此带来一个必须知道的事实：同步依赖（`get_db` / `get_current_user`）
    在线程池里跑，而这一条在事件循环线程里跑，所以**这个会话是跨线程用的**。
    这不是疏漏 —— `database.build_engine` 对 SQLite 设了
    `check_same_thread=False` 正是为了它，并且使用是严格串行的
    （依赖跑完了才轮到端点），不存在并发访问。
    ─────────────────────────────────────────────────────────
    """
    return await assets.store_reference_image(session, user, file)
