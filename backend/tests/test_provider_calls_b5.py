"""`provider_calls` 对账 —— §11.1 的写入侧。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这张表 B1 就建好了，到 B5 之前一行都没被写过】

所以这个文件的第一件事不是「字段对不对」，而是**它到底写不写得进去**，
尤其是在**最该写进去的那一次**：我们打了接口、对方拒了、
而我们因为回滚没有留下任何业务痕迹的那一次。

`generation.submit` 把整件事包在 `atomic()` 里 —— 被拒的提交会让
任务行、冻结、流水一起回滚。同事务插的审计行会跟着消失。所以
这一整条路的设计（事务外、独立连接、best-effort）就是为了那个
**回滚之后的调用**还留得下来。

【因此本文件最要紧的两条是互相矛盾的，而它们都要成立】

  · 回滚掉的那次调用**要**留下审计行（`task_id` 是 NULL）；
  · 审计子系统坏掉**不许**影响生成。

一条测的是「它记得住」，另一条测的是「它不重要到能拖垮主流程」。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from _helpers import new_user, submit_image, submit_video
from app import worker
from app.enums import TaskStatus
from app.models import CreditLedger, ProviderCall, Task
from app.services.provider_audit import CallAudit, PendingCall, sanitize_message
from app.types import utcnow

# provider 侧的两个触发词。**从实现里读**，不在这里手抄 ——
# 抄一遍的话，改了那边这里就变成「一个凑巧不在词表里的普通提示词」，
# 于是这一整个文件会从「验失败路径」悄悄变成「验成功路径」。
from app.providers.fake import FAIL_SENTINEL, RETRY_SENTINEL


@pytest.fixture(autouse=True)
def _clean_poll_schedule() -> None:
    """`worker._last_poll_round` 是模块级全局，不清会让轮询被静默跳过。"""
    worker.reset_poll_schedule()


def _calls(session: Session) -> list[ProviderCall]:
    return list(session.scalars(select(ProviderCall).order_by(ProviderCall.id)))


async def _account(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    return (await api.get("/me", headers=headers)).json()["credit_account"]


# ══════════════════════════════════════════════════════════════
# 一、脱敏（纯单元）
# ══════════════════════════════════════════════════════════════


def test_消息里的地址被换成占位符() -> None:
    """⚠️ provider 报错常把**带签名的产物地址**原样回显。

    落进库就等于把签名存下来了，而这张表是要导出去对账的。
    `provider_url` 那条铁律（「绝不出现在任何响应里」）射程里
    包含这张表 —— 有一条不依赖时效的规则，比「记得它一小时后就没事了」
    可靠得多。
    """
    message = "download failed: https://bucket.oss-cn.aliyuncs.com/a.mp4?X-Amz-Signature=deadbeef"

    sanitized = sanitize_message(message)

    assert sanitized is not None
    assert "deadbeef" not in sanitized
    assert "<url>" in sanitized


def test_超长的消息被截断() -> None:
    """对方可以回一屏 HTML 错误页。不截的话，一次限流风暴能在
    `provider_calls` 里塞进几十 MB 的 HTML。"""
    sanitized = sanitize_message("<html>" + "x" * 5000)

    assert sanitized is not None
    assert len(sanitized) <= 200


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_空消息落成_NULL_而不是空串(bad: str | None) -> None:
    """空串和「没有消息」是两件事，别让它们在库里长得一样。"""
    assert sanitize_message(bad) is None


# ══════════════════════════════════════════════════════════════
# 二、成功路径
# ══════════════════════════════════════════════════════════════


async def test_一次成功的提交留下一行审计(api, api_session) -> None:
    headers, _ = await new_user(api, "对账的人")
    task = (await submit_image(api, headers)).json()

    rows = _calls(api_session)

    assert len(rows) == 1
    row = rows[0]
    assert row.action == "submit"
    assert row.task_id == task["id"], "审计要指对人，否则对账表里全是孤儿"
    assert row.attempt == 1
    assert row.latency_ms is not None and row.latency_ms >= 0
    # fake 不发 HTTP，所以响应侧全是 NULL —— 这是**诚实**的，
    # 不是「忘了填」：它没有响应可记。
    assert row.http_status is None
    assert row.resp_code is None
    assert row.error_kind is None


async def test_关掉审计开关就一行都不写(api, api_session, settings_env) -> None:
    settings_env(PROVIDER_CALL_AUDIT_ENABLED="0")
    headers, _ = await new_user(api, "不需要对账的人")

    assert (await submit_image(api, headers)).status_code in (200, 201)

    assert _calls(api_session) == []


# ══════════════════════════════════════════════════════════════
# 三、回滚掉的那一次 —— 这个文件存在的理由
# ══════════════════════════════════════════════════════════════


async def test_被拒的提交回滚了一切_但审计行还在(api, api_session) -> None:
    """━━ B5 的主断言 ━━

    ─────────────────────────────────────────────────────────
    【这条路上的每一件事都是故意的】

      · 任务 0 条、流水只剩注册赠送、余额回到 50 → 用户重试一次就好，
        「被拒的提交不留痕」那条契约仍然成立；
      · **审计行留下**，而且 `task_id` 是 NULL → 对账表里记着
        「我们确实打过这个接口」。

    如果审计行是在业务事务里插的，它会跟着一起回滚 —— 于是对账表里
    永远不会出现「我们打了接口、对方拒了、我们没记账」的那些调用，
    而它们恰恰是对账要抓的东西。

    【为什么 `task_id` 必须是 NULL 而不是那个已经消失的 id】
    中间件会 assign 一个 id 给 `task`（flush 过），但回滚之后那一行
    在库里不存在了。拿那个 id 去写外键，SQLite 默认**不报错**
    （`PRAGMA foreign_keys` 在每个连接上都要显式打开），于是对账表里
    会多一条指向空气的记录 —— 而它看起来完全正常。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "被拒的人")

    res = await submit_image(api, headers, prompt=f"画一只猫 {FAIL_SENTINEL}")

    assert res.status_code == 502, res.text
    assert res.json()["code"] == "PROVIDER_ERROR"
    # 用户看得见的：钱一分没少。
    account = await _account(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 0)
    assert api_session.scalar(select(func.count()).select_from(Task)) == 0
    assert api_session.scalar(select(func.count()).select_from(CreditLedger)) == 1

    # 用户看不见的：这次调用被记下来了。
    rows = _calls(api_session)
    assert len(rows) == 1, "被拒的提交没留下审计行 —— 同事务插的话就会这样"
    row = rows[0]
    assert row.task_id is None, "任务回滚了，外键必须跟着变成 NULL"
    assert row.action == "submit"
    assert row.resp_code == "PROVIDER_ERROR"
    assert row.resp_message, "失败了却不记对方说了什么，对账表就只剩一个码"


