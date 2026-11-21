"""资产：列表、删除、参考图上传 —— §9.4 / §12.1。

【和 `generation.py` 的分工】那个文件管「产物是怎么被造出来的」，
这个文件管「产物和用户上传物怎么被列出、删除、存进来」。
两边都写 `assets` 表，但**不共用一个 ORM 构造器** ——
它们的字段来源完全不同（一个是 provider 给的时长/宽高，
一个是 multipart 里量出来的字节数），硬凑成一个函数会让
「这个字段到底从哪来」变得看不出来。
"""

from __future__ import annotations

import logging

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AssetKind, ErrorCode
from app.errors import AppError
from app.models import Asset, EvidenceRecord, User, WorkHolding, WorkListing
from app.schemas import UploadOut
from app.services import storage
from app.services.storage import build_storage
from app.services.transcode import ImageProbeStatus, probe_image
from app.services.transfer import staging_dir
from app.services.unit import atomic

logger = logging.getLogger(__name__)

_UPLOAD_CHUNK = 1024 * 1024
"""上传时的读取块大小（1MB）。

【为什么是分块读，而不是 `await file.read()` 一把梭】

`UploadFile.read()` 不传参时会把**整个文件**读进内存。前端的上限是
20MB，看起来还好 —— 但那个上限是**我们**在拒绝之前用来判断的数字：
一把梭的话，一个 2GB 的请求会先把 2GB 塞进内存，然后我们才发现它超了。
(内存先炸，校验再执行 —— 顺序反了。)

分块读让「超限」在读到第 21 个块时就确定，占用恒为 21MB 左右。
注意这只是**应用层**的防线：真正的第一道闸是反代的
`client_max_body_size`（部署那批配）。
"""


