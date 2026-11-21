"""worker —— §8.3 的一轮、两个入口的分工、以及「谁把任务推到终态」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件测的都是「跨时间」的东西】

B2 里 `submit` 一次走完全程，所以「任务什么时候变成 succeeded」这个
问题没有第二个人回答。B3 之后有两个人：**请求路径**（provider 当场
给结果）和 **worker**（排队出队 + 轮询）。这个文件盯的就是后者。

【为什么一次都不 sleep】

`run_once(now=...)` 的 `now` 是参数，所以「等 10 分钟」「退避 4 秒」
全都是把时间戳往前拨。真 sleep 的话，跑一遍测试要几分钟，
而且时间一到就 flaky（CI 上机器慢一点就红）。

【为什么不用后台线程】

`run_forever` / `start_background` 是**调度**，`run_once` 才是**逻辑**。
线程里跑逻辑的测试要么要 sleep 好几秒、要么要 join 超时，
两种都不稳定。这里只测 `run_once`，外加一小段 `_start_worker`
的开关（它决定线程起不起，本身不跑逻辑）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from _helpers import new_user, submit_image
from _providers import ScriptedProvider
from app import worker
from app.main import _start_worker
from app.enums import TaskStatus
from app.models import Task
from app.providers import ProviderFailure
from app.types import utcnow


@pytest.fixture(autouse=True)
def _clean_poll_schedule() -> None:
    """每一轮用例开始前忘掉「上一轮问过 provider」。

    ─────────────────────────────────────────────────────────
    【为什么必须 autouse】

    `worker._last_poll_round` 是**模块级全局**，而它的语义是
    「进程内上一次问 provider 是什么时候」。测试进程是共享的，
    所以上一条用例留下的时间戳会让这一条用例的 poll 被**静默跳过** ——
    表现是「断言 `report.advanced == [id]` 失败，而代码是对的」。

    这类失败最难查：单独跑这条用例是绿的，跑整个文件就红。
    夹具兜掉它，用例里就不必记得手动重置。
    ─────────────────────────────────────────────────────────
    """
    worker.reset_poll_schedule()


async def _me(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    return (await api.get("/me", headers=headers)).json()["credit_account"]


def _task_row(session: Session, task_id: int) -> Task:
    """**另开一个会话**读任务当前的样子。

    【为什么不能直接用 `api_session` 里那个对象】因为 worker 在
    自己的事务里改了这一行。同一个会话里那个已经加载过的 ORM 对象
    可能带着旧值（`expire_on_commit=False`），于是断言读到的是
    「worker 动手之前」的状态 —— 一条永远绿的用例。
    """
    session.expire_all()
    task = session.get(Task, task_id)
    assert task is not None, f"任务 {task_id} 不见了"
    return task


# ══════════════════════════════════════════════════════════════
# 一轮里的顺序（§8.3 职责 ①②③④）
# ══════════════════════════════════════════════════════════════


async def test_一轮里先问进度再出队_空出的位子当轮就用上(
    api: httpx.AsyncClient, api_session: Session, instant_scripted: ScriptedProvider
) -> None:
    """A 完成 → B 在**同一轮**被出队，而不是白等 2 秒。

    ─────────────────────────────────────────────────────────
    【为什么这一条值得单独写】

    因为「先问进度、再出队」这个顺序是有代价的：它看起来只是
    `run_once` 里两行的位置。但反过来写（先出队后问进度）**不会**
    让任何功能失效 —— 任务照样会完成，余额照样对，所有别的用例
    照样绿。它只是让吞吐变差：闸门只有 1 个位子，每完成一条就
    白等一轮（2 秒）。一天下来这是几百次没必要的空转。

    这种「只影响性能、不影响正确性」的顺序，恰恰是最容易在某个
    重构里被无声无息调换的。所以要有一条用例钉着它。

    【为什么这里的替身是 `instant_scripted`】因为它第一次 `poll`
    就返回成品 —— 「A 完成」必须发生在**这一轮之内**，否则
    「空出的位子在当轮被用上」这件事根本不存在。
    ─────────────────────────────────────────────────────────
    """
    a_h, _ = await new_user(api, "alice")
    b_h, _ = await new_user(api, "bob")

    a_task = (await submit_image(api, a_h, idempotency_key="a1")).json()
    b_task = (await submit_image(api, b_h, idempotency_key="b1")).json()
    assert a_task["status"] == "submitted"   # 占着唯一的闸门位
    assert b_task["status"] == "queued"      # 排在后面

    report = worker.run_once(api_session, now=utcnow())

    assert report.polled, "这一轮没问 provider"
    assert report.advanced == [a_task["id"]]
        # 先问进度：A 完成，闸门位空出来。
    assert report.dispatched == [b_task["id"]]
        # 再出队：B 当轮就用上了那一位 —— 不是下一轮。

    assert _task_row(api_session, a_task["id"]).status is TaskStatus.succeeded
    assert _task_row(api_session, b_task["id"]).status is TaskStatus.submitted
        # B 只是被**交出去**了（替身给的是回执），还没完成。


async def test_第一次问就有结果_就在那一轮结算(
    api: httpx.AsyncClient, api_session: Session, instant_scripted: ScriptedProvider
) -> None:
    """真 provider 的异步回执 + worker 轮询，最终落到和前一条路一样的账。

    【它和 `test_queue_b3` 里那条「提交即完成一个字都没变」是一对】
    那条走的是**请求路径**收尾（fake：provider 当场给结果），
    这条走的是 **worker** 收尾（异步 provider：要问一次才有）。
    两条路的**终点必须一模一样** —— 余额 46、`settled_amount` 4、
    `frozen` 0。有差异就说明收尾逻辑分岔了，而那正是 B3 要防的事。
    """
    headers, _ = await new_user(api, "alice")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()

    worker.run_once(api_session, now=utcnow())

    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.succeeded
    assert row.settled_amount == 4
    assert row.queued_at and row.submitted_at and row.finished_at

    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (46, 0)


async def test_问provider的节奏由provider_poll_interval节制(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """worker 每 2 秒巡一次，但不该每 2 秒都去问 provider。

    ─────────────────────────────────────────────────────────
    【为什么两个间隔必须分开】

    `worker_poll_interval_sec` = 2 秒，`provider_poll_interval_sec` = 10 秒。
    一条视频本来就要跑十分钟，2 秒问一次等于对即梦的接口做压力测试 ——
    而 §8.1 里那个「平台共享的并发 1–2」说的是**提交**，端口被人
    这么刷一遍的结果是整个平台被限流。

    反过来也不能只留一个长间隔：出队要快（用户点了生成，2 秒内
    就该被交出去），问进度要慢。所以是两个数。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "alice")
    await submit_image(api, headers, idempotency_key="k1")

    t0 = utcnow()
    assert worker.run_once(api_session, now=t0).polled is True
    assert scripted.poll_count == 1

    # 3 秒后：还在 10 秒的窗口里 —— 巡了一轮，但没问 provider。
    assert worker.run_once(api_session, now=t0 + timedelta(seconds=3)).polled is False
    assert scripted.poll_count == 1, "10 秒没到就问了一次，即梦会被刷爆"

    # 11 秒后：窗口过了，该问了。
    assert worker.run_once(api_session, now=t0 + timedelta(seconds=11)).polled is True
    assert scripted.poll_count == 2


