"""worker —— §8.3 的单进程轮询循环。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【§8.3 把它的职责写成了六条，这个文件逐条落位】

  ① 看闸门空位      → `queue.has_free_slot`
  ② 取 `queued` 任务 → `queue.claim_next`
  ③ `submit`        → `generation.dispatch`
  ④ 对所有 `submitted` 任务 `poll` → `generation.poll_once`
  ⑤ `done` 时立刻转存 + 结算 → `generation.finish_succeeded`
  ⑥ 写回状态        → 每次迁移都在自己的事务里 commit

【B6 对 ⑤ 的修改：worker 路径上的转存 IO 挪到了事务外】

`dispatch` / `poll_once` 都传 `defer_io=True`，于是它们**只登记**
（`transfer_state = running`）就返回；真正的搬运由 ②.5 相位
（`_retry_transfers`）在事务外做完，再回到一个短事务里结算。

**这是本文件里唯一一处 IO 在事务外的地方**，而它是 B6 的主要交付：
B4 的 IO 是本地复制（毫秒），B6 的 OSS 上传是 20MB 过公网 ——
夹在事务里的话，那段时间**整个平台一条任务都写不进库**。
同步路径（`submit`）**保持原样**，理由见 `generation` 里那段「事务边界」。

【为什么是「一个线程 + while 循环」，不是 Celery / asyncio 任务】

§4.1 定稿不引入 Redis/Celery，§8.1 给了算术上的理由（只要一道信号量）。
剩下的选择是 asyncio 任务还是线程，这里选**线程**，原因是这个
进程里的数据库访问全是**同步**的 SQLAlchemy：塞进事件循环要用
`run_in_executor` 把它包起来，绕一圈还是回到线程上。

【为什么一轮里每个任务各开一个事务，而不是整轮一个】

因为一轮里可能包含**真实的网络调用**（问即梦「好了没」）。整轮一个
事务的话，这些调用的耗时全都算在同一个写事务里 —— 在 SQLite 上
就是「用户点生成，等 worker 把别人的 10 个任务问完才能写」。
每个任务一个事务的代价是多几次 commit，换来的是 API 永远不等 worker。

【⚠️ 单实例假设】

两个 worker 同时跑会把同一条任务问两次、也可能各提交一次。
v1 的部署形态是单进程（`uvicorn` 一个 worker），所以没有做租约。
`claim` 是「先 SELECT 再改状态」，在 PostgreSQL 多实例下需要改成
带条件的 UPDATE（`WHERE status='queued'` + 看 rowcount）。
**这是记在案的一处已知缺口**，见 `HANDOFF.md`，不是没想到。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session_factory
from app.enums import ACTIVE_STATUSES, TaskKind, TaskStatus, TransferState
from app.models import Task
from app.providers import GenerationProvider, ProviderResult, build_provider
from app.services import generation, queue
from app.services.provider_audit import CallAudit
from app.services.unit import atomic
from app.types import utcnow

logger = logging.getLogger("aivideo.worker")

MAX_DISPATCH_PER_TICK = 100
""""一轮最多出队几个"。**这不是限流，是防活锁的保险丝。**

