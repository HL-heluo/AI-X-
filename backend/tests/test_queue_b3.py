"""队列 —— §8.2 的规则、§8.1 的闸门、§8.3 的状态机。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件为什么几乎全在打 HTTP，而不是直接调 `services/queue.py`】

因为队列的**规则**是「用户看到什么」，不是「函数返回什么」：

  · §8.2 的「诚实显示排队位次」只在响应体里才成立；
  · §8.1 的闸门在「这个请求该成功还是该排队」这一层才有意义；
  · 而 `queue_position` 是**响应字段**，它只在 `TaskOut` 里活。

直接测函数的代价是：把 `has_free_slot` 测得很绿，而真正接线的
那一处（`submit` 里那个 `if`）写反了 —— 那种绿比红更糟。

【唯一被直接测的是排序键】见 `test_排序键_位次与出队顺序是同一个`——
因为它是**跨函数的约定**（位次算一套、出队按另一套，两个数就对不上），
而它在 HTTP 层看不出区别。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from _helpers import new_user, submit_image, submit_video
from _providers import ScriptedProvider
from app.enums import TaskStatus
from app.models import Task
from app.services import queue
from app.types import utcnow


async def _me(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    return (await api.get("/me", headers=headers)).json()["credit_account"]


async def _tasks(api: httpx.AsyncClient, headers: dict[str, str]) -> list[dict]:
    return (await api.get("/tasks", headers=headers)).json()["items"]


async def _upload(api: httpx.AsyncClient, headers: dict[str, str]) -> int:
    res = await api.post(
        "/uploads/image",
        files={"file": ("ref.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["asset_id"]


def _queue_row(
    *, user_id: int, prompt: str, created_at: datetime, queued_at: datetime
) -> Task:
    """直接摆一条 `queued` 任务。

    【为什么允许测试直接写库】入口闸（§7.5 闸 3）保证一个用户同类
    只能有一个活跃任务，所以**走 HTTP 摆不出「一个人排三条」** ——
    而那正是排序键那两条用例要的形状。它们测的是队列内部的顺序，
    不是准入，所以从库里摆是合适的；准入本身由
    `test_同类第二个任务被入口闸挡下` 盯着。
    """
    return Task(
        user_id=user_id,
        kind="text_to_image",
        status=TaskStatus.queued,
        provider="scripted",
        prompt=prompt,
        params_json="{}",
        freeze_amount=4,
        created_at=created_at,
        queued_at=queued_at,
    )


# ══════════════════════════════════════════════════════════════
# 「提交即完成」这条契约，B3 之后必须一个字都没变
# ══════════════════════════════════════════════════════════════


async def test_fake_provider_下提交即完成_一个字都没变(api: httpx.AsyncClient) -> None:
    """B3 加了整套队列之后，`fake` 下的响应形状必须和 B2 完全一样。

    ─────────────────────────────────────────────────────────
    【这条用例为什么必须存在】

    因为 B3 改的正是 `submit` 的那一段。如果队列接进来之后
    「fake 也排队了」，表现是**前端 138 条测试全红**，而这里的
    125 条 B2 测试可能还是全绿 —— 后端原本没有任何一条测试在断言
    「fake 下提交完就是 succeeded」。

    它是这一批最便宜、也最重要的一条防线：跨仓契约（余额 46/22、
    `status: succeeded`）在后端这一侧的唯一代理。

    【为什么连时间线也一起断言】因为「succeeded 但 queued_at 是
    NULL」这种记录在 B2 是不可能出现的（`_complete` 一次补三个时刻）。
    B3 把那三行拆进了三个函数，拆错了的话状态是对的、时间线是断的，
    而前端只读状态 —— 又是一个只有后端能发现的错。
    ─────────────────────────────────────────────────────────
    """
    headers, registered = await new_user(api, "alice")

    res = await submit_image(api, headers, idempotency_key="k1")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["status"] == "succeeded"
    assert body["queue_position"] is None
        # 终态没有「前面还有几个」可言 —— 报 0 会让用户以为马上就出结果。
    assert body["settled_amount"] == 4
    assert body["params"] == {"ratio": "1:1"}
    assert body["queued_at"] and body["submitted_at"] and body["finished_at"]

    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (46, 0)
    assert registered["credit_account"]["balance"] == 50


async def test_fake_provider_下队列永远是空的(api: httpx.AsyncClient) -> None:
    """连发三个任务，一条都不会停在排队中。

    【它和上一条不是重复的】上一条断言的是「响应是什么」，
    这一条断言的是「库里没有残留」—— 出队闸门如果写成了
    「永远认为满了」，第一条用例照样绿（它走的是另一条分支收尾的），
    而用户的第二个任务会静默地排在那里，排到天荒地老。
    """
    headers, _ = await new_user(api, "alice")

    for index in range(3):
        res = await submit_image(api, headers, idempotency_key=f"k{index}")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "succeeded"

    items = await _tasks(api, headers)
    assert [t["status"] for t in items] == ["succeeded"] * 3


# ══════════════════════════════════════════════════════════════
# 闸门（§8.1）与排队（§8.2）
# ══════════════════════════════════════════════════════════════


async def test_闸门满了就排队_不报错(api: httpx.AsyncClient, scripted: ScriptedProvider) -> None:
    """一人在跑、另一人提交 → 后者拿到 `queued` + 位次 1，**不是** 503。

    ─────────────────────────────────────────────────────────
    【为什么「排队」绝不能表现成错误】

    §12.3 里确实有一个 `QUEUE_SATURATED`(503「队列已满」)，但它说的是
    **队列装不下**（有容量上限时才可能发生）。这里发生的是**正常排队**：
    用户提交成功、钱冻上了、任务在队列里 —— 报错会让他按「重试」，
    而重试只会让队列更长，还会撞上幂等键。

    【为什么账户那一组断言是重点】排队意味着**钱已经冻了**。
    前端那条「退回差额」的账要成立，就必须是「冻结在提交时发生、
    结算在完成时发生」—— 排队中 `frozen=4, balance=50`，可用 46。
    写成「排队时不冻结」的话，用户可以在排队期间把同一笔钱花在
    别处，等轮到他时余额已经不够了。
    ─────────────────────────────────────────────────────────
    """
    a_h, _ = await new_user(api, "alice")
    b_h, _ = await new_user(api, "bob")

    first = await submit_image(api, a_h, idempotency_key="a1")
    assert first.json()["status"] == "submitted"
        # alice 拿到了唯一的那个闸门位：任务是「已提交、等结果」。

    second = await submit_image(api, b_h, idempotency_key="b1")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "queued"
    assert body["queue_position"] == 1
    assert body["submitted_at"] is None
    assert body["settled_amount"] is None
    assert body["queued_at"] is not None

    account = await _me(api, b_h)
    assert (account["balance"], account["frozen"]) == (50, 4)


async def test_排队位次按先来后到(api: httpx.AsyncClient, scripted: ScriptedProvider) -> None:
    """第 2、3、4 个排队的人拿到位次 1、2、3。

    【位次从 1 开始，不是从 0】因为它回答的是「前面还有几个」——
    「前面还有 0 个」在中文里等于「马上到你」，而那正是 §8.2 禁止的
    假进度。第一个人前面有 0 个别的排队者，但他自己也要占一位。
    """
    a_h, _ = await new_user(api, "alice")
    await submit_image(api, a_h, idempotency_key="a1")

    positions = []
    for name in ("bob", "carol", "dave"):
        headers, _ = await new_user(api, name)
        res = await submit_image(api, headers, idempotency_key="k1")
        positions.append((name, res.json()["queue_position"]))

    assert positions == [("bob", 1), ("carol", 2), ("dave", 3)]


async def test_图与视频分开数位次(api: httpx.AsyncClient, scripted: ScriptedProvider) -> None:
    """§8.2：两条图片在排队，不影响视频的位次。

    ─────────────────────────────────────────────────────────
    【为什么这条必须单独测】§8.2 给的理由是「否则图片会被视频饿死」——
    一条排了十分钟的视频会把后面所有秒级的图片堵住。反过来也一样：
    两条图片不该让一个视频用户看到「前面还有 3 个」而其实下一轮
    就轮到他。位次是**给用户的时间预期**，预期错了就是骗人。
    ─────────────────────────────────────────────────────────
    """
    # 图片通道：一人跑、两人排
    img_h, _ = await new_user(api, "img1")
    await submit_image(api, img_h, idempotency_key="i1")
    for name in ("img2", "img3"):
        headers, _ = await new_user(api, name)
        queued_image = await submit_image(api, headers, idempotency_key="i1")
        assert queued_image.json()["status"] == "queued"

    # 视频通道：一人跑、一人排
    vid_h, _ = await new_user(api, "vid1")
    ref = await _upload(api, vid_h)
    first_video = await submit_video(api, vid_h, source_asset_id=ref, idempotency_key="v1")
    assert first_video.json()["status"] == "submitted"

    vid2_h, _ = await new_user(api, "vid2")
    ref2 = await _upload(api, vid2_h)
    queued_video = await submit_video(api, vid2_h, source_asset_id=ref2, idempotency_key="v1")

    assert queued_video.json()["status"] == "queued"
    assert queued_video.json()["queue_position"] == 1
        # 图片那边已经排了 2 个人了，一个都不该算进来。


async def test_同类第二个任务被入口闸挡下(api: httpx.AsyncClient, scripted: ScriptedProvider) -> None:
    """§7.5 闸 3：同一用户**同类**同时只能有一个活跃任务。

    ─────────────────────────────────────────────────────────
    【这条用例钉住的是「轮转为什么不用单独实现」这个前提】

    §8.2 要求轮转调度（同一用户不连续占两轮）。`services/queue.py`
    里的做法是**不实现它**，理由是一条推理：入口闸保证每个用户每类
    至多一个活跃任务，于是队列里每个用户每类最多占一个位子，
    「按时间先进先出」和「用户之间轮流」就是同一件事。

    这条推理一旦被改坏（比如有人把 `max_concurrent_tasks` 调到 2），
    轮转就静默消失了 —— 没有报错、没有测试变红、只是有人开始被插队。
    所以这里把它钉成一条用例：**改那个配置的人会在这里看到红**。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "alice")
    await submit_image(api, headers, idempotency_key="a1")

    second = await submit_image(api, headers, idempotency_key="a2")

    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


