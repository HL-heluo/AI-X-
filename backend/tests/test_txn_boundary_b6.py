"""事务边界（B6）—— 搬产物那一段时间里，**别的连接能不能碰库**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件为什么存在】

B6 把 worker 路径上的转存 IO 从「夹在事务中间」挪到了事务外
（`generation.perform_transfer` 的签名里连 `Session` 都没有）。
理由是 OSS 上传是 20MB 过公网，而 SQLite 只有一个写者 ——
IO 夹在事务里的话，那段时间全平台一条任务都写不进库。

这件事**没有任何功能测试能证明**：把 IO 放回事务里，所有别的
用例照样绿，任务照样成功，余额照样对。只有一条专门盯着
「IO 进行到一半时，库从外面看是什么样」的用例才看得见它。

⚠️ **别把它改写成「另一个连接能写库」那一版** —— 见下面那段
    关于「假绿」的说明。那条断言在两种写法下**都是绿的**。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from _helpers import new_user, submit_image
from _providers import ScriptedProvider
from app import worker
from app.database import get_session_factory
from app.enums import TaskStatus, TransferState
from app.models import Task
from app.services import generation
from app.types import utcnow


@pytest.fixture(autouse=True)
def _clean_poll_schedule() -> None:
    """忘掉「上一轮问过 provider」。理由同 `test_worker_b3.py` 里那条。

    `_last_poll_round` 是模块级全局，上一条用例留下的时间戳会让
    这一条的 ② 相位被**静默跳过** —— 于是搬运永远不会发生，
    而这条用例会以「worker 没走到搬运那一步」的形式红掉。
    """
    worker.reset_poll_schedule()


async def test_搬运期间另一个连接看得见已落库的认领(
    api: httpx.AsyncClient,
    api_session: Session,
    instant_scripted: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker 走到「搬产物」这一步时，**库里已经能看到这条认领**。

    ─────────────────────────────────────────────────────────
    【这条用例钉的是什么】

    `finish_succeeded(defer_io=True)` 只登记 `transfer_state = running`
    就返回，**让调用方先提交**，真正搬字节的活留给 ②.5 相位。
    所以「搬运进行中」这一刻，从另一个连接去看那条任务，应该看到：

      · `transfer_state == running`（认领已落库，是一条**待办**）
      · `provider_url` 非空（要搬谁，也落库了）

    而把 `defer_io` 去掉（IO 回到事务里）之后，这一刻库里的
    还是**认领之前**的样子（`none` + `provider_url` 为空）——
    因为那些改动全在 worker 那个还没提交的事务里。用例当场变红。

    【为什么这件事值得一条用例】（两条理由，都不是洁癖）

      1. **它是「进程死在搬运中途」的兜底所依赖的东西。** 落库的
         `running` 才是下一轮 worker 把活捡回来的依据；只在内存里的
         `running` 随进程一起消失，那条任务会一直停在 `submitted`
         直到一小时超时。
      2. **它把 B6 的修改钉在一个可观测的行为上**，而不是「读代码
         确认它挪出去了」。两次改动各写各的事务边界，是 B3/B4 已经
         吃过一次亏的形态（两边都绿，合起来错）。

    ─────────────────────────────────────────────────────────
    【⚠️ 这个文件里没有的一条断言，以及为什么】

    直觉上更该断言的是「搬运期间另一个连接**能写库**」，因为
    B6 的理由写的就是「IO 占着 SQLite 的唯一写锁」。**但那条断言是假绿**：
    实测把 `defer_io` 去掉、确认下面那条断言变红时，同一次运行里
    打出来的 `能否写库 = True，耗 0.00s` —— 也就是说把 IO 放回事务里，
    另一个连接的写**照样成功**。

    原因是 `sessionmaker(autoflush=False)`：会话直到 `commit()` 才
    发 DML，而搬运之前那几个阶段只做了 SELECT —— 于是 SQLite 层面
    **根本没有拿过写锁**（pysqlite 的隐式 BEGIN 只在一句 DML 之前发）。
    「IO 在事务里」这件事在**有东西被 flush 之后**才有代价，
    在这个代码路径上恰好没有。

    所以：那条断言**两种写法都能过**，它证明不了任何东西。
    真正的判据只能是上面那两条（认领落库没有）。留着这段说明，
    是为了下一个人不要「顺手把它补上」，然后以为覆盖到了。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "alice")
    submitted = (await submit_image(api, headers, idempotency_key="k1")).json()
    task_id = submitted["id"]
    # 【为什么这里必须是 `submitted` 而不是 `queued`】闸门有空位，
    # 请求路径当场就把回执交出去了 —— 这一条用例要的是
    # 「worker 在 ② 相位轮询到成品」，所以它得先处在这个状态。
    assert submitted["status"] == "submitted"

    # ── 把「搬字节」换成一个可以卡住的版本 ────────────────────
    io_started = threading.Event()
    io_release = threading.Event()
    real_transfer = generation.transfer_artifact
        # ⚠️ 必须在打补丁**之前**取下来，否则拿到的是自己。

    def slow_transfer(*, task_id: int, kind, provider_url: str):
        io_started.set()
        if not io_release.wait(timeout=30):
            raise AssertionError(
                "用例自己坏了：搬运一直没被放行（断言失败时也会走到这里，"
                "所以这条消息不代表被测代码有问题）"
            )
        return real_transfer(task_id=task_id, kind=kind, provider_url=provider_url)

    monkeypatch.setattr(generation, "transfer_artifact", slow_transfer)

    # ── 让 worker 跑在一轮里，并在搬运那一步卡住 ───────────────
    box: dict[str, object] = {}

    def drive() -> None:
        box["report"] = worker.run_once(api_session, now=utcnow())

    tick = threading.Thread(target=drive, daemon=True)
    tick.start()
    try:
        assert io_started.wait(timeout=30), "worker 没有走到搬运那一步"

        # ── 此刻：worker 正卡在搬运里，IO 还没做完 ────────────
        seen = _peek(task_id)
        wrote, elapsed = _try_write()

        assert seen.transfer_state is TransferState.running, (
            "搬运进行中，库里却看不到 `running` —— "
            "说明认领是跟在 IO 后面一起提交的（`defer_io` 被去掉了），"
            f"看到的是 {seen.transfer_state}（同时：另一个连接能否写库 = "
            f"{wrote}，耗 {elapsed:.2f}s —— 这两项在两种写法下都一样，"
            "留在这里是为了让「假绿」这件事有一次当场可见的证据）"
        )
        assert seen.provider_url, "搬运进行中，`provider_url` 还没落库"
        assert seen.status is TaskStatus.submitted

        # 【这一条是**顺带**的，不是判据】它证明此刻没有写锁挡着 ——
        # 而它在「IO 放回事务里」的写法下**同样会绿**（理由见文件头）。
        # 留着它是因为它能抓另一类改动：哪天有人为了「省一次 commit」
        # 把整个 ②.5 包进 IO 之外的事务里，写锁就真的被握住了。
        assert wrote, "搬运期间另一个连接写不进去"
        assert elapsed < 1.0, (
            f"另一个连接的写等了 {elapsed:.2f}s —— 有人在搬运期间握着写锁"
        )
        # 注：上面两条**先**跑，于是它们失败时下面那条不会执行；
        # 反过来（下面先红）时，它们的结果会被打进下面那条的消息里
        # —— 那正是「它不区分两种写法」的证据。
    finally:
        # 【为什么放行与 join 必须在 finally 里】断言失败时线程还卡在
        # `io_release` 上；不叫醒它，worker 那个会话就一直攥着连接，
        # 而 `api_session` 是 fixture 管的 —— 收尾时的 dispose 会卡住，
        # 报出来的错和真正失败的断言毫无关系。
        io_release.set()
        tick.join(timeout=30)

    assert not tick.is_alive(), "worker 线程没有在放行后结束"

    report = box["report"]
    # ── 收尾：同一条任务在**同一轮**里被 ② 认领、被 ②.5 搬完 ────
    assert report.advanced == [task_id]
    assert report.retried == [task_id]
    after = _peek(task_id)
    assert after.status is TaskStatus.succeeded
    assert after.transfer_state is TransferState.done
    # 【为什么 `provider_url` 要在落定后清掉】它是 provider 给的、带签名的
    # 地址，留在库里等于把一份会过期的凭据长期存着；而它的用途
    # （重试搬运）在 `transfer_state = done` 之后就不存在了。
    assert after.provider_url is None


# ══════════════════════════════════════════════════════════════
# 从**另一个连接**看这个库
# ══════════════════════════════════════════════════════════════
#
# 【为什么不能直接用 `api_session`】它是 worker 正在用的那个会话。
# 同一个会话里的 ORM 对象带着缓存（`expire_on_commit=False`），
# 读到的会是「worker 动手之前」的样子 —— 一条永远绿的用例。
# 而且会话不是线程安全的：主线程在 worker 线程跑着的时候去读它，
# 是在拿两个线程共用一个对象。
#
# 【为什么另开一个会话 = 另开一个连接】引擎用 `NullPool`，
# 每次签出都是新连接。这正是「另一个连接看得见什么」这件事的前提。


def _peek(task_id: int):
    with get_session_factory()() as s:
        return s.execute(
            select(Task.transfer_state, Task.status, Task.provider_url).where(Task.id == task_id)
        ).one()


def _try_write() -> tuple[bool, float]:
    """试着写一句无关紧要的 DML，返回 `(写成功了吗, 花了多久)`。

    ─────────────────────────────────────────────────────────
    【为什么是 `updated_at = updated_at` 这种空写】

    因为它**不改任何数据**（跑多少次库里的内容都一样），却仍然要走
    一次真正的写路径 —— 写锁、journal、commit 一个不少。
    换成「插一行再删掉」的话，断言失败时留下的垃圾会让下一条
    奇怪的用例红，而那条用例看起来和被测代码有关。
    ─────────────────────────────────────────────────────────
    """
    started = time.perf_counter()
    try:
        with get_session_factory()() as s:
            s.execute(
                text("UPDATE users SET updated_at = updated_at WHERE id = :uid"),
                {"uid": 1},
            )
            s.commit()
    except Exception:  # noqa: BLE001 —— 被挡住就是这条用例要说的事
        return False, time.perf_counter() - started
    return True, time.perf_counter() - started


# ══════════════════════════════════════════════════════════════
# 顺带钉住的两件小事（都跟边界有关，但不需要跑 worker）
# ══════════════════════════════════════════════════════════════


def test_搬运函数不接会话() -> None:
    """`perform_transfer` 的签名里**不能**出现 `Session`。

    ─────────────────────────────────────────────────────────
    【为什么值得一条用例】因为「顺手查一下库」是这段代码最容易
    发生的退化：搬运失败时想记一笔、想把 provider 的响应存下来 ——
    任一情况下都会有人给它加个 `session=` 参数，而那时候
    IO 又回到了事务里，**其它所有用例照样绿**。
    加参数的人会看见这条用例红，而不是在几个月后从
    「偶发地一切都很慢」里把它挖出来。
    ─────────────────────────────────────────────────────────
    """
    import inspect

    params = inspect.signature(generation.perform_transfer).parameters
    assert not [name for name in params if "session" in name.lower()], (
        f"`perform_transfer` 又接上会话了：{list(params)} —— "
        "它的全部价值就在于「跑多久都不碰库」"
    )


def test_同步路径仍然把_io_留在事务里() -> None:
    """`finish_succeeded` 的 `defer_io` **默认是 False**。

    ─────────────────────────────────────────────────────────
    【为什么默认值本身是要紧的】

    同步路径（`submit` → `dispatch(sync=True)`）靠「IO 在外层事务里
    被回滚」实现「被拒的提交不留痕」，而 `TEST_MODE=1`（跨仓门禁的
    配置）不起 worker —— 那种提交一旦变成「200 + 一条永远 `submitted`
    的任务」，它永远好不了。

    真正的契约由 `test_transfer_b4.py::test_同步路径的转存失败_502_而且一整笔都不留`
    钉着。这里只钉默认值：哪天有人把默认改成 `True`「让两条路统一」，
    那条用例会跟着红，而这条会**先**红 —— 报出来的位置更接近病因。
    ─────────────────────────────────────────────────────────
    """
    import inspect

    default = inspect.signature(generation.finish_succeeded).parameters["defer_io"].default
    assert default is False, "同步路径的默认值被改成了 True —— 见这条用例的说明"