按 §8.3 的分工，每一轮出队要么占掉一个闸门位（于是 `while` 结束）、
要么把任务推进到终态（于是它不再出现在队列里），所以循环必然终止。
但这个论证依赖「provider 会了结任务」——真接上即梦之后，
一个「提交永远成功、轮询永远没有结果」的 provider 会让这条循环
每轮都跑满。100 这个数字比正常一轮的出队量大得多（闸门是 1–2），
真撞上它说明该去看日志，而不是该调大它。
"""

# ── 轮询节奏（进程内） ───────────────────────────────────────
#
# 【为什么要记一个「上一轮问 provider 是什么时候」】
# worker 每 2 秒巡一次（`worker_poll_interval_sec`），但问即梦不该
# 问得那么勤（`provider_poll_interval_sec` = 10 秒，一条视频本来就要
# 跑 10 分钟）。两个间隔不是一回事，所以要分别记。
#
# 【为什么它不算「任务状态放在内存里」】铁律管的是**任务状态** ——
# 那些永远在库里，重启不丢。这个变量是一张**调度便签**：
# 丢了最坏的结果是「启动后立刻多问一次 provider」，没有任何任务
# 会因此走错状态。它刻意不写库，是因为为它加一列就要一次迁移，
# 而它带来的价值只有「启动瞬间少一次多余的 HTTP 请求」。
_last_poll_round: datetime | None = None


def reset_poll_schedule() -> None:
    """忘掉「上一轮问过了」。**测试用**，见上面那段说明。"""
    global _last_poll_round
    _last_poll_round = None


@dataclass
class TickReport:
    """一轮干了什么。**给测试和日志用**，不是给用户看的。

    【为什么用 task id 列表而不是计数】因为断言「哪一条被推进了」
    比断言「有 1 条被推进了」有用得多 —— 后者在「推错了那一条」
    的时候照样是绿的。
    """

    expired: list[int] = field(default_factory=list)
    advanced: list[int] = field(default_factory=list)
    retried: list[int] = field(default_factory=list)
        # B4：这一轮**把转存搬完并成功推进**的任务（②.5 相位）。
        # 【为什么不并进 `advanced`】两者的病因完全不同：`advanced`
        # 多起来是 provider 的正常节奏，`retried` 多起来是**转存在坏**
        # （签名过期、OSS 抽风）。混在一起的话，「今天推进了 200 条」
        # 看起来一切正常，而其中 150 条是同一份产物重试了 150 次。
        #
        # 【B6：这一桶里现在装了两类，名字没改】因为对**看日志的人**
        # 它们要回答的是同一个问题「这一轮有几条任务是被 ②.5 推走的」。
        # 两类是「延迟到事务外的首搬」与「失败了再搬一次」，而它们的
        # 区别（`transfer_attempts`）在库里查得到 —— 与其在这里多开
        # 一个只有测试会读的桶，不如让读的人去查那一个数。
    dispatched: list[int] = field(default_factory=list)
    polled: bool = False
        # 这一轮到底问没问 provider（受 `provider_poll_interval_sec` 节制）。

    @property
    def touched(self) -> bool:
        return bool(self.expired or self.advanced or self.retried or self.dispatched)


# ══════════════════════════════════════════════════════════════
# 一轮
# ══════════════════════════════════════════════════════════════


def _provider_for(
    injected: GenerationProvider | None, kind: TaskKind
) -> GenerationProvider:
    """这一次调用该用哪个 provider。**`kind` 是唯一判据。**

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么是「每个使用点现取」，而不是在 `run_once` 开头取一次】

    B7.x 之前这里是一行 `active_provider = provider or build_provider()`：
    一个 tick 造一个 provider，然后在 `for kind in TaskKind` 里
    用在**所有类型**上。那个写法在「只有一个 provider」的世界里是对的，
    而图生视频换成 MiniMax 之后，部署形态变成
    「文生图走 fake/即梦、图生视频走 MiniMax」—— 一个 provider 表达不了。

    【`injected` 优先为什么是对的（而不是「注入也要按 kind 分」）】
    注入的用途只有一个：测试把 `ScriptedProvider` 塞进来，
    好让整条流水线**不碰真网关**。那个替身对每一种 kind 都有效，
    所以它该一路用下去。按 kind 分只在**从配置造**的时候才有意义。

    ⚠️ **别把这个函数内联掉。** `or` 的左边是「有人指定了」、
    右边是「按配置造」，两件事；内联之后很容易在某一处写成
    `build_provider(kind)` 而把注入漏掉 —— 那次漏掉的表现是
    测试真的去连了真网关，而它**不会报错**，只会变慢或变红。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    return injected or build_provider(kind)