# ══════════════════════════════════════════════════════════════
# 失败的三条去向（§7.5）
# ══════════════════════════════════════════════════════════════


async def test_可重试的失败_退回队列并退避(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """限流/5xx 这类失败 → 退回队列、退避后再来。**不是** `failed`。

    ─────────────────────────────────────────────────────────
    【为什么退避的断言要看 `queued_at` 是未来时间，而不是看 sleep】

    因为退避就是「把 `queued_at` 推到未来」实现的（见
    `services/queue.py` 的 `requeue_for_retry`）。这条断言同时钉住两件事：
    退避真的发生了，而且它**没有**用 `time.sleep` 阻塞 worker ——
    后者在一个单线程 worker 里等于「全平台停摆 2 秒」。

    【为什么要断言 `submit_count == 2`】
    只看最终状态的话，一个**根本没重试**、只是被别的东西推进到
    成功的实现也能绿。只有「provider 真的又被调了一次」才证明重试。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "alice")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()
    assert scripted.submit_count == 1

    scripted.poll_failure = ProviderFailure("上游 503", code="PROVIDER_5XX", retryable=True)

    t0 = utcnow()
    report = worker.run_once(api_session, now=t0)
    assert report.advanced == [task["id"]]

    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.queued
    assert row.error_code == "PROVIDER_5XX"
    assert row.retry_count == 1
    assert row.provider_task_id is None
        # 上一次那个句柄已经作废，留着会用错。
    assert row.queued_at > t0
        # 退避 = `queued_at` 在未来。

    # 退避没到点：这一轮不该把它捞出来。
    assert worker.run_once(api_session, now=t0).dispatched == []

    # 钱还冻着 —— 重试中的任务不是失败任务，用户不该看到它退款。
    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 4)

    # 退避到点了，而且上游也好了。
    scripted.poll_failure = None
    later = worker.run_once(api_session, now=t0 + timedelta(seconds=30))
    assert later.dispatched == [task["id"]]
    assert scripted.submit_count == 2, "没有真的再提交一次，这不叫重试"

    assert _task_row(api_session, task["id"]).status is TaskStatus.submitted


async def test_审核不通过_判rejected而不是failed_并且全额退回(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """内容审核失败 → `rejected` + 全额退回。**绝不重试。**

    ─────────────────────────────────────────────────────────
    【为什么 `rejected` 不能是「一种 failed」】

    §12.3 对这两个码给的前端行为完全不同：`CONTENT_REJECTED`(422)
    要用户**改写提示词**，`PROVIDER_ERROR`(502) 是**可重试**。
    把审核失败记成 `failed` 的话，用户会一直点重试，而每一次
    重试都会拿到同一个结果 —— 白白花掉他的次数，还留下一串
    毫无信息量的失败记录。

    【为什么原始码 `50411` 要留在任务上】它是**排查的唯一线索**。
    provider 判违规和平台判违规不是一回事，用户申诉时要有原始结论。
    平台的契约码由 `status` 表达，provider 的原始码由 `error_code`
    表达 —— 两件事，两个字段，不要混。
    【`settled_amount` 保持 NULL】失败任务不是「结算了 0 积分」。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "alice")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()

    scripted.poll_failure = ProviderFailure(
        "输入包含违规内容", code="50411", retryable=False, rejected=True
    )

    report = worker.run_once(api_session, now=utcnow())
    assert report.advanced == [task["id"]]

    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.rejected
    assert row.status is not TaskStatus.failed
    assert row.error_code == "50411"
    assert row.settled_amount is None
    assert row.finished_at is not None
    assert row.retry_count == 0, "审核失败不该重试"

    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 0)
        # 全额退回：50 一分没少，冻结清空。