# ══════════════════════════════════════════════════════════════
# 排序键：位次与出队顺序必须一致（这两条只能直接测函数）
# ══════════════════════════════════════════════════════════════


async def test_排序键_位次与出队顺序是同一个(api: httpx.AsyncClient, api_session: Session) -> None:
    """排队位次和「下一个被捞走的」必须一致，而且都得按 `(queued_at, id)` 排。

    ─────────────────────────────────────────────────────────
    【这四条数据为什么摆得这么别扭】

    因为这条约定**跨两个函数**（`position_of` 算位次、`claim_next`
    选出队的），而它俩可以**各自都对、合起来错**。想让用例真的发现
    这件事，摆出来的数据必须让四种候选键给出**四个不同的答案** ——
    否则一个用错键的实现照样绿，用例只是看着严。

    所以四条任务的 `created_at`、`queued_at`、`id`（= 插入顺序）
    **两两不同序**，而唯一的正确答案是 `(queued_at, id)`：

        prompt     id    created_at    queued_at
        A（最早建） 1     now           now+2s   ← 建了却没马上入队
        B          2     now+10s       now      ← 与 C 同一刻入队
        C          3     now+20s       now
        D          4     now+30s       now+1s

        期望：B, C, D, A
        按 created_at 排 → A, B, C, D   ✗
        按 id 排         → A, B, C, D   ✗
        按 queued_at 排、但不带 id 兜底 → B 与 C 并列（两个都算 1）
                                            → 位次不是 1..4 的排列 ✗

    【A 为什么不是编出来的形状】它就是**退避过的任务**：`created_at`
    很早（早就建好了），`queued_at` 被推到未来。B/C 同一刻入队也不是
    生造的 —— 一次 worker tick 里连出两条任务就是这样。
    ─────────────────────────────────────────────────────────
    """
    _, registered = await new_user(api, "alice")
    user_id = registered["user"]["id"]
    now = utcnow()

    def row(prompt: str, *, created: int, queued: int) -> Task:
        return _queue_row(
            user_id=user_id,
            prompt=prompt,
            created_at=now + timedelta(seconds=created),
            queued_at=now + timedelta(seconds=queued),
        )

    # ⚠️ 插入顺序就是 id 顺序 —— 上面那张表里的 A,B,C,D 就是这里的顺序。
    api_session.add_all(
        [
            row("A", created=0, queued=2),
            row("B", created=10, queued=0),
            row("C", created=20, queued=0),
            row("D", created=30, queued=1),
        ]
    )
    api_session.commit()

    expected = ["B", "C", "D", "A"]

    # ① 位次：把四条按位次排出来，应该就是出队顺序。
    rows = api_session.scalars(select(Task).where(Task.status == TaskStatus.queued)).all()
    positions = {t.prompt: queue.position_of(api_session, t) for t in rows}
    assert sorted(positions.values()) == [1, 2, 3, 4], (
        f"位次不是 1..4 的排列，说明有并列 —— 排序键少了 id 兜底：{positions}"
    )
    assert sorted(positions, key=lambda p: positions[p]) == expected

    # ② 出队：真的一条条捞出来，顺序必须一模一样。
    claimed: list[str] = []
    for _ in range(len(expected)):
        nxt = queue.claim_next(api_session, "text_to_image", now + timedelta(seconds=5))
        assert nxt is not None, "队列里还有任务，却捞不到"
        claimed.append(nxt.prompt)
        # 捞走一条就把它标成 submitted，这样下一轮捞的是下一条。
        nxt.status = TaskStatus.submitted
        api_session.flush()

    assert claimed == expected