def run_once(
    session: Session,
    *,
    now: datetime | None = None,
    provider: GenerationProvider | None = None,
) -> TickReport:
    """走一轮。**测试直接调它** —— 不用起线程，也不用真的等。

    ─────────────────────────────────────────────────────────
    【三个阶段的顺序是有讲究的】

      1. **过期**（`expired` + 全额退回）
      2. **问进度**（`submitted` → `succeeded`/`failed`/`rejected`）
      3. **出队**（`queued` → `submitted`）

    2 在 3 前面，是因为一条 `submitted` 任务在这一轮结束时可能刚好
    完成、从而**空出一个闸门位**。3 排在它后面，那一位当轮就能被
    用上；反过来（先出队后问进度）则每次都要白等一轮 ——
    而「一轮」是 2 秒，闸门只有 1–2 个位子，白等的代价会被放大成
    整条队列的吞吐下降。

    【B4 加的 ②.5 为什么排在 2 与 3 之间】同款理由：转存成功会
    释放一个 provider 闸门位，当轮就能被 ③ 用上。

    【这条顺序在 B6 之后变得更要紧，而不是更松】因为 ② 相位现在
    只**认领**转存（`defer_io=True`），真正的搬运在 ②.5 ——
    所以「当轮结算」这件事完全押在「②.5 排在 ② 后面」上。
    换过来写（②.5 在 ② 前面）不会报错，只会让**每一条**在 ② 完成的
    任务都白等一轮（2 秒），而症状是「也就慢一点点」，没人会去查。

    （③ 相位里认领的转存要等**下一轮**的 ②.5 —— 这是拆事务的代价，
    而它值：那一轮多花的 2 秒换的是「OSS 上传期间全平台可写库」。）

    【`now` 为什么是参数】因为「等 10 秒」「退避 4 秒」这些事在测试里
    不能真的 sleep —— 于是所有跟时间有关的判断都必须从**传入的**
    `now` 读，而不是各自去 `utcnow()`。漏掉一处，那条测试就会
    变成一个真的会睡 10 秒的慢测试（或者更糟：一个不稳定的测试）。
    ─────────────────────────────────────────────────────────
    """
    moment = now or utcnow()
    report = TickReport()

    _expire_stale(session, moment, report)
    _advance_submitted(session, moment, provider, report)
    _retry_transfers(session, moment, provider, report)
    _dispatch_ready(session, moment, provider, report)

    if report.touched:
        logger.info(
            "worker：过期 %s 条，推进 %s 条，补转存 %s 条，出队 %s 条",
            len(report.expired),
            len(report.advanced),
            len(report.retried),
            len(report.dispatched),
        )
    return report


def _expire_stale(session: Session, moment: datetime, report: TickReport) -> None:
    """阶段 1：超过 `task_timeout_sec` 还没终态的任务判 `expired` 并全额退回。

    【为什么按 `created_at` 算，而不是 `queued_at` / `submitted_at`】
    因为只有 `created_at` 在**所有活跃状态下都有值**。用 `submitted_at`
    的话，一条卡在 `pending`（比如入队那一步挂了）的任务永远没有
    时间基准，也就永远不过期 —— 而它恰恰是最需要兜底的那一条。
    """
    deadline = moment - timedelta(seconds=get_settings().task_timeout_sec)
    stale_ids = session.scalars(
        select(Task.id).where(
            Task.status.in_(ACTIVE_STATUSES),
            Task.created_at < deadline,
        )
    ).all()

    for task_id in stale_ids:
        # 每个任务一个事务：一条任务的异常不该把同一个阶段里
        # 其余的过期处理一起回滚掉。
        with atomic(session):
            task = session.get(Task, task_id)
            if task is None or task.status not in ACTIVE_STATUSES:
                continue
            logger.warning("任务 %s 超过 %s 秒仍未终态，判过期", task_id, get_settings().task_timeout_sec)
            generation.expire_stale(session, task, now=moment)
            report.expired.append(int(task_id))