async def test_触发词不改计费_退款就是全额(api) -> None:
    """「冻结 → 失败 → 全额退款」这条路 §15.1 专门列了一段。

    【为什么它能被端到端验了】B5 之前要触发它只能等真即梦上一次真失败
    （限流、审核拒、网络断），于是这条路在跨仓门禁里从来没被走过 ——
    而「从没跑过的路一定有问题」是这个项目吃过两次亏的教训。
    """
    headers, _ = await new_user(api, "退全款的人")
    before = (await _account(api, headers))["balance"]

    res = await submit_image(api, headers, prompt=FAIL_SENTINEL)

    assert res.status_code == 502
    after = await _account(api, headers)
    assert after["balance"] == before
    assert after["frozen"] == 0


async def test_可重试的触发词走的是另一条路(api, api_session) -> None:
    """⚠️ 两个触发词**故意分成两条路**，否则总有一条走不到。

    `__RETRY__` 是可重试的：任务**不**判死，而是退回队列、退避后再来。
    于是同步请求拿到的是一个排队中的任务（200/201），而不是 502 ——
    这比给用户一个 502 然后让他自己再点一次要好，而且它**真的**在重试。

    【它和 `__FAIL__` 的差别只在 `retryable` 一个 bit 上】
    所以这一条真正钉住的是 `handle_failure` 里那个分岔 ——
    少了它，「重试预算」这件事在测试里完全看不见（§7.5 的重试纪律）。
    """
    headers, _ = await new_user(api, "再试一次的人")

    res = await submit_image(api, headers, prompt=f"画一只猫 {RETRY_SENTINEL}")

    assert res.status_code in (200, 201), res.text
    body = res.json()
    assert body["status"] == TaskStatus.queued.value, "可重试的失败该退回队列，不是判死"

    row = api_session.scalar(select(Task).where(Task.id == body["id"]))
    assert row is not None and row.retry_count == 1

    calls = _calls(api_session)
    assert [c.action for c in calls] == ["submit"]
    assert calls[0].task_id == body["id"], "这条任务活着，审计就该挂在它头上"
    assert calls[0].attempt == 1, "第一次尝试记 1（`retry_count + 1`）"


# ══════════════════════════════════════════════════════════════
# 四、worker 路径：每次 poll 都要有一行
# ══════════════════════════════════════════════════════════════


async def test_worker_每次问进度都留一行(api, api_session, scripted) -> None:
    """⚠️ `query` 是**出现次数最多**的那一类调用。

    一条视频会被问几十次，而我们按次计费 —— 少记这一类，
    对账表就只记得住「提交了几次」，而「问了即梦多少次」才是
    成本的大头。

    【为什么「还没好」的那一次也要记】它没有 `ProviderResult`、
    也没有 `ProviderFailure` —— 最容易在实现里被一个
    `if result is not None` 顺手漏掉，而它恰恰是最常见的一种。
    """
    scripted.polls_before_done = 1
    headers, _ = await new_user(api, "轮询的人")
    task = (await submit_image(api, headers)).json()
    assert task["status"] == TaskStatus.submitted.value

    t0 = utcnow()
    first = worker.run_once(api_session, now=t0, provider=scripted)
    assert first.polled is True
    assert [c.action for c in _calls(api_session)] == ["submit", "query"], "「还没好」那次没被记"
    assert _calls(api_session)[1].task_id == task["id"]

    # 过了轮询间隔再问一次 —— 这一次它带回了成品。
    later = t0 + timedelta(seconds=60)
    worker.run_once(api_session, now=later, provider=scripted)

    actions = [c.action for c in _calls(api_session)]
    assert actions == ["submit", "query", "query"], actions
    assert api_session.scalar(select(Task).where(Task.id == task["id"])).status is (
        TaskStatus.succeeded
    )


