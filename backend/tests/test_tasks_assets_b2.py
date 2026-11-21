"""任务与资产的查询/取消 —— §8 / §9.4 / §12.1。"""

from __future__ import annotations

import httpx

from _helpers import auth, grant_credits, new_user, register, submit_image, submit_video


async def _upload(api: httpx.AsyncClient, headers: dict[str, str], name: str = "ref.png") -> int:
    res = await api.post(
        "/uploads/image",
        files={"file": (name, b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["asset_id"]


# ── 任务列表 ──────────────────────────────────────────────────


async def test_任务列表的形状与排序(api: httpx.AsyncClient) -> None:
    """`/tasks` 是 `{items, page, page_size, total}`，最新的在前。

    【为什么 `page_size` 必须等于 `total`】见 `TaskListOut` 的说明：
    这是**唯一**能保证前端拿到全部任务的方式。前端的任务页拿到
    `items` 就直接渲染，从不翻页 —— 这里要是给个 20，第 21 条
    就会**静默消失**，而用户不会收到任何提示。
    """
    headers, _ = await new_user(api, "有三个任务的人")
    await submit_image(api, headers, prompt="第一张", idempotency_key="t1")
    await submit_image(api, headers, prompt="第二张", idempotency_key="t2")
    await submit_image(api, headers, prompt="第三张", idempotency_key="t3")

    body = (await api.get("/tasks", headers=headers)).json()

    assert body["total"] == 3
    assert body["page_size"] == 3 == len(body["items"]), "page_size 必须是全部条数"
    assert body["page"] == 1
    assert [item["prompt"] for item in body["items"]] == ["第三张", "第二张", "第一张"]


async def test_任务列表不是分页接口(api: httpx.AsyncClient, monkeypatch) -> None:
    """⚠️ 超过 20 条时也**一条都不能少**。

    ─────────────────────────────────────────────────────────
    【为什么这条要临时把每日上限调高】

    因为默认每日上限就是 20，而要证明「不是分页」必须拿到 21 条以上
    —— 20 条时 `page_size=20` 和 `page_size=len(items)` 是同一个数，
    用什么写法都看不出区别。这条用例把这个上限临时抬到 100，
    让 22 个任务真的建出来。

    为什么要 `get_settings.cache_clear()`：`get_settings()` 带
    `lru_cache`，不清的话 `_check_quota` 读到的还是旧的那份配置
    （这个坑在本仓库的 conftest 里已经被写下来过一次）。
    ─────────────────────────────────────────────────────────
    """
    from app.config import get_settings

    monkeypatch.setenv("DAILY_TASK_LIMIT", "100")
    get_settings.cache_clear()

    headers, _ = await new_user(api, "有很多任务的人")
    await grant_credits(api, "有很多任务的人", 500)
    for i in range(22):
        res = await submit_image(api, headers, idempotency_key=f"many-{i}")
        assert res.status_code == 200, f"第 {i + 1} 个就失败了：{res.text}"

    body = (await api.get("/tasks", headers=headers)).json()

    assert body["total"] == 22
    assert len(body["items"]) == 22, "第 21 条之后的任务不能被静默截断"
    assert body["page_size"] == 22


async def test_按状态筛选(api: httpx.AsyncClient) -> None:
    """`?status=active` / `?status=done`。

    【为什么 fake provider 下 `active` 是空的，而这条仍然有意义】
    因为走 fake 时所有任务提交即终态 —— 于是「active 为空」
    本身就是一条断言：它证明筛选真的按状态过滤了，而不是把
    所有任务原样返回。B3 引入真实排队后，同一个用例会改成
    「提交后立刻查 active，应当有一条 queued」。
    """
    headers, _ = await new_user(api, "要筛选的人")
    await submit_image(api, headers, idempotency_key="s1")

    active = (await api.get("/tasks?status=active", headers=headers)).json()
    done = (await api.get("/tasks?status=done", headers=headers)).json()

    assert active["total"] == 0, "fake provider 下没有进行中的任务"
    assert done["total"] == 1
    assert done["items"][0]["status"] == "succeeded"


async def test_任务列表只包含自己的(api: httpx.AsyncClient) -> None:
    """⚠️ 别人的任务一条都不能出现（§8 的隐私底线）。"""
    mine, _ = await new_user(api, "只看自己的")
    other_session = await register(api, "任务很多的人")
    await submit_image(
        api, auth(other_session["token"]), idempotency_key="theirs"
    )
    await submit_image(api, mine, idempotency_key="mine")

    body = (await api.get("/tasks", headers=mine)).json()

    assert body["total"] == 1
    assert body["items"][0]["idempotency_key"] == "mine"


# ── 任务详情 ──────────────────────────────────────────────────


async def test_任务详情(api: httpx.AsyncClient) -> None:
    """`GET /tasks/{id}` 的形状和提交的响应**同构**（同一个 `TaskOut`）。"""
    headers, _ = await new_user(api, "看详情的人")
    created = (await submit_image(api, headers)).json()

    res = await api.get(f"/tasks/{created['id']}", headers=headers)

    assert res.status_code == 200, res.text
    assert res.json() == created, "详情与提交响应必须是同一个形状"


async def test_别人的任务是_404(api: httpx.AsyncClient) -> None:
    """⚠️ 拿别人的任务 id 查，必须是 404（不是 403）。

    【为什么】403 等于确认了「这个 id 存在」—— 那是一个可以拿来
    枚举 id 的探针，而任务详情里有提示词和产物地址。
    """
    mine, _ = await new_user(api, "手很长的")
    other_session = await register(api, "被查的人")
    other_task = (
        await submit_image(api, auth(other_session["token"]), idempotency_key="secret")
    ).json()

    res = await api.get(f"/tasks/{other_task['id']}", headers=mine)

    assert res.status_code == 404, res.text
    assert res.json()["code"] == "NOT_FOUND"


async def test_任务_id_不是数字时是_400(api: httpx.AsyncClient) -> None:
    """路径参数类型错 → `INVALID_REQUEST`，不是 500。"""
    headers, _ = await new_user(api, "乱传 id 的人")

    res = await api.get("/tasks/abc", headers=headers)

    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INVALID_REQUEST"


# ── 取消 ──────────────────────────────────────────────────────


async def test_取消一个已成功的任务返回_409(api: httpx.AsyncClient) -> None:
    """⚠️ §7.4：终态不可逆。

    ─────────────────────────────────────────────────────────
    【为什么这条在 B2 里是「唯一的取消路径」】

    fake provider 提交即完成，所以任何任务被取消时都已经是终态 ——
    「排队中取消、全额退回」那条分支在 B2 里**走不到**（它是 B3 的活，
    见 `services/generation.cancel_task` 的注释）。这里测的是另一条：
    已经花掉的钱不能被取消退回来。

    【为什么这个 409 值得有一个专门的错误码】见 `enums.TASK_NOT_CANCELABLE`：
    §12.3 里没有它，而 Mock 给出了一个 409 + 一句具体的话。
    补上它之后，服务端日志和 curl 手打都能说清是哪一类冲突
    （前端文案仍走通用兜底 —— 那是 F 侧的一次小改动，不在这批）。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "想取消的人")
    task = (await submit_image(api, headers)).json()
    before = (await api.get("/me", headers=headers)).json()["credit_account"]

    res = await api.post(f"/tasks/{task['id']}/cancel", headers=headers)

    assert res.status_code == 409, res.text
    assert res.json()["code"] == "TASK_NOT_CANCELABLE"
    after = (await api.get("/me", headers=headers)).json()["credit_account"]
    assert after == before, "取消失败不该动积分"


async def test_取消不存在的任务是_404(api: httpx.AsyncClient) -> None:
    headers, _ = await new_user(api, "取消空气的人")

    res = await api.post("/tasks/999999/cancel", headers=headers)

    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


# ── 资产 ──────────────────────────────────────────────────────


async def test_视频任务产出正片和封面两张资产(api: httpx.AsyncClient) -> None:
    """§11.2：视频落两张 —— 正片 + 缩略图。

    ─────────────────────────────────────────────────────────
    【为什么封面是**独立**的一张资产，而不是视频的附属字段】

    因为作品列表一屏要摆九个视频。每个都直接加载视频文件当封面的话，
    流量和内存都会炸。封面是单独一张小图，列表读它，点开才读视频。
    所以它们是两个文件、两行记录、各有各的 URL。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "看作品的人")
    asset_id = await _upload(api, headers)
    task = (await submit_video(api, headers, source_asset_id=asset_id)).json()

    items = (await api.get("/assets?page_size=50", headers=headers)).json()["items"]
    by_kind = {item["kind"]: item for item in items}

    assert set(by_kind) == {"image", "video", "thumbnail"}, by_kind
    assert by_kind["video"]["duration_sec"] == 6, "成片时长 = 6（请求 5 + 1）"
    assert by_kind["video"]["mime"] == "video/mp4"
    assert (by_kind["video"]["width"], by_kind["video"]["height"]) == (1280, 720)
    assert by_kind["thumbnail"]["mime"] == "image/jpeg"
    assert by_kind["video"]["task_id"] == task["id"]
    assert by_kind["thumbnail"]["task_id"] == task["id"]


async def test_出图产出一张_1024_的_png(api: httpx.AsyncClient) -> None:
    """图片产物：1024×1024、`image/png`、`duration_sec` 是 null。"""
    headers, _ = await new_user(api, "看出图的人")
    await submit_image(api, headers)

    items = (await api.get("/assets", headers=headers)).json()["items"]

    assert len(items) == 1
    assert items[0]["kind"] == "image"
    assert items[0]["mime"] == "image/png"
    assert (items[0]["width"], items[0]["height"]) == (1024, 1024)
    assert items[0]["duration_sec"] is None, "图片没有时长"


async def test_资产可以按_task_id_过滤(api: httpx.AsyncClient) -> None:
    """作品详情页要看「这一条任务产出了什么」。

    【为什么要用 `task_id` 而不是让前端筛】因为作品的产物是
    **服务端**知道的事实，让客户端拿全量列表自己过滤，等于把
    「哪些资产属于哪个任务」这条规则复制到客户端一份。
    """
    headers, _ = await new_user(api, "按任务筛的人")
    # 两条 5 秒视频要冻 32×2，注册送的 50 不够 —— 先补足
    # （不补的话第二个提交会以 INSUFFICIENT_CREDITS 失败，
    #   而那条失败和本用例要测的「按 task_id 过滤」毫无关系）。
    await grant_credits(api, "按任务筛的人", 200)
    asset_id = await _upload(api, headers)
    first = (await submit_video(api, headers, source_asset_id=asset_id)).json()
    second = (
        await submit_video(api, headers, source_asset_id=asset_id, idempotency_key="v2")
    ).json()

    only_first = (
        await api.get(f"/assets?task_id={first['id']}", headers=headers)
    ).json()

    assert only_first["total"] == 2, "一条视频任务产出正片 + 封面"
    assert {item["task_id"] for item in only_first["items"]} == {first["id"]}
    assert second["id"] not in {item["task_id"] for item in only_first["items"]}


async def test_删除资产之后列表里就没有它了(api: httpx.AsyncClient) -> None:
    """`DELETE /assets/{id}` → `{"ok": true}`，且真的删掉了。"""
    headers, _ = await new_user(api, "删作品的人")
    asset_id = await _upload(api, headers)

    res = await api.delete(f"/assets/{asset_id}", headers=headers)

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    items = (await api.get("/assets", headers=headers)).json()["items"]
    assert asset_id not in {item["id"] for item in items}


async def test_删不存在的资产是_404(api: httpx.AsyncClient) -> None:
    """不幂等 —— 见 `routers/assets.py` 里为什么不做成「删了就返回 ok」。"""
    headers, _ = await new_user(api, "删空气的人")

    res = await api.delete("/assets/999999", headers=headers)

    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


async def test_不能删别人的资产(api: httpx.AsyncClient) -> None:
    """⚠️ 拿别人的 asset_id 删，必须是 404 且**真的没删掉**。"""
    mine, _ = await new_user(api, "手很长的人")
    other_headers, _ = await new_user(api, "被删的人")
    other_asset_id = await _upload(api, other_headers, name="别人珍贵的图.png")

    res = await api.delete(f"/assets/{other_asset_id}", headers=mine)

    assert res.status_code == 404
    still_there = (await api.get("/assets", headers=other_headers)).json()["items"]
    assert other_asset_id in {item["id"] for item in still_there}, "别人的资产必须还在"
