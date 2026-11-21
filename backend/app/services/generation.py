"""生成：问价、提交、任务状态机、任务查询、取消 —— §7.2 / §7.5 / §8。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件里最要紧的一条纪律：校验走在任何写之前】

`POST /generation/*` 里的检查顺序**不是**随手排的，它是从前端那条
断言反推出来的（`repository_layer_test.dart` 的「积分不足」用例）：
一次被拒的提交必须让 `balance` / `frozen` / 任务数 / 流水
**一个都不动**。

所以「先冻结再校验余额」这种写法是禁止的 —— 钱已经被扣了，
再发现不够，回滚虽然能救回来，但只要将来有人把 `atomic()`
挪个位置，它就会变成一笔真实的误扣。校验一律前置。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【B3：状态机从「一步走完」变成「两个入口共用一套收尾」

B2 里 `submit()` 自己把任务推到 `succeeded`。B3 之后有**两个**地方
会把任务推到终态：

  · **请求路径**（这个文件的 `submit`）—— 只处理 provider 当场
    就给出结果的情况（`result.done`，也就是 fake）；
  · **worker**（`app/worker.py`）—— 处理排队出队、以及「提交了
    但还没回来」的那些。

两条路走到最后是**同一段代码**（`finish_succeeded` / `fail_task` /
`reject_task` / `expire_task`）。这是 §8.3「worker 的职责 ⑥写回状态」
和请求路径之间唯一正确的分工方式：一旦两边各写一份收尾逻辑，
它们就会在「先退冻结还是先扣余额」「失败任务要不要落资产」这类
细节上分岔，而对账时看得出来的只有余额对不上。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    AssetKind,
    ErrorCode,
    TaskErrorCode,
    TaskKind,
    TaskStatus,
    TransferState,
)
from app.errors import AppError
from app.models import Asset, Task, User
from app.providers import (
    GenerationProvider,
    GenerationRequest,
    ProviderFailure,
    ProviderResult,
    build_provider,
)
from app.schemas import CostOut, TaskListOut, TaskOut
from app.services import credits, evidence, moderation, queue, storage
from app.services.provider_audit import (
    CallAudit,
    PendingCall,
    call_from_failure,
    call_from_result,
)
from app.services.transfer import ArtifactSpec, TransferFailure, transfer_artifact
from app.services.unit import atomic
from app.types import utcnow

logger = logging.getLogger("aivideo")

STATUS_FILTER_ACTIVE = "active"
STATUS_FILTER_DONE = "done"
"""/tasks?status= 的两个取值。定义在 `lib/core/constants/api_paths.dart`
（`statusActive` / `statusDone`）—— 逐字一致，别改整齐。"""


# ══════════════════════════════════════════════════════════════
# 问价
# ══════════════════════════════════════════════════════════════


def parse_kind(raw: str) -> TaskKind:
    """把 wire 值解析成 `TaskKind`，认不出就是 400 而不是 500。

    【为什么要包一层】直接 `TaskKind(raw)` 抛的是 `ValueError`，
    它会一路冒成 500 —— 而「客户端传了一个不存在的 kind」是
    **调用方的错**，该是 400。
    """
    try:
        return TaskKind(raw)
    except ValueError as exc:
        allowed = ", ".join(k.value for k in TaskKind)
        raise AppError(ErrorCode.INVALID_REQUEST, f"未知的 kind {raw!r}（可用：{allowed}）") from exc


def estimate_cost(kind: TaskKind, duration_sec: int) -> CostOut:
    """`GET /generation/cost`。§7.2。

    【图片为什么 min == max == freeze == 4】文生图成本固定，冻结额等于
    结算额。前端 `TaskCostEstimate.isFixed` 会据此把文案从
    「4~4 积分」改成「本次冻结 4 积分」。

    【视频为什么 min 和 max 不一样】因为**成片时长由 provider 侧的
    Agent 决定**，下单那一刻连后端都不知道最终会扣多少（§7.2）。
    给一个确定数字就是在撒谎 —— §13.4 明令禁止在按钮下写确定数字。
    """
    settings = get_settings()
    if kind is TaskKind.text_to_image:
        fixed = settings.credits_per_image
        return CostOut(min=fixed, max=fixed, freeze=fixed)

    request = GenerationRequest(
        kind=kind, prompt="", requested_duration_sec=duration_sec
    )
    # 【为什么这里必须传 `kind`】同一个 `freeze_amount` 在不同 provider
    # 上可能不是一个价（本批的部署形态就是图片走 fake、视频走 MiniMax）。
    # 不传的话，这个接口报出来的预估冻结额来自**图片那条路**，
    # 而用户实际冻的是视频那条路 —— 界面上「本次冻结 N 积分」会是个
    # 与实际不符的数字（§13.4：不许在按钮下写确定数字，就是为这个）。
    freeze = build_provider(kind).freeze_amount(request)
    minimum = settings.credits_per_sec_720 * duration_sec
    return CostOut(min=minimum, max=freeze, freeze=freeze)


# ══════════════════════════════════════════════════════════════
# 排队位次
# ══════════════════════════════════════════════════════════════
#
# 【为什么它搬去了 `services/queue.py`】因为位次和出队顺序**必须用
# 同一个排序键**，否则「前面还有 3 个」就是一句谎话。B2 时它俩分别
# 在 `generation.py`（位次）和「不存在的 worker」里，看不出这层关系；
# B3 有了真正的出队之后，把两个函数放在同一个文件里，
# 「改了一个别忘了另一个」才有一点点可能被人注意到。
#
# 所以这里**没有**一个叫 `queue_position_of` 的转发函数 —— 转发会让
# 「位次在哪定义」这件事又变得模糊（读到这里的人会以为它在这儿）。
# 调用点直接写 `queue.position_of`，文件出处一眼可见。


# ══════════════════════════════════════════════════════════════
# 提交
# ══════════════════════════════════════════════════════════════


def _clean_params(**values: Any) -> dict[str, Any]:
    """丢掉值为 None 的键。

    【为什么要丢】因为前端 `TaskParams.toJson` 就是这么干的
    （`{if (ratio != null) 'ratio': ratio, ...}`），而契约要求我们
    返回到 `params` 对象里的东西和它逐字对齐。留着 `"ratio": null`
    不会解析失败，但形状就对不上了。
    """
    return {key: value for key, value in values.items() if value is not None}


def image_params(aspect_ratio: str | None) -> dict[str, Any]:
    """`POST /generation/image` 的入参 → `tasks.params`。

    ─────────────────────────────────────────────────────────
    【为什么这层翻译在 service 里，而不是在路由里】

    因为「对外叫 `aspect_ratio`、对内叫 `ratio`」是一条**契约事实**，
    不是一个参数搬运。放在路由里的话，将来第二个调用方
    （导入接口、后台补单脚本）会各写一遍，而写漏的那一处会让
    `params` 里出现一个前端读不到的键 —— 表现是「比例选了但详情页
    显示不出来」，排查时很难想到是路由的锅。
    ─────────────────────────────────────────────────────────
    """
    return _clean_params(ratio=aspect_ratio)


def video_params(ratio: str | None, duration: int) -> dict[str, Any]:
    """`POST /generation/video` 的入参 → `tasks.params`。

    【为什么 `duration` 也要存一份】任务详情页要显示「这条我选的是 5 秒」，
    而它读的是 `params.duration`（`TaskParams` 里只有这一个时长字段）。
    `tasks.requested_duration_sec` 那一列也记着同一个数，那是给
    对账用的 —— 两个都写不冲突，且前端只认前者。
    """
    return _clean_params(ratio=ratio, duration=duration)


def _check_quota(session: Session, user_id: int, kind: TaskKind) -> None:
    """§7.5 的第 3 道闸。

    ─────────────────────────────────────────────────────────
    【两道限制，都是真抛 RATE_LIMITED，不是摆设】

    它们的存在价值在于**让 UI 里那些分支真的被执行过**
    （「已达今日生成上限」那句话在真机上长什么样，只有抛过才知道）。
    所以即使走 `fake` provider 一切瞬间完成，这两条也必须真做。

    · **每日上限 20**：按 `created_at` 落在今天（UTC）的任务数算，
      **不分状态** —— 一个失败了 20 次的用户今天不该还能再试。
    · **同类同时 ≤ 1**：§8.2 强调「图与视频分开计数」，混在一起的话
      图片会被视频饿死（用户排了个十分钟的视频，连张图都生成不了）。

    ⚠️ 走 fake provider 时，任务在提交那一刻就已经是终态，
      所以「同类同时」永远是 0 —— 这条闸对假冒 provider **测不出效果**。
      要看它生效，得用一个不会当场完成的 provider
      （`tests/test_queue_b3.py` 里那个 `SlowProvider`）。
      这是有意的取舍，不是漏了。

    【它和 `queue.has_free_slot` 是两道不同的闸，别当成一道】
    这一道是**每用户**的（§7.5 闸 3，成本自保：别让一个人把额度堆满）；
    那一刀是**全局按类**的（§8.2 的闸门值，物理约束：即梦的并发
    是平台共享的）。数值都来自配置，但来自**两个不同的配置项** ——
    理由见 `config.py` 的 `provider_max_concurrency`。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today_count = session.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.user_id == user_id,
            Task.created_at >= day_start,
            Task.created_at < day_start + timedelta(days=1),
        )
    )
    if (today_count or 0) >= settings.daily_task_limit:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            f"已达每日上限 {settings.daily_task_limit} 个（今天已建 {today_count} 个）",
        )

    active_of_kind = session.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.user_id == user_id,
            Task.kind == kind,
            Task.status.in_(ACTIVE_STATUSES),
        )
    )
    if (active_of_kind or 0) >= settings.max_concurrent_tasks:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            f"同时进行的 {kind.value} 任务不能超过 {settings.max_concurrent_tasks} 个",
        )