async def test_worker_出队那条路也记了_submit(api, api_session, scripted) -> None:
    """同步路径没空位时会排队，真正的那次 `submit` 发生在 worker 里。

    这是**另一处**调用了 `dispatch` 的地方 —— 汇总点的模式能覆盖它，
    但前提是那两处都传了 `audit`。漏一处的话，被漏的那条路上
    一次调用都不会被记下来，而另一条路全绿。
    """
    scripted.polls_before_done = 1
    # ── 怎么造出「排队」────────────────────────────────────────
    # 闸门是**全局**的（§8.1：即梦的并发是平台共享的），但
    # `max_concurrent_tasks` 是**每个用户**的。所以一个用户塞不进
    # 两条并发任务（第二条会撞 429 RATE_LIMITED）——
    # 要用**两个**用户：甲先占住闸门，乙就只能排队。
    #
    # 【为什么不把 `max_concurrent_tasks` 调大】那会让这条用例
    # 依赖一个和它无关的配置旋钮；而它要验的是「worker 出队那次
    # 调用有没有被记下来」，越少别的前提越好。
    headers_a, _ = await new_user(api, "排队的人甲")
    headers_b, _ = await new_user(api, "排队的人乙")

    first = (await submit_image(api, headers_a, idempotency_key="k1")).json()
    second = (await submit_image(api, headers_b, idempotency_key="k1")).json()
    assert first["status"] == TaskStatus.submitted.value
    assert second["status"] == TaskStatus.queued.value, "闸门没满就没法验出队那条路"

    t0 = utcnow()
    # 第一轮：甲还没好，闸门仍被它占着 —— 乙应该原地不动。
    worker.run_once(api_session, now=t0, provider=scripted)
    assert not [c for c in _calls(api_session) if c.task_id == second["id"]]

    # 第二轮（过了轮询间隔）：甲完成、闸门空出来，乙当轮就被出队。
    later = t0 + timedelta(seconds=60)
    report = worker.run_once(api_session, now=later, provider=scripted)
    assert second["id"] in report.dispatched

    dispatched = [c for c in _calls(api_session) if c.task_id == second["id"]]
    assert dispatched, "worker 出队那次 submit 没被记下来"
    assert dispatched[0].action == "submit"


# ══════════════════════════════════════════════════════════════
# 五、审计坏了**不许**影响生成
# ══════════════════════════════════════════════════════════════


async def test_审计写库失败不影响生成(api, api_session, monkeypatch) -> None:
    """best-effort 是硬要求，不是偷懒。

    审计子系统出任何问题（库锁了、盘满了、表被删了）都不许让一次
    正常的生成变成 500 —— 同 `assets.delete_asset` 删文件失败只记日志
    的那条纪律：**附属功能的失败不能升级成主流程的失败**。

    【怎么造这个坏】把审计层拿会话的那个函数换成抛异常的版本。
    这条路上它确实会抛，而不是「恰好没写进去」。
    """

    def _boom() -> object:
        raise RuntimeError("假设审计库这一刻写不进去")

    monkeypatch.setattr("app.services.provider_audit.get_session_factory", _boom)

    headers, _ = await new_user(api, "被审计拖累的人")

    res = await submit_image(api, headers)

    assert res.status_code in (200, 201), f"审计坏了把生成也带崩了：{res.text}"
    assert res.json()["status"] == TaskStatus.succeeded.value
    assert _calls(api_session) == [], "写不进去就是写不进去，但它不该抛出去"


def test_冲刷失败之后待冲队列会被清空() -> None:
    """⚠️ 不重试是**有意**的。

    「审计写不进去」通常正是库层面的问题（锁、磁盘满），把待冲队列
    留着让下一次 flush 连同上次一起重试，只会让同一个失败滚雪球。
    丢掉并记一条 error 是更诚实的选择：**审计可以少，但主流程不能坏**。
    """
    audit = CallAudit()
    audit.record(PendingCall(action="submit"))
    assert len(audit) == 1

    import app.services.provider_audit as provider_audit

    original = provider_audit.get_session_factory
    provider_audit.get_session_factory = lambda: (_ for _ in ()).throw(RuntimeError("坏了"))
    try:
        audit.flush(task_id=None)  # 不许抛
    finally:
        provider_audit.get_session_factory = original

    assert len(audit) == 0, "失败的待冲队列必须清空，否则下一个请求会连它一起重试"