async def test_超过时限就过期_并全额退回(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """卡住的任务到点判 `expired` + 全额退回。

    ─────────────────────────────────────────────────────────
    【这条兜底没了会怎样】

    不是「多几条失败任务」，而是**用户的积分被永久锁死**：
    provider 那边卡住不动、任务一直 `submitted`、冻结一直不释放。
    而冻结在界面上是不可见的（用户看到的是 `balance − frozen`），
    所以他的感受是「我明明还有 50 积分，为什么生成不了」——
    余额没变、没有失败任务、流水也没有异常，这类事故在账面上
    根本查不出来。

    【为什么用 `created_at` 而不是 `submitted_at` 做超时基准】
    见 `worker._expire_stale`：只有 `created_at` 在所有活跃状态下
    都有值。这条用例顺带钉住它 —— 如果基准改成 `submitted_at`，
    一条卡在 `pending` 的任务就永远不过期了。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "alice")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()

    two_hours_later = utcnow() + timedelta(hours=2)
    report = worker.run_once(api_session, now=two_hours_later)

    assert report.expired == [task["id"]]
    assert report.advanced == [], "已经判过期的任务不该再被问一次"

    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.expired
    assert row.error_code == "TASK_TIMEOUT"
    assert row.settled_amount is None

    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 0)


async def test_排队中被取消_全额退回_而且不再被出队(
    api: httpx.AsyncClient, api_session: Session, instant_scripted: ScriptedProvider
) -> None:
    """`queued` 状态下取消 = 全额退回。这是 B3 才真的可达的路径。

    ─────────────────────────────────────────────────────────
    【B2 里这个分支永远走不到】

    B2 的 fake「提交即完成」，所以任务在提交那一刻就已经是终态，
    取消只会拿到 `TASK_NOT_CANCELABLE`。B3 把 `queued` 变成一段
    **真的会持续一段时间**的状态之后，「排队中取消」第一次有了实际
    意义 —— 而它对应的正是 §7.4 里那条「还没交出去就不该收钱」。

    【为什么替身必须是 `instant_scripted`，而且必须断言闸门真的开了】
    最后一步想验的是「已有的任务完成后，那条**已退款**的任务不会被
    补位捞走」。如果 alice 那条没完成，闸门就是满的，`dispatched`
    当然是空的 —— 用例会**因为完全无关的原因**变绿，而它想守的
    那条（`claim_next` 有没有过滤状态）一个字都没验到。
    所以这里先断言 `report.advanced == [alice_id]`：闸门确实空出来了，
    紧接着 `dispatched` 仍然为空才是「那条取消掉的任务没被捞」。
    ─────────────────────────────────────────────────────────
    """
    a_h, _ = await new_user(api, "alice")
    b_h, _ = await new_user(api, "bob")

    a_task = (await submit_image(api, a_h, idempotency_key="a1")).json()  # 占住闸门
    queued = (await submit_image(api, b_h, idempotency_key="b1")).json()
    assert queued["status"] == "queued"

    canceled = await api.post(f"/tasks/{queued['id']}/cancel", headers=b_h)
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"

    account = await _me(api, b_h)
    assert (account["balance"], account["frozen"]) == (50, 0)

    report = worker.run_once(api_session, now=utcnow())

    assert report.advanced == [a_task["id"]]
        # alice 那条完成了 —— 闸门**真的**空出来了。
    assert report.dispatched == [], "已经退款的任务被重新生成了一次"
    assert _task_row(api_session, queued["id"]).status is TaskStatus.canceled


# ══════════════════════════════════════════════════════════════
# 起不起后台线程（这一小段不跑逻辑，只测开关）
# ══════════════════════════════════════════════════════════════


def _start_worker_settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    """按给定的环境变量造一份 settings。

    【为什么连 `_start_worker` 也值得测】因为它是一个**只在生命周期
    回调里被调用**的函数，而它错了的表现分别是「测试跑着跑着库被清了」
    和「生产环境队列永远不动」—— 两种都不会在单测里自然暴露。
    """
    from app.config import get_settings

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


def _record_start(monkeypatch: pytest.MonkeyPatch, started: list[str]) -> None:
    """把 `start_background` 换成一个只记账的替身。

    【为什么要记账而不是真起线程】真起的话，它会按
    `worker_poll_interval_sec` 一直巡到进程结束，打的是**测试库**。
    它不影响这几条断言，但会让别的用例偶发地看到「有东西在改我的
    数据」—— 那种失败极难定位。

    【为什么替身要有返回值】因为 `_start_worker` 的返回值就是
    `start_background()` 的返回值（`lifespan` 靠它拿 stop 开关）。
    写成 `lambda: started.append(1)` 的话返回的是 `None`，
    于是「起来了」和「没起来」在断言里长得一样 —— 用例就骗了自己。
    """
    def fake_start() -> str:
        started.append("started")
        return "stop-开关"

    monkeypatch.setattr("app.worker.start_background", fake_start)


def test_TESTMODE下不启动worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TEST_MODE=1` → 不起 worker 线程。

    ─────────────────────────────────────────────────────────
    【为什么这条是硬要求，不是优化】

    `TEST_MODE` 下 `/__test/reset` 会 `drop_all` + `create_all`。
    后台 worker 同时在跑的话，它会拿着一个**正在被删的表**做查询 ——
    B2b 那批就撞过一次，报出来的错是「no such table: tasks」，
    看起来像迁移漏了，其实是清库和 worker 抢表。

    所以这里宁可不启动：测试要跑 worker，就显式调 `run_once`。
    ─────────────────────────────────────────────────────────
    """
    from app.config import get_settings

    started: list[str] = []
    _record_start(monkeypatch, started)
    try:
        settings = _start_worker_settings(monkeypatch, TEST_MODE="1", WORKER_ENABLED="1")
        assert _start_worker(settings) is None
        assert started == [], "TEST_MODE=1 时还是把 worker 线程起了起来"
    finally:
        get_settings.cache_clear()


def test_开关关掉时不启动worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WORKER_ENABLED=0` → 不起；开着 → 起（且只靠生命周期回调起）。

    【为什么「开着」那一半也要断言】否则这个函数写成
    `return None` 也能过全部测试，而队列在真实部署里永远不动 ——
    一个「任务提交成功、状态永远停在 queued」的平台，
    用户看到的是「一直在排队」，而我们没有任何一条测试会红。
    """
    from app.config import get_settings

    started: list[str] = []
    _record_start(monkeypatch, started)
    try:
        off = _start_worker_settings(monkeypatch, TEST_MODE="0", WORKER_ENABLED="0")
        assert _start_worker(off) is None
        assert started == []

        on = _start_worker_settings(monkeypatch, TEST_MODE="0", WORKER_ENABLED="1")
        assert _start_worker(on) == "stop-开关"
        assert started == ["started"]
    finally:
        get_settings.cache_clear()