def _advance_submitted(
    session: Session,
    moment: datetime,
    provider: GenerationProvider | None,
    report: TickReport,
) -> None:
    """阶段 2：§8.3 职责 ④ —— 对所有 `submitted` 任务问一次进度。

    【`provider` 为什么是可空的】见 `_provider_for`：注入为 `None` 时
    **逐条任务**按 `task.kind` 现造 —— 这一相位是跨 kind 的
    （一条 SQL 捞出所有 `submitted`），所以「用哪个 provider」
    只能到循环里面、拿到 `task` 之后才定得下来。
    """
    global _last_poll_round
    interval = timedelta(seconds=get_settings().provider_poll_interval_sec)
    if _last_poll_round is not None and moment - _last_poll_round < interval:
        return
    _last_poll_round = moment
    report.polled = True

    submitted_ids = session.scalars(
        select(Task.id)
        .where(Task.status == TaskStatus.submitted)
        .order_by(Task.submitted_at.asc(), Task.id.asc())
    ).all()

    for task_id in submitted_ids:
        # ── 对账：每一条任务一个审计桶，冲在它自己的事务之后 ──────
        # 【为什么一任务一个，而不是一轮一个】因为 `provider_calls.task_id`
        # 要指对人。一轮一个的话，冲的时候只能拿到「最后那条任务」的 id ——
        # 于是一整轮的调用全被记到同一条任务头上，对账表看起来很正常，
        # 只是归属全错。
        audit = CallAudit()
        audit_task_id: int | None = None
        try:
            with atomic(session):
                task = session.get(Task, task_id)
                # 【为什么要重新判一次状态】因为上面的 SELECT 和这里的处理
                # 之间隔着别的任务的事务。够不到的东西不处理，比处理一个
                # 已经变了的行要便宜得多。
                if task is None or task.status is not TaskStatus.submitted:
                    continue
                request = generation.request_from_task(task)
                advanced = generation.poll_once(
                    session,
                    task,
                    request=request,
                    provider=_provider_for(provider, task.kind),
                    now=moment,
                    audit=audit,
                    # 【B6】产物到了也只**登记**，搬运交给 ②.5（事务外）。
                    defer_io=True,
                )
            # 【为什么赋值在 `with` 之外】`atomic()` 是退出时才 commit 的。
            # 放在里面的话，一条提交失败的任务也会把它的调用记到自己名下 ——
            # 而那条任务在库里根本不存在了。
            audit_task_id = int(task_id)
            if advanced:
                report.advanced.append(int(task_id))
        finally:
            # 审计是 best-effort（见 `provider_audit` 的文件头）：
            # 它写不进去也绝不许让一轮 worker 挂掉。
            audit.flush(task_id=audit_task_id)


