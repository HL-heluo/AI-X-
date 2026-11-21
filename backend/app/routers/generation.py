"""生成 —— `POST /generation/image` / `POST /generation/video` / `GET /generation/cost`。

§7.1 计价、§7.2 三段式扣费、§7.5 四道闸。三条端点在同一个文件里，
是因为它们共用同一套计价规则（`services/generation.py`）——
分开写会让「问价报 32、下单冻 40」这种不一致变得可能。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.enums import TaskKind
from app.schemas import CostOut, ImageGenIn, TaskOut, VideoGenIn
from app.services import generation

router = APIRouter(prefix="/generation", tags=["生成"])

DEFAULT_VIDEO_DURATION_SEC = 5


@router.post(
    "/image",
    response_model=TaskOut,
    summary="文生图（固定 4 积分）",
)
def generate_image(payload: ImageGenIn, user: CurrentUser, session: DbSession) -> TaskOut:
    """提交一次文生图。

    ─────────────────────────────────────────────────────────
    【字段名是 `aspect_ratio`，不是 `ratio` —— 刻意照抄，不要改整齐】

    §12.1 里图片接口用 `aspect_ratio`、视频接口用 `ratio`。
    文档自己不一致，但前端 `RemoteGenerationRepository.submitImage`
    发的就是 `aspect_ratio`。**契约的权威是冻结的前端**，所以这里照抄。
    归一化在**内部**做：存进 `tasks.params` 时统一成 `ratio`
    （`TaskParams` 只有 `ratio` 这一个字段，前后端都一样）。
    ─────────────────────────────────────────────────────────
    """
    return generation.submit(
        session,
        user,
        kind=TaskKind.text_to_image,
        prompt=payload.prompt,
        # 【为什么走 `image_params` 而不是直接塞 dict】因为前端
        # `TaskParams.toJson` 会**省略值为 null 的键**。不丢的话，
        # 响应的 `params` 里会多出一个 `"ratio": null`，形状就对不上了。
        params=generation.image_params(payload.aspect_ratio),
        source_asset_id=None,
        requested_duration_sec=0,
        idempotency_key=payload.idempotency_key,
    )


@router.post(
    "/video",
    response_model=TaskOut,
    summary="图生视频（按秒计费，多退少不补）",
)
def generate_video(payload: VideoGenIn, user: CurrentUser, session: DbSession) -> TaskOut:
    """提交一次图生视频。

    【为什么 kind 恒为 `image_to_video`，即使 `source_asset_id` 是 null】
    因为 Mock 就是这么做的（`_submitVideo` 写死 kind），而 v1 的创作页
    里视频模式**必然**带一张参考图。「没给参考图」不是「文生视频」，
    是一个错误请求 —— 由 service 抛 400。若将来真开文生视频入口，
    那一刻要新增的是**契约**（前端得能表达「我要文生视频」），
    不是在这里加一个 `if`。
    """
    return generation.submit(
        session,
        user,
        kind=TaskKind.image_to_video,
        prompt=payload.prompt,
        params=generation.video_params(payload.ratio, payload.duration),
        source_asset_id=payload.source_asset_id,
        requested_duration_sec=payload.duration,
        idempotency_key=payload.idempotency_key,
    )


@router.get(
    "/cost",
    response_model=CostOut,
    summary="下单前问价 → {min, max, freeze}",
)
def estimate_cost(
    kind: str = Query(..., description="TaskKind 的 wire 值"),
    duration: int = Query(DEFAULT_VIDEO_DURATION_SEC, ge=1, description="请求时长（秒）"),
    ratio: str | None = Query(
        None,
        description="画面比例。**v1 不影响价格** —— 见下方说明。",
    ),
) -> CostOut:
    """问价。

    ─────────────────────────────────────────────────────────
    【`ratio` 为什么收下了却不用】

    因为 v1 只有 720P 一档，而 §7.1 的定价是按**分辨率**分档的
    （720P 4 积分/秒、1080P 9 积分/秒），**不是按比例**。
    16:9 和 9:16 都是 720×1280 那个量级的像素数，价格相同。

    那为什么还要收这个参数？因为前端 `RemoteGenerationRepository`
    会发它（`{kind, duration, ratio}`），而**多一个未知的查询参数
    不该让请求失败**。收下、忽略、并在这里写清楚为什么忽略 ——
    比回到前端去删掉它要好：那是改契约，而契约是冻结的。

    【两处数字都是契约值】
    图片恒为 4（`credits_per_image`）；视频按
    `(输入时长 0 + 请求时长 + 3 秒余量) × 4`。前端
    `TaskCostEstimate.isFixed` 靠 `min == max` 把文案从
    「4~4 积分」改成「本次冻结 4 积分」—— 所以图片那三个数字
    **必须相等**，改动任何一个都要同时改前端。
    ─────────────────────────────────────────────────────────
    """
    return generation.estimate_cost(generation.parse_kind(kind), duration)
