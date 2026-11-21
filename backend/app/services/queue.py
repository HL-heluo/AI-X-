"""队列 —— §8。**队列就是 `tasks` 表本身**，没有第二个数据结构。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这里没有 Redis / Celery / 消息队列】

§4.1 定稿，§8.1 给了理由，而理由是**算术**而不是品味：

  即梦默认并发 1–2，且**平台整体共享**（与用户数无关）；
  「60 秒视频约 10 分钟」→ 单账号吞吐上限约 6 条/小时。

于是队列要解决的是**一个信号量**，不是「一台机器扛不住的吞吐」。
为一道信号量引入一个中间件，换来的是：多一个会挂的进程、多一份
要备份的状态、以及「任务到底在库里还是在 Redis 里」这种对不上账的问题。

【为什么 `tasks.status` 自己就能当队列】

因为它已经有 `ix_tasks_status_queued_at` 这条索引（B1 就建好了，
当时的注释写的就是「worker 扫『该提交的』和『该轮询的』」）。
出队 = 一条带顺序的 SELECT，入队 = 一次状态更新，
而且**任务状态永不落在进程内存里**（铁律）—— 它本来就在库里。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import TaskKind, TaskStatus
from app.models import Task
from app.types import utcnow

# ══════════════════════════════════════════════════════════════
# 顺序的唯一定义
# ══════════════════════════════════════════════════════════════
#
# ⚠️ 出队顺序（`claim_next`）和排队位次（`position_of`）**必须用同一个
#    键**，否则「前面还有 3 个」就成了一句谎话：位次按 A 排序算，
#    而真正的出队按 B 排序走，两个数对不上。
#
# 【为什么键是 (queued_at, id) 而不是 (created_at, id)】
# `created_at` 是「什么时候被创建」，`queued_at` 是「什么时候开始排队」。
# 重试退避（§7.5）是把 `queued_at` 推到未来实现的，所以只有
# `queued_at` 能表达「这个任务现在排在哪里」。用 `created_at` 的话，
# 一个退避到 30 秒后的重试任务会**永远排在最前面** —— 每轮都被捞起来、
# 每轮都被退避推开，变成一次空转的忙等。
#
# 带上 `id` 是为同微秒建的多个任务提供稳定次序（和流水那边同一个理由）。
#
# ⚠️ 两处都把 `queued_at` 当**非空**用。它在 `status == queued` 时确实
#    必然非空（`enqueue` 是唯一入口，见那里的说明）；真出现 NULL 的话，
#    `queued_at <= now` 会把这条任务排除在外 —— 表现是「有一条任务永远
#    卡在排队中」。这正是 `enqueue` 那段「不许在别处直接改 status」的
#    理由，也是 `tests/test_queue_b3.py` 里那条用例要守的东西。


# ══════════════════════════════════════════════════════════════
# 状态迁移（pending → queued → submitted）
# ══════════════════════════════════════════════════════════════


def enqueue(session: Session, task: Task, now: datetime | None = None) -> None:
    """`pending → queued`。**入队的唯一入口。**

    【为什么不许在别处直接写 `task.status = queued`】因为 `queued_at`
    必须同时被写上 —— 它是出队顺序的键。只改状态不写时间的代码**能跑**：
    任务照样会出队（`queued_at` 为 NULL 时排在最前），只是它插到了
    所有人前面。这种 bug 的表现是「有人被插队」，而没有任何报错。
    """
    task.status = TaskStatus.queued
    task.queued_at = now or utcnow()


def mark_submitted(
    session: Session, task: Task, *, provider_task_id: str | None, now: datetime | None = None
) -> None:
    """`queued → submitted`：已经交给 provider 了，正在等。"""
    task.status = TaskStatus.submitted
    task.submitted_at = now or utcnow()
    if provider_task_id is not None:
        task.provider_task_id = provider_task_id


def requeue_for_retry(session: Session, task: Task, *, now: datetime | None = None) -> float:
    """§7.5 的指数退避：**退回队列，但把 `queued_at` 推到未来**。返回等了多少秒。

    ─────────────────────────────────────────────────────────
    【为什么不 `time.sleep(backoff)`】

    因为 worker 是**单线程**的。sleep 5 秒 = 这 5 秒里全平台的任务
    一条都出不了队，包括那些本来好好的。退避的语义是「**这一个**
    任务晚点再试」，不是「整条流水线停 5 秒」。

    把 `queued_at` 推到未来正好表达前者，而且它**自动落库**：
    进程重启了退避也还在，不像内存里的定时器一重启就复位。

    ⚠️ 代价：`queued_at` 在这里不再是「第一次入队的时间」，
      而是「下次可以出队的时间」。所以它**不能**用来做「这个任务
      等了多久」的统计 —— 那个要另外记（目前没这个需求）。

    【退避秒数为什么在这里算、而不是让调用方传进来】因为调用方传的
    是「我想退避多久」，而这里要的是「第几次重试该等多久」——
    后者是本文件的事（`retry_backoff_sec`）。让调用方自己算，
    就是把这个策略复制到每一个调用点，而它们会分岔。
    ─────────────────────────────────────────────────────────
    """
    task.retry_count += 1
    task.status = TaskStatus.queued
    task.provider_task_id = None
        # 【为什么要清掉】上一次提交的那个句柄已经作废了。留着的话，
        # 轮询那一轮会拿着一个作废的 id 去问 provider —— 得到的
        # 最坏结果不是「查不到」，而是**查到了另一个任务的产物**。
    backoff = retry_backoff_sec(task.retry_count)
    task.queued_at = (now or utcnow()) + timedelta(seconds=backoff)
    return backoff


def retry_backoff_sec(retry_count: int) -> float:
    """第 `retry_count` 次重试该等多久（`retry_count` 从 1 开始数）。

    §7.5：「指数退避且设上限」。上限不是可选项 —— 没有它，
    `provider_max_retries` 调到 10 的时候第 10 次重试要等 8 分钟，
    而写那个配置的人以为自己在做一件小事。
    """
    settings = get_settings()
    return min(
        settings.worker_retry_backoff_sec * (2 ** max(retry_count - 1, 0)),
        settings.worker_retry_max_backoff_sec,
    )


# ══════════════════════════════════════════════════════════════
# 出队闸门（§8.1 的严格信号量）
# ══════════════════════════════════════════════════════════════


def claimed_count(session: Session, kind: TaskKind) -> int:
    """**全局**「已经交给 provider、还没回来」的任务数（按类）。

    【为什么是全局而不是每个用户各算各的】§8.1：即梦的并发是
    **平台整体共享**的，10 个用户各开 1 个任务就是 10 个并发，
    照样被限流。所以这道闸必须跨用户。逐用户的闸在
    `generation._check_quota` 里，那是另一回事（§7.5 的入口闸）。
    """
    return session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.kind == kind, Task.status == TaskStatus.submitted)
    ) or 0


def has_free_slot(session: Session, kind: TaskKind) -> bool:
    """出队闸门还有没有空位。"""
    return claimed_count(session, kind) < get_settings().provider_max_concurrency


# ══════════════════════════════════════════════════════════════
# 取下一个
# ══════════════════════════════════════════════════════════════


def claim_next(session: Session, kind: TaskKind, now: datetime | None = None) -> Task | None:
    """按 `(queued_at, id)` 取队首的 `queued` 任务，没有就 `None`。

    ─────────────────────────────────────────────────────────
    【§8.2 的「轮转调度」为什么不用单独实现】

    因为 **`_check_quota` 已经把轮转变成了 FIFO 的必然结果**：
    它限制「每个用户同类的**活跃**任务 ≤ 1」，而 `queued` 算活跃 ——
    于是队列里**每个用户每类最多只占一个位子**。既然每个用户
    至多一个，那么「按 `queued_at` 先进先出」和「用户之间轮流」
    就是同一件事，不需要游标、也不需要窗口函数。

    ⚠️ **这个等价关系是有前提的，改 `max_concurrent_tasks` 时要想清楚**：
      把它调到 2，同一个用户就能有两个排队任务，FIFO 立刻不再是轮转，
      一个连点两次的用户会连占两轮。届时要么补真正的轮转排序
      （`ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY queued_at)`），
      要么承认「不做轮转」。`tests/test_queue_b3.py` 里有一条用例
      钉着这个前提。

    【为什么 `queued_at <= now` 这个条件不能省】它就是退避的实现 ——
    见 `requeue_for_retry`。少了它，被退避推开的任务下一轮立刻又被
    捞起来，退避形同虚设。
    ─────────────────────────────────────────────────────────
    """
    moment = now or utcnow()
    return session.scalars(
        select(Task)
        .where(Task.kind == kind, Task.status == TaskStatus.queued, Task.queued_at <= moment)
        .order_by(Task.queued_at.asc(), Task.id.asc())
        .limit(1)
    ).first()


# ══════════════════════════════════════════════════════════════
# 排队位次
# ══════════════════════════════════════════════════════════════


def position_of(session: Session, task: Task) -> int | None:
    """排队位次。§8.2：诚实显示位次，**不做假进度条**。

    ─────────────────────────────────────────────────────────
    【为什么不是 queued 就返回 None，而不是返回 0】

    只有排队中才有「前面还有几个」可言。已经 submitted 的任务前面
    没有任何人 —— 但那时显示「前面还有 0 个」是**错的**：用户会以为
    马上出结果，其实还要等好几分钟。返回 null 让 UI 干脆不显示这一行。

    【为什么在同类里数、而且不按用户过滤】§8.2：图与视频**分开计数**
    （否则图片会被视频饿死）。而真 provider 是全局单队列，
    「前面还有几个」问的是整条队列 —— 这也是 Mock 的做法。

    【为什么排序键必须和 `claim_next` 一模一样】见本文件顶部那一段。
    这里用 `(queued_at, id)` 逐字对上 `claim_next` 的 `ORDER BY`，
    所以「前面还有 2 个」和「下一轮捞的不是我」永远同时成立。

    【为什么写成 SQL 而不是「取回全部再在 Python 里数」】因为这段
    每读一次任务就要跑一次（`/tasks` 列表是逐条算位次的）。取回全部
    在队列短的时候没差别，在「有 500 条排队」的时候就是每次列表请求
    都拉 500 行。这里用 `(a, b) < (x, y)` 展开成的 OR 形式 ——
    它和 ORDER BY 是同一件事，只是换了个方向问。
    ─────────────────────────────────────────────────────────
    """
    if task.status is not TaskStatus.queued or task.queued_at is None:
        return None

    ahead = session.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.kind == task.kind,
            Task.status == TaskStatus.queued,
            Task.id != task.id,
            (Task.queued_at < task.queued_at)
            | ((Task.queued_at == task.queued_at) & (Task.id < task.id)),
        )
    )
    return (ahead or 0) + 1