def _resolve_source_asset(session: Session, user: User, asset_id: int | None) -> Asset:
    """图生视频的参考图必须是**本用户真实上传过的**资产。

    【为什么 Mock 做不到这条】Mock 没有「别人的资产」这个概念。
    真后端有，所以必须查 —— 否则用户可以拿一个随便编的数字下单，
    而那笔任务事后追溯不到任何输入图（`tasks.source_asset_id` 没有外键，
    见 `models.py` 里那段说明）。

    【为什么是 404 而不是 400】因为语义是「你要的那个东西不存在」，
    和「你给的东西形状不对」是两回事。

    【B6：为什么返回整行 `Asset` 而不是 `asset.id`】因为即梦要的是
    一个**它下得动**的地址（`GenerationRequest.source_url`），而那个
    地址在 `assets.public_url` 上。返回 id 的话，调用方拿不到它，
    只能**再查一次**——两次查询之间那张图可能被删掉，
    于是「校验通过但地址为空」。一次查出整行，就没有那个窗口。
    """
    if asset_id is None:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "图生视频必须提供 source_asset_id",
        )
    asset = session.get(Asset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise AppError(ErrorCode.NOT_FOUND, f"参考图 {asset_id} 不存在或不属于当前用户")
    return asset


def source_url_for(session: Session, task: Task) -> str | None:
    """`task.source_asset_id` → 参考图的**公网地址**（B6）。

    ─────────────────────────────────────────────────────────
    【为什么需要它】worker 在另一时刻干活，手里只有 `Task` 那一行，
    而 `Task` 上只有 `source_asset_id`（我们库里的编号）。
    即梦在**它的机房里**下载参考图，所以它只认 URL ——
    拿一个整数过去，它无从解析。

    【为什么用 `assets.public_url` 而不是现拼一个】
    因为那一列就是**用户此刻看到的地址**（作品列表、详情页都读它）。
    现拼一个出来的话，两个地址会在「换 CDN」「改 PUBLIC_BASE_URL」
    这类操作之后开始不一样 —— 而那时用户看到的图与 provider
    下载的图就不是同一张了，且两边各自的测试都还是绿的。

    【为什么查不到就返回 `None`，而不是抛】参考图被删掉是一条
    正常路径（用户删作品）。这时 `jimeng.submit` 会不带 `image_urls`
    把任务交出去 —— 即梦会回一个 4xx，那是一次**响亮且不花钱**的失败，
    用户拿到退款和一个「生成失败」。比在这里抛一个 500、
    让 worker 那一轮整个停摆要好。
    ─────────────────────────────────────────────────────────
    """
    if task.source_asset_id is None:
        return None
    asset = session.get(Asset, task.source_asset_id)
    return asset.public_url if asset is not None else None


def submit(
    session: Session,
    user: User,
    *,
    kind: TaskKind,
    prompt: str,
    params: dict[str, Any],
    source_asset_id: int | None,
    requested_duration_sec: int,
    idempotency_key: str,
) -> TaskOut:
    """提交一次生成 —— `POST /generation/image|video` 的共同实现。

    ─────────────────────────────────────────────────────────
    【检查顺序（照抄 Mock 的 `_submit`，一步都不许挪）】

      1. 提示词（空 / 超长 → `INVALID_PROMPT`）
      2. 参考图（图生视频必须有，且属于本用户）
      3. **幂等键去重**（→ 409 + 已有 task）
      4. 配额（→ `RATE_LIMITED`）
      5. 余额（→ `INSUFFICIENT_CREDITS`）
      6. 建任务 → 冻结 → 写流水
      7. 看闸门：有空位就直接提交，没有就排队

    第 3 条为什么必须在第 6 条**之前**：它的作用就是防连点双扣。
    用户双击生成按钮 → 两个请求带同一个 key 到达 → 如果先冻结再查重，
    钱已经被扣两次了，再发现重复也没用。

    第 5 条同理：它是「先冻结后提交」这道闸的判据，而判据必须
    在扣钱之前算出来。

    【第 7 步在 B3 为什么变成「看闸门」】
    §8.1 说得很直白：即梦的并发是**平台共享**的，所以「有没有空位」
    这件事不能只看自己 —— 闸门满了就得排队，而不是照样把请求打过去、
    然后拿一串限流错误回来。§8.3 的 worker 职责 ①「看闸门空位」
    说的就是这一步；请求路径做的是同一件事，只是它顺手替自己
    把任务推了一步（provider 当场给结果时）。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    # 【`kind` 是形参，本来就在作用域里】传它下去，这条任务才会落到
    # 它那一档 provider 上（图片一档、视频一档，见 `providers.__init__`）。
    # 不传的话，`PROVIDER=fake` + `VIDEO_PROVIDER=minimax` 的部署里
    # 视频请求路径会拿着 fake provider 去提交，而 worker 那一侧
    # 却用 minimax —— 同一条任务在两处走两条路。
    provider = build_provider(kind)
    text = (prompt or "").strip()

    # ── 对账记录（§11.1）──────────────────────────────────
    # 【为什么在这儿建、在 finally 里冲】
    #
    # `atomic()` 里那把事务**持着 SQLite 唯一的写锁**去打 provider 的
    # HTTP。此时任何第二条连接想写 `provider_calls`，都会在 busy_timeout
    # 上等一把**自己持有的**锁 —— 死锁。所以审计只能等事务落定之后再冲。
    #
    # 而它又**必须**拥有自己的连接：被拒的提交会让任务行、冻结、流水
    # 一起回滚，同事务插的审计行会跟着消失 —— 于是对账表里永远没有
    # 「我们打了接口、对方拒了、我们没记账」的那些调用，
    # 而它们恰恰是对账要抓的东西。
    audit = CallAudit()
    # 【为什么用一个变量接住 id，而不是在 finally 里读 `task.id`】
    # 事务回滚之后 `task` 已经不在库里了，可 `task.id` 仍然有值 ——
    # 拿它去写 `provider_calls` 会留下一条指向空气的外键
    # （SQLite 默认不报错，于是对账表里多一条谁都解释不了的记录）。
    # 这个变量**只在提交成功之后**才被赋值，回滚路径上它保持 None。
    audit_task_id: int | None = None

    try:
        with atomic(session):
            # ── 1. 提示词 ────────────────────────────────────
            # 【为什么长度上限从配置读】它是 §11.2 的业务规则（2000 字），
            # 不是存储能力 —— 所以 `tasks.prompt` 是 Text 而不是 String(2000)。
            if not text or len(prompt) > settings.max_prompt_len:
                raise AppError(
                    ErrorCode.INVALID_PROMPT,
                    f"提示词为空或超过 {settings.max_prompt_len} 字（实际 {len(prompt)}）",
                )

            # ── 1.5 入口审核（§10.2 第①层）───────────────────
            # 【为什么它在第 2 步之前，而不是更后面】
            #
            # ① 它**在任何写库动作之前** —— 于是「被拒的提交一个数字都不动」
            #    是**构造上**成立的，不需要额外的回滚去保证。
            # ② 它比后面每一步都便宜：一次归一化 + 几次子串匹配，
            #    不查库、不打网络。先做便宜的、能拒掉请求的检查。
            #
            # ⚠️ 顺序后果，有测试钉着：**零余额 + 命中词**的用户拿到的是
            #    `CONTENT_REJECTED`(422)，而不是 `INSUFFICIENT_CREDITS`。
            #    这对用户是好事 —— 他该知道的是「这句话不行」，
            #    因为去充钱也发不出来。但它确实与 §12.1 Mock 的检查顺序不同，
            #    所以不能靠「没人会同时踩到」蒙过去。
            #
            # ⚠️ 这一刀只是**第①层**。它挡不住同音字和变体字
            #    （关键词方案的固有上限），真正的兜底是即梦那边的第②层，
            #    见 `moderation` 的模块说明。
            moderation.screen_input(text)

            # ── 2. 参考图 ────────────────────────────────────
            resolved_asset = None
            if kind is TaskKind.image_to_video:
                resolved_asset = _resolve_source_asset(session, user, source_asset_id)
            resolved_asset_id = resolved_asset.id if resolved_asset else None

            # ── 3. 幂等去重 ──────────────────────────────────
            existing = session.scalar(
                select(Task).where(
                    Task.user_id == user.id,
                    Task.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                raise _duplicate_error(session, existing)

            # ── 4. 配额 ──────────────────────────────────────
            _check_quota(session, user.id, kind)

            # ── 5. 余额 ──────────────────────────────────────
            request = GenerationRequest(
                kind=kind,
                prompt=text,
                params=params,
                source_asset_id=resolved_asset_id,
                # 【B6】参考图的公网地址带上 —— 同步路径上 provider
                # 可能当场就把它交出去（fake 不会，但协议允许）。
                # 取的是用户此刻看得见的那个地址，见 `source_url_for`。
                source_url=resolved_asset.public_url if resolved_asset else None,
                requested_duration_sec=requested_duration_sec,
                input_duration_sec=0,
            )
            freeze = provider.freeze_amount(request)
            account = credits.account_of(session, user.id)
            if not credits.has_enough(account, freeze):
                raise AppError(
                    ErrorCode.INSUFFICIENT_CREDITS,
                    f"需要冻结 {freeze}，可用只有 {account.balance - account.frozen}",
                )

            # ── 6. 建任务 + 冻结 ─────────────────────────────
            now = utcnow()
            task = Task(
                user_id=user.id,
                kind=kind,
                status=TaskStatus.pending,
                provider=provider.name,
                prompt=text,
                params_json=json.dumps(params, ensure_ascii=False) if params else "{}",
                source_asset_id=resolved_asset_id,
                idempotency_key=idempotency_key,
                freeze_amount=freeze,
                input_duration_sec=0,
            )
            session.add(task)
            session.flush()  # 拿 id：流水要靠它关联
            credits.freeze(session, user.id, freeze, task_id=task.id, note="提交任务预扣")

            # ── 7. 出队闸门 ──────────────────────────────────
            if queue.has_free_slot(session, kind):
                # 有空位。`dispatch` 里可能把它推成 succeeded（fake 的
                # 提交即完成），也可能只推进到 submitted（真 provider），
                # 那之后就是 worker 的事了。
                #
                # ── 同步失败要升级成 HTTP 错误 ──────────────────
                # 【为什么这里要把 ProviderFailure 变成 AppError】
                # 因为这是**同步**路径：用户正拿着一个没返回的请求在等。
                # §12.3 给了 `PROVIDER_ERROR`(502，「可重试」) 和
                # `CONTENT_REJECTED`(422，「提示改写」) 两个码，说的就是
                # 这件事。抛出去之后 `atomic()` 会回滚 —— 任务、冻结、
                # 流水一个都不留，用户重试一次就好。
                #
                # ⚠️ 这与 worker 里的处置**故意不同**：那条路上任务已经
                #   存在、钱已经冻了，把它回滚掉等于把证据删掉，
                #   所以那里是「记在任务上 + 全额退回」。
                #   两条路的区别就是「有没有一个活着的请求要回」。
                #
                # `sync=True`（B4）：转存失败也走**同一条**升级路 ——
                # 立刻判失败 → 下面的 if 看见 failed → 抛 502 → 回滚。
                # 少了它的话，一次转存失败会以 200 + `status:"submitted"`
                # 返回，而 `TEST_MODE=1` 的实例（跨仓门禁用的就是它）
                # 不起 worker，那条任务会一直停在那里、钱冻着一小时。
                dispatch(
                    session,
                    task,
                    request=request,
                    provider=provider,
                    now=now,
                    sync=True,
                    audit=audit,
                )
                if task.status in (TaskStatus.failed, TaskStatus.rejected):
                    raise _sync_failure(task)
            else:
                # 闸门满了 → 排队。这里**不**给用户报错：§8.2 说的是
                # 「诚实显示排队位次」，不是「稍后再试」——
                # 后者会把一次正常的排队变成一次失败，用户会重试，
                # 而重试只会让队列更长。
                queue.enqueue(session, task, now)

            session.flush()
            out = TaskOut.from_task(task, queue_position=queue.position_of(session, task))
            created_task_id = task.id
        # ── 走到这一行 = 事务**已经提交** ─────────────────────
        # 【为什么赋值放在 `with` 外面】`atomic()` 是**退出时**才 commit 的，
        # 所以 `with` 的缩进体里那一行并不代表写成功了。放在这里，
        # 「提交失败」这条路径上 `audit_task_id` 就还是 None。
        audit_task_id = created_task_id
        return out
    except IntegrityError as exc:
        # 并发下的兜底。见 `_translate_integrity_error` 的说明。
        raise _translate_integrity_error(session, exc, user, idempotency_key) from exc
    finally:
        # 【为什么冲刷在 finally 里，而且拿它自己的连接】
        # 见本函数开头那段：审计行必须活过**回滚**（被拒的提交正是
        # 最该被记下来的那一次），又不能挤进业务事务（会死锁）。
        # 放在 finally 里，三条出口（成功 / AppError / IntegrityError）
        # 都会走到，不需要在每一条 return 前面各写一遍 ——
        # 那种写法在加第四条出口时一定会漏。
        audit.flush(task_id=audit_task_id)


def _sync_failure(task: Task) -> AppError:
    """把「同步提交阶段的硬失败」翻译成 §12.3 的 HTTP 错误。

    【为什么状态码要从**任务状态**反推，而不是从 provider 的原始码】
    因为 provider 的原始码（即梦的 `50411` 之类）是**它的**分类体系，
    平台的契约码是**我们的**。两者之间必须有一个明确的映射点，
    而这个映射点就是 `handle_failure` 里的那个 if（审核类 → `rejected`）。
    在这里二次翻译原始码，等于把同一件事判断两遍 —— 两遍迟早会不一致。

    【只有 `failed` / `rejected` 会走到这里】可重试的失败已经被
    `handle_failure` 退回队列了（任务状态是 `queued`，带着一个未来的
    `queued_at`），那次请求会以 200 返回一个排队中的任务 ——
    这比给用户一个 502 然后让他自己再点一次要好，而且它**真的**在重试。
    """
    if task.status is TaskStatus.rejected:
        return AppError(
            ErrorCode.CONTENT_REJECTED,
            f"provider 判定输入未通过审核（{task.error_code}）：{task.error_msg}",
        )
    return AppError(
        ErrorCode.PROVIDER_ERROR,
        f"provider 在提交阶段失败（{task.error_code}）：{task.error_msg}",
    )


def _duplicate_error(session: Session, existing: Task) -> AppError:
    """构造 `DUPLICATE_REQUEST`，**把已有任务一并带回去**。

    ─────────────────────────────────────────────────────────
    【为什么必须在 raise 之前把它 dump 成原生 dict】

    这个异常会穿过 `atomic()` 的 `session.rollback()`，而 rollback
    会**expire 会话里的所有 ORM 对象**。等到异常处理器去序列化
    `existing` 时，那些属性处于「已过期」状态，访问它们会触发一次
    懒加载 —— 而那时会话可能已经被关掉了（`get_db` 的 finally）。

    所以在这里、对象还活着的时候，用 `model_dump(mode="json")` 把它
    变成纯 dict（datetime 会变成 ISO 字符串，StrEnum 会变成 wire 值）。
    ─────────────────────────────────────────────────────────

    【为什么这个 409 是「故意的错误」】§12.3 写明了它的客户端行为是
    **静默复用已存在的任务**。响应里不带 task 的话，前端
    `RemoteGenerationRepository._submitOrReuse` 只能把错误原样抛出去
    （它明确拒绝「随便造一个空任务」）—— 用户就会看到「我点了一下生成，
    它报错了」，而其实任务已经在跑了。
    """
    return AppError(
        ErrorCode.DUPLICATE_REQUEST,
        f"幂等键重复，复用任务 {existing.id}",
        payload={
            "task": TaskOut.from_task(
                existing, queue_position=queue.position_of(session, existing)
            ).model_dump(mode="json")
        },
    )


def _translate_integrity_error(
    session: Session, exc: IntegrityError, user: User, idempotency_key: str
) -> AppError:
    """把数据库约束冲突翻译成业务错误，别让它变成 500。

    ─────────────────────────────────────────────────────────
    【它和上面第 3 步「查一次重」是什么关系：两层，不是重复】

    第 3 步是**友好的那一层**（99.9% 的重复点击在这一层就被拦下，
    连 INSERT 都不会发生）。这一层是**兜底的那一层**，靠的是
    数据库上那条 `(user_id, idempotency_key)` 唯一约束 ——
    两个请求**同时**过了第 3 步、又同时 INSERT 时，只有一个能成功。

    【为什么要接 `idempotency_key` 参数】因为兜底时得把**那一个**
    已存在的任务带回去。早先的写法是「取这个用户的任意一个带 key 的
    任务」，在只有一个任务的测试里看起来是对的，而在真正会走到
    这条路径的场景（并发提交、用户已经有好几个任务）里，
    它会把**别的任务**当成重复的那个返回给客户端 ——
    于是用户点生成，拿回来一个他上周做的视频。

    v1 是单 worker + SQLite，这条路径几乎撞不上（`busy_timeout=5000`
    + 前置检查已经盖住绝大多数情形）。留着是因为：

      · 迁到 PostgreSQL 多 worker 之后，`check-then-act` 之间的窗口
        就是真实存在的；
      · 而撞上时的默认表现是一个 **500 + 一坨 SQL 错误文本**，
        排查成本远高于在这里多写十行。
    ─────────────────────────────────────────────────────────
    """
    text = str(getattr(exc, "orig", exc))

    if "idempotency_key" in text:
        existing = session.scalar(
            select(Task).where(
                Task.user_id == user.id,
                Task.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return _duplicate_error(session, existing)
        # 唯一约束炸了却查不到那一行 —— 只可能是「另一个事务刚删了它」
        # 这类极端情形。给一个不带 task 的 409 也比 500 好。
        return AppError(ErrorCode.DUPLICATE_REQUEST, "幂等键冲突（并发提交）")

    if "ck_credit_accounts" in text:
        # `frozen <= balance` 或 `balance >= 0` 被撞 —— 也就是可用余额不够。
        return AppError(ErrorCode.INSUFFICIENT_CREDITS, "并发扣费导致可用余额不足")

    raise exc


# ══════════════════════════════════════════════════════════════
# 状态机 —— 请求路径与 worker **共用**的那一套
# ══════════════════════════════════════════════════════════════
#
# 【为什么这一段是全批最要紧的代码】§8.3 的 ⑥「写回状态」在 worker 里，
# 而 ③「submit」在请求路径里也有一份。两边各写一遍收尾逻辑的后果不是
# 代码重复，是**它们会分岔**：一边先退冻结再扣余额、另一边反过来，
# 或者一边给失败任务落了资产、另一边没落。分岔之后余额还是能对上
# （两边的总数一样），是流水里的 `balance_after` 快照对不上 ——
# 而那时候已经查不清是哪一条写坏的。
#
# 所以规则是：**任何改变任务终态的代码只写在这里**。


def request_from_task(task: Task, *, source_url: str | None = None) -> GenerationRequest:
    """从库里的一行还原出 `GenerationRequest`。

    ─────────────────────────────────────────────────────────
    【为什么必须有一个「还原」的函数】

    worker 是**另一个时刻**在干活：它捞起一条 `queued` 任务时，
    当初那个 `GenerationRequest` 对象早就随请求一起消失了。
    于是「从哪里把请求拼回来」这件事必须只有一个出处 ——
    否则请求路径和 worker 各拼一次，某个字段拼漏了
    （比如 `input_duration_sec`），重算出来的结算额就会和当初
    冻结时依据的那个数**不是同一个**，而两边各自的测试都是绿的。

    ⚠️ `requested_duration_sec` 只能从 `params_json["duration"]` 取 ——
      `tasks` 表里**没有**这一列（只有 `input_duration_sec` 与
      `output_duration_sec`，那两个是给对账用的实际值）。
      这就是 `video_params()` 为什么要把 `duration` 存进 params 的原因，
      也是「改 `video_params` 时要想到 worker」的原因。

    【B6：`source_url` 为什么是参数，而不是自己去查】
    因为查它要一个 `Session`，而**这个函数的调用点有三个**
    （worker 的三个相位），其中两个只是拿它去 `poll` 或结算，
    压根不碰 provider 的提交接口 —— 给那两个也加一次库查询，
    是拿「每次轮询多一条 SELECT」换一个它们用不上的字段。

    所以只有真的要提交的那一处（`_dispatch_ready`）自己去
    `source_url_for()` 把地址查出来传进来。签名上看得见这件事：
    **不传的调用方明确地说了「我不需要它」**。
    ─────────────────────────────────────────────────────────
    """
    params: dict[str, Any] = {}
    if task.params_json:
        try:
            loaded = json.loads(task.params_json)
        except ValueError:
            # 库里的脏数据不该让整个 worker 停摆 —— 日志里有，
            # 而这一条任务会因为时长算成 0 而少收钱。
            logger.warning("任务 %s 的 params_json 不是合法 JSON，按空参数处理", task.id)
            loaded = None
        if isinstance(loaded, dict):
            params = loaded

    return GenerationRequest(
        kind=task.kind,
        prompt=task.prompt,
        params=params,
        source_asset_id=task.source_asset_id,
        source_url=source_url,
        requested_duration_sec=int(params.get("duration") or 0),
        input_duration_sec=task.input_duration_sec or 0,
    )


def _record_call(
    audit: CallAudit | None,
    action: str,
    *,
    started: float,
    task: Task,
    result: ProviderResult | None = None,
    failure: ProviderFailure | None = None,
) -> None:
    """记一次 provider 调用（§11.1 的对账表）。**不抛异常。**

    【`result=None` 且 `failure=None` 是什么意思】「问了一次，它说还没好」
    —— `poll_once` 里最常见的那一种（一条视频会问几十次）。
    它**必须**被记下来，见 `poll_once` 里那段。所以这里不能
    「两个都没有就跳过」：那恰好会漏掉出现次数最多的一类调用。

    ─────────────────────────────────────────────────────────
    【为什么延迟在这里量，而不是让 provider 自己报】

    因为「provider 花了多久」和「我们为这次调用等了多久」是两个数 ——
    后者才是用户感受到的、也才是判断闸门该开多大的依据。
    在**调用点**用 `perf_counter` 夹住，量到的是后者。
    这也意味着它量的是**同一件事**，不管底下是 fake 还是即梦。

    【为什么用 `perf_counter` 而不是 `time.time`】
    后者会被系统对时（NTP 校时）跳一下，于是某一次调用会记下
    一个负数或几小时的延迟。对账表里出现一条 7200000ms 的记录，
    读的人会去查 provider 是不是挂了 —— 而它只是被校了个时。

    【`attempt` 从哪来】`tasks.retry_count + 1`。第一次是 1。
    于是「第几次才成功」这个问题在对账表里能直接查出来 ——
    而它正是判断「闸门是不是开太大」的关键：如果大多数调用都要
    试到第 3 次，那问题不在重试策略，在并发。
    ─────────────────────────────────────────────────────────
    """
    if audit is None:
        return
    latency_ms = int((time.perf_counter() - started) * 1000)
    attempt = (task.retry_count or 0) + 1
    if failure is not None:
        audit.record(
            call_from_failure(action, exc=failure, latency_ms=latency_ms, attempt=attempt)
        )
    elif result is not None:
        audit.record(call_from_result(action, result=result, latency_ms=latency_ms, attempt=attempt))
    else:
        # 「还没好」。它没有 provider 状态码可记（对方没给结果），
        # 但**延迟与次数**正是要量的东西。
        audit.record(PendingCall(action=action, latency_ms=latency_ms, attempt=attempt))


def dispatch(
    session: Session,
    task: Task,
    *,
    request: GenerationRequest,
    provider: GenerationProvider,
    now: datetime | None = None,
    sync: bool = False,
    audit: CallAudit | None = None,
    defer_io: bool = False,
) -> None:
    """把一条任务交给 provider（§8.3 职责 ③），并按结果推进状态。

    ─────────────────────────────────────────────────────────
    【它做了三件事，顺序不能换】

      ① 入队（如果还没入过）→ ② 标记 submitted → ③ 调 provider 并看结果

    ① 放在最前面，是因为**每一条任务都该有 `queued_at`**。
    fake 那条路径上，「入队」和「出队」之间没有真实间隔，但记录里
    仍然是一次完整的 `pending → queued → submitted → succeeded`。
    不写 `queued_at` 的话，「这个任务排了多久」这类问题在 fake 下
    永远是空的 —— 而那正是我们将来调队列参数时要看的东西。

    ② 放在 ③ 前面，是因为 §8.3 的状态机里 `submitted` 的定义就是
    「已经交给 provider 了」。先调后标记的话，provider 在调用过程中
    抛错时任务会停在 `pending`，而它其实**已经真的提交过了** ——
    这会让「重试」重复提交一次真活儿。

    【它不抛 `ProviderFailure`】失败会被记在任务上（见
    `handle_failure`），因为这时的任务是**已经存在、钱已经冻了**的
    东西：回滚掉它等于把证据删掉。同步路径要不要把这个失败升级成
    HTTP 502，是**调用方的选择** —— 见 `submit` 里那一段。

    [sync]（B4）这一条是不是**用户正在等着**的请求路径。
    它只影响一件事：转存失败时是「留在 submitted 等 worker 重试」
    还是「立刻判失败」。理由见 `finish_succeeded` 里的那段分岔说明 ——
    **`TEST_MODE=1` 的实例根本不启动 worker**，所以「等重试」
    在那种实例上等于「永远等」。

    [defer_io]（B6）转存的 IO 要不要挪到**事务外**。**只有 worker
    路径传 `True`** —— 请求路径必须把 IO 留在事务里（那正是「被拒的
    提交不留痕」的实现方式）。理由见 `_claim_transfer` 上面那段。
    ─────────────────────────────────────────────────────────
    """
    moment = now or utcnow()

    if task.queued_at is None:
        queue.enqueue(session, task, now=moment)
    queue.mark_submitted(session, task, provider_task_id=None, now=moment)

    # ⚠️ `perf_counter` 要**紧贴**调用，别把上面那两行库存操作夹进来 ——
    #    那量到的是「我们在自己库里花了多久」，会把这个数彻底污染掉。
    _started = time.perf_counter()
    try:
        result = provider.submit(request)
    except ProviderFailure as exc:
        _record_call(audit, "submit", started=_started, task=task, failure=exc)
        handle_failure(session, task, exc, now=moment)
        return
    _record_call(audit, "submit", started=_started, task=task, result=result)

    if result.provider_task_id is not None:
        task.provider_task_id = result.provider_task_id

    if not result.done:
        # 只是一张回执 —— 剩下的交给 `poll_once`（worker 每轮会来问）。
        # 【为什么这里要显式 return 而不是「反正不 done 就什么都不做」】
        # 因为下面那一行是 `finish_succeeded`：漏掉 return 的表现是
        # **把一张还没有产物的回执当成成品结算掉** —— 钱扣了、资产
        # 记录落了、而文件根本不存在。这是本文件里最贵的一个 bug。
        return

    finish_succeeded(
        session,
        task,
        request=request,
        result=result,
        provider=provider,
        now=moment,
        sync=sync,
        defer_io=defer_io,
    )


def poll_once(
    session: Session,
    task: Task,
    *,
    request: GenerationRequest,
    provider: GenerationProvider,
    now: datetime | None = None,
    audit: CallAudit | None = None,
    defer_io: bool = False,
) -> bool:
    """对一条 `submitted` 任务问一次进度（§8.3 职责 ④）。返回是否推进了。

    【`None` 是「还没好」，不是「失败了」】这个区别是整个轮询循环
    能成立的前提：把「还没好」当成失败，用户的视频会在生成到一半时
    被判定失败并退款，然后 provider 那边还在跑、还会出片。
    """
    moment = now or utcnow()

    if not task.provider_task_id:
        # 提交时说了「没做完」却没给句柄 —— provider 违约，或者进程在
        # 「写了 submitted」和「存下 provider_task_id」之间挂了。
        #
        # 【为什么不留给超时兜底】超时是 1 小时。它已经不可能自己好了，
        # 让用户的积分被锁 1 小时换不来任何东西。
        handle_failure(
            session,
            task,
            ProviderFailure(
                f"任务 {task.id} 处于 submitted 但没有 provider_task_id",
                code="MISSING_PROVIDER_TASK_ID",
                retryable=False,
            ),
            now=moment,
        )
        return True

    _started = time.perf_counter()
    try:
        result = provider.poll(task.provider_task_id)
    except ProviderFailure as exc:
        _record_call(audit, "query", started=_started, task=task, failure=exc)
        handle_failure(session, task, exc, now=moment)
        return True
    _record_call(audit, "query", started=_started, task=task, result=result)

    if result is None:
        # ⚠️ 「还没好」这一次**也要记**。它是轮询里出现次数最多的那一种
        #    （一条视频可能问几十次），而「一天问了多少次、平均几次才出片」
        #    正是判断轮询间隔该多长的唯一依据。只记成功那次的话，
        #    对账表会显示出一条视频只调了一次 —— 与事实差几十倍。
        return False

    finish_succeeded(
        session,
        task,
        request=request,
        result=result,
        provider=provider,
        now=moment,
        defer_io=defer_io,
    )
    return True


def finish_succeeded(
    session: Session,
    task: Task,
    *,
    request: GenerationRequest,
    result: ProviderResult,
    provider: GenerationProvider,
    now: datetime | None = None,
    sync: bool = False,
    defer_io: bool = False,
) -> None:
    """成功收尾：**§7.2 三段式的后两段** + §9.2 转存 + §11.2 落资产。

    【`settle` 为什么要 `min(raw, freeze)`】§7.2 ④：实际时长超过冻结
    上限时，**平台自担差额**。不钳的话余额会被扣成负数 —— 那不是
    「少收点钱」，而是直接撞上 `balance >= 0` 的约束、
    把一个本该成功的任务变成 500。

    ─────────────────────────────────────────────────────────
    【B4：为什么「结算」被推到了转存之后】

    因为「成功」的定义是**用户拿到了东西**。provider 那边做出来了、
    但我们还没搬回自己的存储，这时收钱是在为一个用户拿不到的文件
    收费 —— 而 §9.2 的转存是**会失败**的（§9.3 专门为它定了重试与
    退款）。所以顺序是：先转存，拿到了再结算。

    代价是转存的那段时间里，这笔冻结仍然冻着 —— 对的，用户也确实
    还在等（前端显示的状态仍是 `submitted`，即「生成中」）。
    ─────────────────────────────────────────────────────────
    """
    moment = now or utcnow()

    claimed = _claim_transfer(session, task, result=result, now=moment)
    if claimed is None:
        return

    if defer_io:
        # 【B6】认领完就停。见 `_claim_transfer` 上面那段「事务边界」——
        # 调用方提交这个事务之后，由 worker 的 ②.5 相位在**事务外**
        # 把 IO 做掉，再回到一个短事务里落定。
        return

    specs, failure = perform_transfer(task_id=int(task.id), kind=task.kind, provider_url=claimed)
    finish_transferred(
        session,
        task,
        request=request,
        result=result,
        provider=provider,
        specs=specs,
        failure=failure,
        now=moment,
        sync=sync,
    )


# ══════════════════════════════════════════════════════════════
# 转存：认领（事务内）→ 搬运（事务外）→ 落定（事务内）
# ══════════════════════════════════════════════════════════════
#
# 【B6 为什么把它切成三段】
#
# ─────────────────────────────────────────────────────────
# 原来的写法是「一个函数、IO 夹在中间」，而那意味着**网络与磁盘的耗时
# 全都被算在 SQLite 的唯一写锁里**。B4 时 IO 是本地复制（几十 KB、
# 毫秒级），所以只是理论问题；B6 接上 OSS 之后，一次 `put_file` 是
# 20MB 过公网 —— 那段时间里**整个平台一条任务都写不进库**，
# 而且症状是「偶发地一切都很慢」，不像一个能定位的 bug。
#
# 于是拆成三段，中间那一段**不接会话**：
#
#   ① `_claim_transfer`    事务内：登记 `running` + 记下地址
#   ② `perform_transfer`   **事务外**：纯 IO，签名里连 `Session` 都没有
#   ③ `finish_transferred` 事务内：失败处置 / 结算 / 落资产
#
# ─────────────────────────────────────────────────────────
# 【为什么同步路径（`submit` → `dispatch(sync=True)`）**不**拆】
#
# 因为它靠「IO 在外层事务里被回滚」实现「被拒的提交不留痕」——
# `test_transfer_b4.py::test_同步路径的转存失败_502_而且一整笔都不留`
# 钉着这条契约。把 IO 挪出去，那条路会变成「200 + 一条永远
# `submitted` 的任务」，而 `TEST_MODE=1`（跨仓门禁的配置）**不起
# worker**，于是它永远好不了。
#
# 对真 provider 而言同步路径本来就安全：`JimengProvider.submit`
# **永远返回 `done=False`**，下载/上传从不在请求路径上内联发生。
#
# 【`running` 这个值从此真的会被持久化】
#
# 拆开之前它只活在事务内部（要么整体提交时已经是 `done`，要么整体
# 回滚），所以库里的 `running` 是「不该存在的东西」。现在它是
# **一条明确的待办**：「有人认领过这次转存，但没落定」——进程死在
# 中间、或者落定那一步失败，下一轮 worker 会靠它把活儿捡回来。
# ══════════════════════════════════════════════════════════════


def _claim_transfer(
    session: Session, task: Task, *, result: ProviderResult, now: datetime
) -> str | None:
    """登记「这条任务的产物该由谁去搬」。返回要搬的地址，或 `None`。

    **它只写库 —— 不碰网络、不碰磁盘。** 返回 `None` 的每一种情况都
    意味着「这次不用搬」，而且每一种的理由都不一样：

      · 已经 `succeeded`  → 幂等护栏，绝不二次结算；
      · `transfer_state` 已经是 `done` → 构造上不可达，真出现要人工看一眼；
      · 没有地址 → 当场判死（等不来地址的任务只会白锁着冻结）；
      · 还在退避窗口里 → 下一轮再说。
    """
    # ── ⓪ 幂等护栏：绝不二次结算 ──────────────────────────
    # 【为什么这条最重要】`settle_and_refund` 跑两遍会把钱扣两遍，
    # 而账面上余额仍然是「对的」（流水里有两条 settle，各自都合法）。
    # 这正是文件头说的那类「两边各写一份收尾逻辑」才会暴露的问题，
    # 所以在这里用一行代码把它堵死。
    if task.status is TaskStatus.succeeded:
        return None

    task.output_duration_sec = result.output_duration_sec
    if result.provider_url:
        # 【为什么存在 task 上】重试转存时要用（见 worker 的 ②.5 相位）：
        # 那条路不能再问 provider 一次，只能拿这个地址重跑。
        # ⚠️ 它**绝不进任何响应**（`TaskOut` 里没有这个字段，有守卫测试）。
        task.provider_url = result.provider_url

    # ── ① 转存认领 ────────────────────────────────────────
    if task.transfer_state is TransferState.done:
        # 【构造上不可达】`done` 与 `status=succeeded` 在**同一个事务**里
        # 写入，所以看见 done 就必然已经 succeeded —— 上面那条护栏会先返回。
        # 真出现时，宁可让任务停在 `submitted` 等超时兜底，
        # 也不要在没有产物规格的情况下凭记忆落资产。
        logger.error(
            "任务 %s 的转存已完成，但状态仍是 %s —— 需要人工看一眼",
            task.id,
            task.status.value,
        )
        return None

    if not task.provider_url:
        # provider 说「做好了」却没给地址。这不是能等好的事：
        # 没有地址就永远转存不了，冻结会一直锁到超时。
        _fail_transfer(session, task, reason="provider 没有给出产物地址", now=now)
        return None

    # ── ② 退避与重试上限 ──────────────────────────────────
    if not _transfer_retry_due(task, now):
        # 【为什么要有退避，而不是「下一轮再来」】真 provider 的 poll
        # 每轮都会把同一个 done 结果带回来，而 worker 的 ②.5 相位也会来
        # 捡它 —— 没有退避的话，两个入口会在**同一轮里各花掉一次重试**，
        # 3 次预算两轮就见底，一次抖动都不给它扛过去的机会。
        # 退避把「3 次重试」摊开成一段真正的时间。
        return None

    # ── ③ 认领 ────────────────────────────────────────────
    task.transfer_state = TransferState.running
    return task.provider_url


def perform_transfer(
    *, task_id: int, kind: TaskKind, provider_url: str
) -> tuple[list[ArtifactSpec], TransferFailure | None]:
    """搬一次产物。**纯 IO：签名里连 `Session` 都没有。**

    ⚠️ 这个签名是**故意的**，不是「顺手抽一个函数」——它让
    「往里加一句查库」变成一件必须改签名才能做的事。而真发生了那种
    改动时，读的人会在这里看见它，而不是在某次线上事故之后。

    失败**不抛**，而是作为第二个返回值交回去：调用方紧接着要开一个
    事务去处置它，用返回值比 `try/except` 更容易看出「这两件事
    之间**没有**事务」。
    """
    try:
        return transfer_artifact(task_id=task_id, kind=kind, provider_url=provider_url), None
    except TransferFailure as exc:
        return [], exc


def finish_transferred(
    session: Session,
    task: Task,
    *,
    request: GenerationRequest,
    result: ProviderResult,
    provider: GenerationProvider,
    specs: list[ArtifactSpec],
    failure: TransferFailure | None,
    now: datetime | None = None,
    sync: bool = False,
) -> None:
    """搬运之后的那一半：失败处置 / 结算 / 落资产。**全在事务里。**

    ⚠️ 调用方必须保证 `specs` 对应的字节**已经落存储**了 ——
    本函数不校验任何路径，它只是把规格写成 `assets` 行。
    """
    moment = now or utcnow()
    settings = get_settings()

    # ── 转存没成 ──────────────────────────────────────────
    if failure is not None:
        task.transfer_attempts += 1
        task.transfer_state = TransferState.failed
        task.error_code = TaskErrorCode.TRANSFER_FAILED.value
        # 【为什么不把地址放进 error_msg】`error_msg` **会出现在响应里**
        # （`TaskOut.error_msg`），而即梦的产物地址是带签名的 ——
        # 进去就等于进每一个客户端的缓存。要排查地址去日志里看，
        # `transfer._describe()` 只打 scheme + 主机 + 文件名，丢掉 query。
        task.error_msg = f"转存失败（第 {task.transfer_attempts} 次）：{failure}"
        logger.warning(
            "任务 %s 转存失败（第 %s/%s 次，%s）：%s",
            task.id,
            task.transfer_attempts,
            settings.transfer_max_retries,
            "不可重试" if not failure.retryable else "可重试",
            failure,
        )

        # 【两条路的分岔点：谁在等这个结果】
        # · 同步路径（`sync=True`）：用户手里攥着一个没返回的请求，
        #   而这个实例可能**根本没起 worker**（TEST_MODE=1 就是不启动的，
        #   那正是跨仓门禁的配置）。留在 `submitted` 等于让他永远等 ——
        #   所以立刻判失败，由 `submit` 升级成 502 并**回滚全部痕迹**。
        # · worker 路径：任务已经存在、钱已经冻了，回滚等于删证据
        #   （与 `dispatch` 里那段说明同款理由）。所以记在任务上等重试。
        if (
            sync
            or not failure.retryable
            or task.transfer_attempts >= settings.transfer_max_retries
        ):
            _fail_transfer(
                session,
                task,
                reason=f"转存失败（已试 {task.transfer_attempts} 次）",
                now=moment,
            )
        return

    # ── 转存成了 ──────────────────────────────────────────
    task.transfer_state = TransferState.done
    # 【为什么用完就清掉】它**只活 1 小时**（§9.2），是搬运用的中转，
    # 不是资产真相。留着只会在下一次有人读这个字段时给出一个
    # 已经失效的地址。
    task.provider_url = None

    # ── 在飞期间被别人终结了吗 ────────────────────────────
    if task.status is not TaskStatus.submitted:
        # 转存的这段时间里，worker 的过期相位可能把这个任务判成
        # `expired` 并**已经全额退款**（另一条线程/进程上）。
        # 这时再写一条结算 + 一批资产，就是给一个「已过期已退钱」的任务
        # 交付东西 —— 用户没花钱却拿到了作品，而账面上看不出来。
        #
        # ⚠️ 这条在 B6 之后**不再是理论上的**：IO 真的挪到了事务外，
        #    中间那段时间里别的连接是能改这一行的。
        logger.warning(
            "任务 %s 在转存期间变成了 %s，放弃落地（它已经退过款了）",
            task.id,
            task.status.value,
        )
        return

    # ── 结算 + 退回（§7.2 三段式的后两段）────────────────
    raw_settle = provider.settle_amount(request, result)
    settle = min(raw_settle, task.freeze_amount)

    task.settled_amount = settle
    task.status = TaskStatus.succeeded
    task.finished_at = moment
    task.error_code = None
    task.error_msg = None

    # 结算与退回必须同一个事务 —— 由调用方的 `atomic()` 保证。
    credits.settle_and_refund(
        session,
        task.user_id,
        task_id=task.id,
        freeze_amount=task.freeze_amount,
        settle=settle,
    )
    # ── 落资产（用**真实**的产物规格）────────────────────
    _create_assets_for(session, task.user_id, task, specs)


def _transfer_retry_due(task: Task, moment: datetime) -> bool:
    """这一轮该不该再试一次转存。

    【为什么借用 `updated_at` 而不是加一列】失败那一次写库正好把它
    推到失败时刻（`models.Task.updated_at` 带 `onupdate=utcnow`），
    语义上够用，而**加一列要一次 Alembic 迁移**。B4 刻意不动表结构。
    ⚠️ 它是借用：任何一次对任务行的 UPDATE 都会推开这个窗口。
    真到了「说不清为什么这一轮没重试」的时候，B6 补一个
    `transfer_next_attempt_at`（HANDOFF 里已经记着这条）。
    """
    if task.transfer_attempts == 0:
        return True
    updated = task.updated_at
    if updated is None:
        return True
    return moment >= updated + timedelta(seconds=get_settings().transfer_retry_backoff_sec)


def _fail_transfer(session: Session, task: Task, *, reason: str, now: datetime) -> None:
    """转存彻底失败：`failed` + `TRANSFER_FAILED` + **全额**退回。

    【为什么是全额而不是「按已生成的成片扣」】成片在 provider 那边确实
    做出来了，但我们**没把它交付出去**。§7.6 的退款纪律只有一条：
    没交付就全退。按内部状态扣钱的话，用户会为一份他永远看不到、
    也永远不会出现在他作品页里的文件付钱。
    """
    task.transfer_state = TransferState.failed
    task.error_code = TaskErrorCode.TRANSFER_FAILED.value
    task.error_msg = reason
    _terminate(session, task, TaskStatus.failed, note="转存失败，全额退回", now=now)


def handle_failure(
    session: Session, task: Task, exc: ProviderFailure, *, now: datetime | None = None
) -> None:
    """provider 报错时按 §7.5 的重试纪律处置。**三条去向，一条都别漏。**

    ─────────────────────────────────────────────────────────
    | 情况 | 去向 | 为什么 |
    |---|---|---|
    | 审核类（`rejected`） | `rejected` + 全额退回 | 重试一万次也是同样结果，重试只是白花钱 |
    | 可重试且还有次数 | 退回队列、退避后再来 | 限流/5xx 是**等一下就好**的 |
    | 其余 | `failed` + 全额退回 | 钱不能锁着，用户得知道它坏了 |

    【为什么「审核类」不是靠 `retryable` 推断出来的】因为它们是**两个
    独立的维度**：审核失败既不可重试、也不该把任务记成 `failed`。
    用一个 bool 表达两件事的话，`rejected` 迟早会被当成「一种 failed」，
    而前端 §12.3 对 422 和 502 的处理文案完全不同
    （「提示改写」 vs 「可重试」）。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    moment = now or utcnow()
    task.error_code = exc.code
    task.error_msg = str(exc)

    if exc.rejected:
        _terminate(session, task, TaskStatus.rejected, note="内容审核未通过，全额退回", now=moment)
        return

    if exc.retryable and task.retry_count < settings.provider_max_retries:
        queue.requeue_for_retry(session, task, now=moment)
        logger.warning(
            "任务 %s 第 %s 次重试（%s），%s 秒后再来",
            task.id,
            task.retry_count,
            exc.code,
            queue.retry_backoff_sec(task.retry_count),
        )
        return

    _terminate(session, task, TaskStatus.failed, note="生成失败，全额退回", now=moment)


def expire_stale(session: Session, task: Task, *, now: datetime | None = None) -> None:
    """§8.3：超过 `task_timeout_sec` 还没终态 → `expired` + 全额退回。

    【为什么必须有这条】它是「冻结永远不释放」的唯一兜底。没有它，
    provider 那边卡住一个任务，用户那笔积分就**永久**锁在冻结里 ——
    而冻结是不可见的（`available` 才是用户能用的），用户只会发现
    「我明明还有钱，为什么生成不了」。这类事故在账面上查不出来：
    余额没变、没有失败任务、没有流水异常。
    """
    task.error_code = TaskErrorCode.TASK_TIMEOUT.value
    task.error_msg = (
        f"任务 {task.id} 在 {get_settings().task_timeout_sec} 秒内没有到终态"
        f"（最后状态 {task.status.value}）"
    )
    _terminate(session, task, TaskStatus.expired, note="超过处理时限，全额退回", now=now)


def _terminate(
    session: Session, task: Task, status: TaskStatus, *, note: str, now: datetime | None = None
) -> None:
    """**所有非成功终态的收尾都走这里。**

    【为什么失败也要落 `finished_at`】不落的话，`/tasks?status=done`
    里那些任务的时间线是断的 —— 用户问「这个任务什么时候失败的」，
    答案是「不知道」。而且「终态但 finished_at 为空」本身就是一条
    自相矛盾的记录，和 B2 里那条「succeeded 却没有 submitted_at」同源。

    【`settled_amount` 保持 NULL】§11.2 的约束只管 succeeded。
    给失败任务写 0 会让「未结算」和「结算了 0 积分」变成同一个值 ——
    而这是两件完全不同的事（B2 的契约里专门说过这条）。
    """
    moment = now or utcnow()
    task.status = status
    task.finished_at = moment
    task.provider_task_id = None
        # 这条任务不会再被 poll 了，句柄留着只会让将来某个查询
        # 误以为「还能去问 provider」。
    task.provider_url = None
        # 【B4 补的】同理：它是**只活 1 小时**的中转地址（§9.2）。
        # 任务已经终态了，留着它只会在将来某次「找找还有没有能重试的」
        # 查询里被当成一条线索。
    if task.transfer_state in (TransferState.running, TransferState.failed):
        # 【为什么只在这两种状态下改它】`none` 表示「压根没有产物的搬运
        # 可言」（排队中失败、审核未通过），把它标成 `failed` 是撒谎；
        # `done` 表示产物已经落地了，那条路走不到这里（成功收尾不走
        # `_terminate`）。只有「试过 / 正在试」的那些，终态才配得上
        # `failed` 这个词。
        task.transfer_state = TransferState.failed
    credits.refund_frozen_all(
        session,
        task.user_id,
        task_id=task.id,
        freeze_amount=task.freeze_amount,
        note=note,
    )


def _create_assets_for(
    session: Session, user_id: int, task: Task, specs: list[ArtifactSpec]
) -> None:
    """把**已经落存储的**产物写成 `assets` 行。§11.2。

    【视频为什么连封面一起落】因为作品列表一屏要摆九个视频。
    每个都直接加载视频文件当封面的话，流量和内存都会炸。
    封面是单独一张小图，列表读它，点开才读视频。

    【B4 改了什么：宽高与大小不再是写死的】
    B2 这里写的是 1280×720 / 1024×1024 和 `size_bytes=None`，因为那时
    磁盘上没有字节。现在尺寸是从**真实文件**里探出来的
    （`transfer.ArtifactSpec`），所以写死的常量没有存在的理由 ——
    而它一旦写死，`assets` 就会和文件说的是两件事。

    ⚠️ **只有 `duration_sec` 仍然取自任务**（`task.output_duration_sec`）：
    那是**计费依据**，也是前端断言钉住的值（`test_tasks_assets_b2.py`
    的 `duration_sec == 6`）。ffprobe 量出来的时长是编码器时间基下的
    另一个数，用它会让那条断言因为一个与契约无关的原因变红。
    这也是 `ArtifactSpec` 上**故意没有** duration 字段的原因。

    【`is_ai_generated` 一律 True】§11.2：平台产物都是 AI 生成的。
    这一列是《人工智能生成合成内容标识办法》要求的法律义务字段，
    漏打标是合规问题，不是显示问题。（封面是 AI 视频的一帧，同样算。）

    ─────────────────────────────────────────────────────────
    【B6：地址为什么改走 Storage 实例】

    原来这里调的是**模块级**的 `storage.public_url_for`，而那个函数把
    `/media/` 写死在路径里。走 `local` 时它是对的（`main.py` 挂的
    静态目录就是 `/media`）；走 OSS 时它会拼出
    `{PUBLIC_BASE_URL}/media/t/12/xxx.mp4` —— 一个指向**我们这台机器**
    的地址，而文件在桶里。那个地址对用户是一个 404，对排查的人是
    一个「静态挂载配错了」的假线索。

    改成走实例的 `url_for` 之后，「地址怎么算」和「字节落在哪」由
    同一个实现回答（`assets.py` 对上传的参考图一直是这么做的）。
    两处对同一件事各有一套算法，正是这个仓库反复在防的形态。
    ─────────────────────────────────────────────────────────
    """
    store = storage.build_storage()
        # 【为什么提到循环外】OSS 下这一句会建一个 boto3 客户端
        # （连接池 + 签名器）。放循环里的话，一条视频的两个资产
        # 会各建一个，而那些连接直到进程退出才回收。
    for spec in specs:
        asset = Asset(
            user_id=user_id,
            task_id=task.id,
            kind=spec.kind,
            storage_key=spec.storage_key,
            public_url=store.url_for(spec.storage_key),
            mime=spec.mime,
            size_bytes=spec.size_bytes,
            duration_sec=task.output_duration_sec if spec.kind is AssetKind.video else None,
            width=spec.width,
            height=spec.height,
            is_ai_generated=True,
        )
        session.add(asset)
        if spec.kind is AssetKind.video and spec.sha256 is not None:
            session.flush()
            evidence.enqueue(session, asset, task, spec.sha256)


# ══════════════════════════════════════════════════════════════
# 任务查询与取消
# ══════════════════════════════════════════════════════════════


def get_task(session: Session, user: User, task_id: int) -> Task:
    """按 id 取任务。**别人的任务 = 不存在**（404，不是 403）。"""
    task = session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise AppError(ErrorCode.NOT_FOUND, f"任务 {task_id} 不存在或不属于当前用户")
    return task


def task_detail(session: Session, user: User, task_id: int) -> TaskOut:
    task = get_task(session, user, task_id)
    return TaskOut.from_task(task, queue_position=queue.position_of(session, task))


def list_tasks(session: Session, user: User, status_filter: str | None) -> TaskListOut:
    """`GET /tasks?status=active|done` —— **不是分页接口**。

    【为什么不分页】§12.1 里 `/tasks` 没有分页参数，前端
    `RemoteTaskRepository._fetchList` 也专门说明了它为什么不用
    `Paged.fromJson`。这里把全部任务返回，`page_size` 填 `len(items)`
    而不是默认的 20 —— 填 20 会让第 21 条任务**静默消失**，
    因为前端拿到 `items` 就渲染，从不翻页。

    ⚠️ 这个决定有一个明确的代价：任务攒到几千条时这个响应会很大。
    但 `/tasks` 的真实用法是「进行中」和「最近完成」两屏，
    真要全量那是 B3 之后的事（届时得先补契约，因为前端不支持翻页）。
    """
    statement = select(Task).where(Task.user_id == user.id)

    if status_filter == STATUS_FILTER_ACTIVE:
        statement = statement.where(Task.status.in_(ACTIVE_STATUSES))
    elif status_filter == STATUS_FILTER_DONE:
        statement = statement.where(Task.status.in_(TERMINAL_STATUSES))

    # 新的排在前面。带 `id DESC` 兜底是因为同一微秒建的多个任务
    # 时间可能完全相同，只按时间排不稳定（和流水那边同一个理由）。
    tasks = session.scalars(
        statement.order_by(Task.created_at.desc(), Task.id.desc())
    ).all()

    items = [TaskOut.from_task(t, queue_position=queue.position_of(session, t)) for t in tasks]
    return TaskListOut(items=items, page=1, page_size=len(items), total=len(items))


def cancel_task(session: Session, user: User, task_id: int) -> TaskOut:
    """`POST /tasks/{id}/cancel`。§7.4 的退费政策。

    ─────────────────────────────────────────────────────────
    【只有排队中取消才全额退回】

    已提交给 provider 之后取消是**不退**的 —— provider 已经在跑，
    钱已经花出去了。这个区别必须如实体现，不能一律全退：
    否则 UI 上「取消会退多少」的提示永远是错的，
    用户会在真的被扣钱时投诉。

    ─────────────────────────────────────────────────────────
    【B3 起「排队中取消」才真的可达】

    B2 里所有任务在提交那一刻就已是终态，所以这个端点只会返回
    `TASK_NOT_CANCELABLE`。有了真队列之后，`queued` 是一个**会持续
    一段时间**的状态，用户在这段时间里点取消，就该拿到全额退回。

    ⚠️ 它和 worker 之间有一个竞态：用户点取消的同时，worker 可能
      刚好把这条任务捞去提交了。两边都在写这一行，靠的是
      **同一个事务里读、同一个事务里写**（status 的读取发生在
      `get_task` 里，它已经开启了本会话的事务，而 `atomic()` 只是在
      末尾 commit）。所以取消看到的 status 和它据以退费的 status
      永远是同一个 —— 不会出现「按 queued 退了钱，而任务其实
      已经 submitted」。
    ─────────────────────────────────────────────────────────
    """
    task = get_task(session, user, task_id)

    if task.status.is_terminal:
        raise AppError(
            ErrorCode.TASK_NOT_CANCELABLE,
            f"任务 {task.id} 已经是 {task.status.value}，不能再取消",
        )

    refundable = task.status in (TaskStatus.pending, TaskStatus.queued)

    with atomic(session):
        if refundable:
            credits.refund_frozen_all(
                session,
                user.id,
                task_id=task.id,
                freeze_amount=task.freeze_amount,
                note="排队中取消，全额退回",
            )
            task.settled_amount = 0
        else:
            credits.charge_frozen(
                session,
                user.id,
                task_id=task.id,
                freeze_amount=task.freeze_amount,
                note="已提交给生成服务后取消，不予退回",
            )
            task.settled_amount = task.freeze_amount

        task.status = TaskStatus.canceled
        task.finished_at = utcnow()

    return TaskOut.from_task(task, queue_position=None)