def _retry_transfers(
    session: Session,
    moment: datetime,
    provider: GenerationProvider | None,
    report: TickReport,
) -> None:
    """阶段 ②.5：§9.3 / B6 —— 把「已认领但没搬完」的产物搬完并落定。

    ─────────────────────────────────────────────────────────
    【B6 起它服务的是两类任务，而两类的处置完全相同】

      · **延迟到事务外的首搬**：`finish_succeeded(defer_io=True)` 在
        ② / ③ 相位里只登记了 `transfer_state = running`，IO 留在这里；
      · **重试**：上一次搬失败，`transfer_state = failed`，过了退避再来。

    数据上它们只差 `transfer_attempts`（0 还是 ≥1）。分开写两份的
    后果是「事务外那一份」迟早会漏掉失败处置、或者反过来 ——
    而两条路各自的测试都是绿的。

    ⚠️ **这里是本文件唯一一处 IO 在事务外**（`perform_transfer` 的
    签名里连 `Session` 都没有）。改回事务里的话，
    `test_txn_boundary_b6.py` 会因为「搬运进行中，库里看不到那条
    认领（`transfer_state = running`）」而变红 —— 那条用例就是为
    这个而写的，别删它。

    【判据为什么是「认得见」而不是「别的连接写得进」】后者听起来
    才是 B6 的理由，但它**两种写法都是绿的**：会话是
    `autoflush=False`，搬运之前的几个阶段只发 SELECT，所以 SQLite
    那边**根本没拿过写锁**。那条用例的文件头把这件事写全了。

    【为什么不重问 provider】

    因为它要的东西**已经在库里**：`provider_url` 是产物地址，
    `output_duration_sec` 是计费与交付都需要的那个数。重建一个
    `ProviderResult` 交给 `finish_transferred` 就够了 ——
    这条路和 ② 走的是同一段落定逻辑（「收尾逻辑只有一份」）。

    ⚠️ 代价：重建出来的结果丢了 `provider_task_id` 与 params，
    所以这一步与 provider 接口是**耦合**的（对 fake 完全够用，
    真 provider 那边要复审）。记在 HANDOFF 的缺口里。

    【`running` 现在**真的**会落库了】

    B6 之前它在事务内写，那个事务要么整体提交（那时状态已经是
    `done`）、要么整体回滚 —— 所以库里的 `running` 是「不该存在的
    东西」，放在筛选条件里只是兜底。B6 之后 `running` 是一个**明确的
    待办**：「有人认领过这次转存，但没落定」。于是它必须**不等退避**
    就被捡起来 —— 否则每一次正常的 worker 转存都要白等一个退避窗口。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    backoff = timedelta(seconds=settings.transfer_retry_backoff_sec)
    ids = session.scalars(
        select(Task.id)
        .where(
            Task.status == TaskStatus.submitted,
            or_(
                # ① 已认领、还没搬完 —— **不等退避**。
                #    可能是这一轮刚在 ② / ③ 相位认领的（那时退避没有
                #    意义：还没有人试过），也可能是一个死在转存中途的
                #    进程留下的（那更不该等）。两种都当轮捡起来。
                Task.transfer_state == TransferState.running,
                # ② 上次搬失败了 —— 要等退避，理由见下面那段说明。
                and_(
                    Task.transfer_state == TransferState.failed,
                    # 【为什么这条不能少】它和 `finish_succeeded` 里的
                    # `_transfer_retry_due` 是**同一个判断的两个位置**：
                    # 一条 SQL 用不到那个函数，而漏掉它的话，两个入口会在
                    # 同一轮里各花掉一次重试预算（见那处的说明）。
                    Task.updated_at <= moment - backoff,
                ),
            ),
            Task.transfer_attempts < settings.transfer_max_retries,
            Task.provider_url.is_not(None),
        )
        # 先补最早的，别让新失败的任务插队（它们多半还要等退避）。
        .order_by(Task.updated_at.asc(), Task.id.asc())
    ).all()

    for task_id in ids:
        # ── ① 读：把这次搬运要的东西一次取全（**短事务**）────────
        #
        # ⚠️ 这一段之后**只准用局部变量**，别再去碰那个 ORM 对象 ——
        #    `atomic()` 退出时会 commit，而 commit 会让对象过期
        #    （下次访问属性会再发一次 SELECT）。那次 SELECT 会发生在
        #    **事务外**，也就是在一条没有事务保护的连接上读 ——
        #    读到的可能是别人刚改过的行，而下面的 IO 是照着旧值做的。
        with atomic(session):
            task = session.get(Task, task_id)
            # 与 ② 同款：够不到的东西不处理。
            if task is None or task.status is not TaskStatus.submitted:
                continue
            if not task.provider_url:
                # 在上面那条 SELECT 和这里之间被别的路径清了
                # （比如任务刚被终结）。下一条，别在这里猜。
                continue
            request = generation.request_from_task(task)
            result = ProviderResult(
                output_duration_sec=task.output_duration_sec or 0,
                provider_task_id=task.provider_task_id,
                provider_url=task.provider_url,
                done=True,
            )
            kind = task.kind
            provider_url = task.provider_url
            # 【为什么在这里定，而不是用 tick 开头那一个】同
            # `_advance_submitted`：这一相位也是跨 kind 的。而这一处
            # 尤其要小心 —— `finish_transferred` 拿 provider 是去**结算**
            # （`settle_amount`），算错的后果是直接错在钱上。
            active = _provider_for(provider, kind)

        # ── ② 搬运：**事务外**（B6）─────────────────────────────
        #
        # 这一段是 B6 的主要交付：签名里没有会话，所以它跑多久都不会
        # 占着 SQLite 的唯一写锁。这期间**别的连接可以自由写库** ——
        # `test_txn_boundary_b6.py` 就是拿这一点当判据的。
        specs, failure = generation.perform_transfer(
            task_id=int(task_id), kind=kind, provider_url=provider_url
        )

        # ── ③ 落定：新事务里结算 + 落资产（或记下失败）──────────
        with atomic(session):
            task = session.get(Task, task_id)
            if task is None:
                continue
            before = task.status
            generation.finish_transferred(
                session,
                task,
                request=request,
                result=result,
                provider=active,
                specs=specs,
                failure=failure,
                now=moment,
            )
            if task.status is not before:
                # 【为什么只在**状态真的变了**的时候才记】重试失败时
                # 任务仍是 `submitted`（还在等下一次），把它记成
                # 「推进了」会让日志和测试都以为它在往前走。
                #
                # 【B6：落定前**不再**判一次 `status`】因为搬运那段时间里
                # 任务可能已经过期退款了，而那种情况要在 `finish_transferred`
                # 里被**记一条 warning**（它的 ④ 那一小节）。在这里提前
                # `continue` 的话，那件事就悄无声息了。
                report.retried.append(int(task_id))


def _dispatch_ready(
    session: Session,
    moment: datetime,
    provider: GenerationProvider | None,
    report: TickReport,
) -> None:
    """阶段 3：§8.3 职责 ①②③ —— 闸门有空位就把队首捞出来交给 provider。

    【为什么按类各跑一遍】§8.2：图与视频**分开计数**。混在一起的话，
    一条排了十分钟的视频会把所有图片堵在后面（图片本来是秒级的）。

    【`kind` 在这一相位是循环变量，所以这一处最不需要绕】
    它本来就是「按 kind 各跑一遍」，provider 跟着 kind 走是
    最自然的一处 —— 反倒是 B7.x 之前那个「循环外用同一个 provider」
    才需要解释。
    """
    for kind in TaskKind:
        active = _provider_for(provider, kind)
        dispatched = 0
        while queue.has_free_slot(session, kind):
            task = queue.claim_next(session, kind, moment)
            if task is None:
                break  # 这一类没有到点的排队任务了
            # 【B6】这里是 worker 里**唯一**需要参考图公网地址的地方 ——
            # 因为只有这一相位的 provider 会真的把任务交出去
            # （② 只是问进度、②.5 只是搬产物）。见
            # `request_from_task` 签名上那段说明。
            request = generation.request_from_task(
                task, source_url=generation.source_url_for(session, task)
            )
            task_id = int(task.id)
            audit = CallAudit()
            audit_task_id: int | None = None
            try:
                with atomic(session):
                    generation.dispatch(
                        session,
                        task,
                        request=request,
                        provider=active,
                        now=moment,
                        audit=audit,
                        # 【B6】同 ② 相位：这一相位的 provider 通常是给回执
                        # 的，但一个「提交即完成」的 provider 在这里也会
                        # 产生产物 —— 那时搬运同样该在事务外。
                        defer_io=True,
                    )
                audit_task_id = task_id
                report.dispatched.append(task_id)
            finally:
                audit.flush(task_id=audit_task_id)

            dispatched += 1
            if dispatched >= MAX_DISPATCH_PER_TICK:
                logger.error(
                    "%s 一轮出队超过 %s 条，疑似活锁（provider 是不是永远不结束任务？）",
                    kind.value,
                    MAX_DISPATCH_PER_TICK,
                )
                break


# ══════════════════════════════════════════════════════════════
# 后台线程
# ══════════════════════════════════════════════════════════════


def run_forever(stop: threading.Event) -> None:
    """循环跑 `run_once` 直到 `stop` 被 set。

    【为什么单轮异常只记日志、不退出循环】因为一轮里最常见的异常是
    「数据库正忙」这种**下一秒就好了**的东西。让异常终止循环的话，
    一次锁等待就会把整个平台的队列停掉 —— 而它本来只需要重试一次。
    真的坏了的话，日志里会连着刷，看得见。
    """
    interval = get_settings().worker_poll_interval_sec
    logger.info("worker 启动（巡检间隔 %.1f 秒）", interval)

    while not stop.is_set():
        try:
            with get_session_factory()() as session:
                run_once(session)
        except Exception:  # noqa: BLE001 —— 见上面那段说明
            logger.exception("worker 本轮出错，跳过这一轮")
        stop.wait(interval)

    logger.info("worker 已停止。")


def start_background() -> threading.Event:
    """起一个 daemon 线程，返回它的停止开关。

    【为什么 daemon=True】它不该拖住进程退出。关停由 `lifespan` 里的
    `stop.set()` 负责；万一那条路没走到（比如进程被 SIGKILL），
    daemon 线程也不会让进程卡在退出中。
    """
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(stop,), name="aivideo-worker", daemon=True).start()
    return stop
