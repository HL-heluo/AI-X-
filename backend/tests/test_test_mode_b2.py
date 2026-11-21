"""`/__test/*` —— §15.1 的验收自动化要能反复重跑。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这两条端点是整批里**唯一**能凭空造钱、能删库的东西】

所以这个文件测的重点不是「功能对不对」，而是两件事：

  1. 它真的**管用**（不然 §15.1 的剧本重跑不了，而人会在半路
     手动改库 —— 那种手工步骤最后一定会被跳过）；
  2. 它**只在 TEST_MODE 开着时存在**（关着时在路由表里查无此路，
     而不是「返回 403」—— 那个区别见 B0 的门禁注释）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import httpx

from _helpers import PASSWORD, auth, new_user, register


async def test_reset_种下_MOCK_邀请码(api: httpx.AsyncClient) -> None:
    """`POST /__test/reset` → `{ok: true, invite_code: "MOCK"}`。

    【为什么必须是 `MOCK` 这四个字母】因为前端**全部**测试和浏览器剧本
    用的就是它（`repository_layer_test` / `auth_flow_test` /
    `me_credits_test` 里都是 `inviteCode: 'MOCK'`）。夹具也依赖它 ——
    换个名字，那些冻结的用例和 B2 的全部测试会一起红。
    """
    res = await api.post("/__test/reset")

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "invite_code": "MOCK"}


async def test_reset_真的把数据清掉了(api: httpx.AsyncClient) -> None:
    """⚠️ 它必须**真的**删库，而不是「假装重置」。

    ─────────────────────────────────────────────────────────
    【为什么用「旧 token 失效」来证明】

    因为这是唯一一条**只能由删库导致**的观察：token 本身签名还是合法的
    （密钥没换），失效的原因是它指向的 user id 不存在了。
    换成「用户名可以重复注册」来验也行，但那条弱一些 ——
    它在「reset 只清了 users 没清 credit_accounts」这种半吊子实现下
    也会绿。

    这在前端的浏览器验收里是刚需：剧本要反复重跑，不清库的话
    第二次跑就会撞上「用户名已被占用」。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "重置前的人")

    await api.post("/__test/reset")

    res = await api.get("/me", headers=headers)
    assert res.status_code == 401, "清库之后旧 token 必须失效"
    assert res.json()["code"] == "UNAUTHORIZED"

    # 重置之后 MOCK 还能再用（不限次）
    again = await api.post(
        "/auth/register",
        json={"invite_code": "MOCK", "username": "重置前的人", "password": PASSWORD},
    )
    assert again.status_code == 201, again.text


async def test_grant_加钱并且记一条_adjust_流水(api: httpx.AsyncClient) -> None:
    """`POST /__test/grant` → 走 `credits.adjust`（§15.1 的管理员脚本）。

    ─────────────────────────────────────────────────────────
    【为什么这条要盯着流水，而不只是余额】

    直接改 `account.balance` 也能让这里绿 —— 但那会让用户的积分页
    显示「余额 150，流水加起来只有 50」，而那种账在没有客服
    权限的 v1 里根本解释不清。所以断言里必须有一条 `adjust`。

    【为什么 kind 是 `adjust` 而不是 `grant`】见
    `services/credits.py`：`grant` 专指「注册赠送」这一个业务动作，
    `adjust` 是「人手工改了一笔」。混用的话，将来对账时
    「赠送」那一栏会把运营补贴也算进去。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "要被发钱的人")

    res = await api.post(
        "/__test/grant", json={"username": "要被发钱的人", "amount": 100}
    )

    assert res.status_code == 200, res.text
    assert res.json()["credit_account"]["balance"] == 150, res.text

    entries = (await api.get("/credits/ledger", headers=headers)).json()["items"]
    assert entries[0]["kind"] == "adjust"
    assert entries[0]["amount"] == 100
    assert entries[0]["balance_after"] == 150


async def test_grant_给不存在的人发钱是_404(api: httpx.AsyncClient) -> None:
    """打错用户名时要说清楚，而不是静默成功。

    【为什么这条要紧】验收脚本是**手打**的（§15.1 的剧本），
    用户名打错一个字是常事。静默成功的话，脚本会继续往下跑，
    然后在「余额不足」那一步失败 —— 排查方向完全错了。
    """
    res = await api.post("/__test/grant", json={"username": "查无此人", "amount": 100})

    assert res.status_code == 404, res.text
    assert res.json()["code"] == "NOT_FOUND"


async def test_TEST_MODE_关着时_reset_和_grant_在路由表里根本不存在(make_app) -> None:
    """⚠️ 安全守卫：这两条能删库/造钱的接口，关掉时**不许存在**。

    ─────────────────────────────────────────────────────────
    【为什么断言的是路由表，而不是 HTTP 404】

    两者在 HTTP 层一模一样，但含义差很远：

      · **不注册** → 这个路径不存在。将来某次重构把那个 `if` 挪走了，
        改动的意图是可见的（要删掉一行 `return`）。
      · **注册了但抛错 / 返回 403** → 路径存在。某次重构顺手把
        判断挪进函数体、或改成「记个日志继续」，**接口就静默地开了**，
        而 HTTP 层的现象从 403 变成 200，没人会去注意。

    一个不需要鉴权就能删库的接口配得上这种程度的谨慎。
    ─────────────────────────────────────────────────────────
    """
    app = make_app(TEST_MODE="0")

    leaked = [
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", "").startswith("/__test")
    ]

    assert leaked == [], f"TEST_MODE=0 却注册了测试路由：{leaked}"


async def test_TEST_MODE_关着时业务路由照样在(make_app) -> None:
    """反向确认：关掉测试接口**不影响**任何业务端点。

    【为什么要这条】上面那条守卫可以用「干脆什么都不挂」来满足 ——
    而那种实现会让整个服务变成空壳。这条钉住另一半。
    """
    app = make_app(TEST_MODE="0")

    paths = {getattr(route, "path", "") for route in app.routes}

    for expected in (
        "/health",
        "/auth/register",
        "/auth/login",
        "/me",
        "/credits/ledger",
        "/generation/image",
        "/generation/video",
        "/generation/cost",
        "/tasks",
        "/assets",
        "/uploads/image",
    ):
        assert expected in paths, f"{expected} 不见了：{sorted(paths)}"


async def test_reset_之后原来的邀请码记录也重建了(api: httpx.AsyncClient) -> None:
    """重置用的是 `drop_all` + `create_all`，所以**表结构**也是重建的。

    【为什么这条值得单独测】如果 reset 的实现是「DELETE FROM 每张表」，
    它会漏掉那些**没有数据**的表，也会在自增 id 上留下痕迹
    （SQLite 的 `AUTOINCREMENT` 会继续往上走）。用 `drop_all` 则是
    彻底的：id 从 1 重新开始，且任何新加的表都不会被漏掉。

    这里用「重置后注册的用户 id 又是 1」来观察这件事 ——
    它不是一条硬性契约，但它能立刻暴露出实现变成了逐表 DELETE。
    """
    first = await register(api, "第一个")
    assert first["user"]["id"] == 1

    await api.post("/__test/reset")
    second = await register(api, "第一个")

    assert second["user"]["id"] == 1, "drop_all 之后自增 id 要重新开始"


async def test_reset_不需要鉴权(api: httpx.AsyncClient) -> None:
    """⚠️ 刻意的：验收脚本要能从一个空库开始，而那时它还没有 token。

    这条用例的作用是**把这个事实写下来** —— 它是「TEST_MODE 必须是
    硬门禁」这条纪律存在的全部理由。
    """
    assert (await api.post("/__test/reset")).status_code == 200