async def store_reference_image(
    session: Session, user: User, upload: UploadFile
) -> UploadOut:
    """`POST /uploads/image` —— 存用户上传的参考图。§12.1 / §9.4。

    ─────────────────────────────────────────────────────────
    【为什么这个 service 函数是 `async` 的，别的都不是】

    因为它的输入是一个 `UploadFile`，读它必须 `await`（Starlette 把
    大文件缓冲在临时文件里，读是真正的 IO）。其余 service 全是同步的
    —— 它们只碰数据库会话，而 SQLAlchemy 的同步 Session 在 FastAPI 的
    同步依赖里跑得好好的。

    【为什么不改成「路由里读完再传给一个同步函数」】
    那样要么把整份字节在内存里递一手（等于放弃分块），要么把
    `media_root` 的写入逻辑挪进路由 —— 而「字节落哪、失败怎么回滚」
    是业务，不该长在路由里。

    【B4 起它真的落盘了】字节会写进 `storage`（`STORAGE=local` 时就是
    `media_root`），于是 `public_url` 第一次真的能被打开。
    落盘前会探一次尺寸 —— 但那**不改变「解不出也收」的口径**，
    见下面 `probe_image` 那一段。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    limit = settings.max_image_bytes
    store = build_storage()

    # 【为什么这次读到**临时文件**而不是一个 list】B2 时量完就把字节丢掉
    # 了（那时不需要留），B4 要留下它们。留在 list 里意味着 20MB 常驻内存，
    # 而并发上传时这份内存会相乘。
    #
    # ⚠️ 暂存目录建在 spool 根下，**不在 media_root 里** ——
    # `media_root` 是被 `StaticFiles` 发布出去的，把半个文件放在那里面，
    # 就意味着一个 `/media/<key>` 请求可能读到它。
    with staging_dir() as work:
        staged = work / "upload"
        total = 0
        # 先量再决定要不要留下 —— 见 `_UPLOAD_CHUNK` 的说明。
        with staged.open("wb") as fh:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    # 【为什么这条在**任何解码之前**】「21MB 的垃圾字节 →
                    # IMAGE_TOO_LARGE」是 B2 就有的断言，而它必须继续
                    # 由大小决定 —— 不该因为「它同时也不是一张图」
                    # 而变成另一个错误。
                    raise AppError(
                        ErrorCode.IMAGE_TOO_LARGE,
                        f"参考图超过 {limit} 字节上限（已读到 {total}）",
                    )
                fh.write(chunk)

        info = probe_image(staged)
        if info.status is ImageProbeStatus.too_large:
            # 【这一条是「宽松口径」里唯一硬的地方】能**读出**声明的边长，
            # 就按边长管。放它进来的话，「解不出也收」就变成了一句空话 ——
            # 一张 6 万×6 万声明的 PNG 完全可以在 20MB 以内。
            raise AppError(
                ErrorCode.IMAGE_TOO_LARGE,
                f"参考图边长超过 {settings.max_upload_side}（实际 {info.width}×{info.height}）",
            )

        # 【为什么 `mime` 允许为空字符串时退回 image/png】和 Mock 逐字一致
        # （`mimeType ?? 'image/png'`）。`UploadFile.content_type` 在客户端
        # 没带 header 时是 `None`，也可能是个空串 —— 两种都要兜住，
        # 否则库里会出现一列空字符串，前端按 mime 分支时会认不出。
        #
        # 【为什么中间夹了一层「探出来的 mime」】两边都不给的时候
        # （客户端没带 header、且我们真的读出了格式），从字节里读出来的
        # 那个比一个写死的 image/png 准 —— 一张真的 JPEG 不该被记成 PNG。
        mime = (upload.content_type or "").strip() or info.mime or "image/png"
        # 文件名也要兜：`UploadFile.filename` 同样是可选字段。
        filename = upload.filename or "upload"

        with atomic(session):
            asset = Asset(
                user_id=user.id,
                # 【为什么 `task_id` 恒为 None】用户上传的参考图不属于任何
                # 生成任务 —— 它是任务的**输入**，不是产物（§11.2）。
                # 填成某个任务 id 会让「删任务」把用户的原始素材一并带走。
                task_id=None,
                kind=AssetKind.image,
                # 先占位，flush 拿到 id 之后再换成真路径：路径里带 asset_id
                # （`u/{user}/{asset}/{name}`），而 id 要 INSERT 之后才有。
                # 这比「先算路径用随机数」好 —— 前者让存储层与数据库同构。
                storage_key="",
                public_url="",
                mime=mime,
                size_bytes=total,
                duration_sec=None,
                # 【宽高为什么可能还是 None】探得出就记下来（B4 起），
                # 探不出仍然是 None —— 那是**用户拍板的口径**：
                # 解不出的文件照收，只是宽高空着。
                width=info.width,
                height=info.height,
                # ⚠️ §11.2 + §10.1：用户上传的原图**不是** AI 生成的。
                # 这就是这一列不能写死成 true 的原因（见 models.py 的注释）。
                is_ai_generated=False,
            )
            session.add(asset)
            session.flush()

            key = storage.reference_image_key(user.id, asset.id, filename)
            # 【为什么写对象在事务里】与产物那条路同理（见 HANDLER/GAP：
            # 「转存 IO 在 DB 写事务内」）。这里是一次本地复制、上限 20MB，
            # 而它换来的是「行与文件同时存在或同时不存在」这个性质 ——
            # 交换的代价是写锁多持有一个复制的时长。
            store.put_file(key, staged, content_type=mime)
            asset.storage_key = key
            asset.public_url = store.url_for(key)
            session.flush()

            return UploadOut(asset_id=asset.id, public_url=asset.public_url)


def get_asset(session: Session, user: User, asset_id: int) -> Asset:
    """按 id 取资产。**别人的资产 = 不存在**（404，不是 403）。

    【为什么 404 而不是 403】和 `requirements` 之外的一切资源接口一致：
    403 会告诉调用方「这个 id 存在，只是不属于你」——
    那是一个可以拿来枚举 id 的探针。
    """
    asset = session.get(Asset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise AppError(ErrorCode.NOT_FOUND, f"资产 {asset_id} 不存在或不属于当前用户")
    return asset


def lock_asset(session: Session, asset_id: int) -> Asset:
    """Serialize publication, deletion, and marketplace writes for one asset."""
    if session.get_bind().dialect.name == "sqlite":
        # SQLite has no SELECT FOR UPDATE; acquire its writer lock before reading.
        session.execute(update(Asset).where(Asset.id == asset_id).values(id=Asset.id))
    asset = session.scalar(
        select(Asset).where(Asset.id == asset_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
    return asset


def delete_asset(session: Session, user: User, asset_id: int) -> None:
    """`DELETE /assets/{id}`。

    存证记录的资产引用由数据库置空，保留链上登记和审计回执。

    ─────────────────────────────────────────────────────────
    【B4：把存储上的对象也删掉，而且**先 commit 再删文件**】

    顺序反过来（先删文件、再 commit）的话，一次提交失败就会留下
    「行还在、文件没了」—— 用户点开自己的作品是一张裂图，
    而列表里它明明还在。

    删文件失败**不回滚也不报错**（只记日志）：用户点了删除，
    他要的结果是「它从我的列表里消失了」。为了一个删不掉的孤儿文件
    把这次删除变成一次失败，是把我们自己的清理问题转嫁给用户。

    ⚠️ 与 Mock 逐字一致：**只删这一行，不级联删任务的封面**
    （`fake_api_client.dart:208-228`）。所以删掉一个视频资产会留下
    它自己的缩略图行 —— 那是前端也有的行为，不是漏了。
    ─────────────────────────────────────────────────────────
    """
    with atomic(session):
        asset = lock_asset(session, asset_id)
        if asset.user_id != user.id:
            raise AppError(ErrorCode.NOT_FOUND, "没有此作品")
        evidence_id = session.scalar(select(EvidenceRecord.id).where(EvidenceRecord.asset_id == asset.id))
        if evidence_id is not None:
            holding = session.get(WorkHolding, evidence_id)
            listed = session.scalar(select(WorkListing.id).where(
                WorkListing.evidence_record_id == evidence_id, WorkListing.status == "active",
            ))
            if listed is not None or (holding is not None and holding.holder_id != user.id):
                raise AppError(ErrorCode.INVALID_REQUEST, "请先撤销挂单，只有当前持有人和作者为同一账号时可以删除作品")
        key = asset.storage_key
        session.delete(asset)

    if not key:
        # 理论上不会有（上传与产物都一定会填 key），但 B2 的老数据里
        # 可能有空串。一个空 key 传进 `_safe_path` 会解析成 media_root
        # 本身 —— 而删掉整个 media 目录不是我们想要的任何结果。
        return
    try:
        build_storage().delete(key)
    except Exception:  # noqa: BLE001 —— 见上面那段说明
        logger.warning("资产 %s 的行已删除，但对象 %s 没删掉", asset_id, key, exc_info=True)


def list_assets(
    session: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    task_id: int | None = None,
    certified_only: bool = False,
) -> tuple[list[Asset], int]:
    """`GET /assets` —— 真分页，可按 `task_id` 过滤。

    ─────────────────────────────────────────────────────────
    【排序：最新的在前，`id DESC` 兜底】

    Mock 的注释说它**不排序**（就是插入顺序）。但插入顺序在 SQL 里
    不是一个有保证的东西 —— PostgreSQL 上没有 `ORDER BY` 的行序
    取决于物理布局，一次 vacuum 就可能变。用户在作品页看到顺序
    无故跳变，会以为丢了东西。

    所以这里显式排一个「新→旧」，它和前端作品页的预期一致
    （第一屏是最新作品）。这是本批**有意比 Mock 更严格**的两处之一
    （另一处是 `/tasks` 的排序）。

    【`total` 与 `items` 必须用同一套 where 条件】分页最常见的 bug 是
    total 忘了带过滤条件，于是「共 100 条」而只有 3 条能翻到。
    这里把 where 收进一个元组，两处共用一个来源。
    ─────────────────────────────────────────────────────────
    """
    conditions = [Asset.user_id == user.id]
    if task_id is not None:
        conditions.append(Asset.task_id == task_id)
    if certified_only:
        conditions.extend((
            Asset.kind == AssetKind.video,
            select(EvidenceRecord.id).where(
                EvidenceRecord.asset_id == Asset.id, EvidenceRecord.status == "committed"
            ).exists(),
        ))

    total = session.scalar(select(func.count()).select_from(Asset).where(*conditions)) or 0
    rows = session.scalars(
        select(Asset)
        .where(*conditions)
        .order_by(Asset.created_at.desc(), Asset.id.desc())
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total