async def test_退避把任务推到队尾(api: httpx.AsyncClient, api_session: Session) -> None:
    """重试退避之后，这条任务的位次**掉到最后**。

    【为什么这条值得单独写】退避的实现是「把 `queued_at` 推到未来」。
    如果位次是按 `created_at` 算的（一个很自然的写法），退避就白退了：
    任务会一直显示在第一位、每轮被捞起来、每轮被推开 ——
    用户看到的是「排队中，前面还有 0 个」挂了十分钟。
    """
    _, registered = await new_user(api, "alice")
    user_id = registered["user"]["id"]
    now = utcnow()

    earliest = _queue_row(user_id=user_id, prompt="earliest", created_at=now, queued_at=now)
    middle = _queue_row(
        user_id=user_id, prompt="middle", created_at=now, queued_at=now + timedelta(seconds=1)
    )
    retried = _queue_row(
        user_id=user_id, prompt="retried", created_at=now, queued_at=now - timedelta(seconds=5)
    )
    api_session.add_all([earliest, middle, retried])
    api_session.commit()

    assert queue.position_of(api_session, retried) == 1

    queue.requeue_for_retry(api_session, retried, now=now)
    api_session.flush()

    assert retried.retry_count == 1
    assert retried.queued_at > now + timedelta(seconds=1)
    assert queue.position_of(api_session, retried) == 3
    assert queue.position_of(api_session, earliest) == 1
