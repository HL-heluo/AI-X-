"""注册 / 登录 / `/me` 的契约 —— §6.1 / §12.1。

这一组测的不是「功能有没有」，而是**冻结的前端能不能直接解析**。
`lib/data/remote/remote_auth_repository.dart` 读哪些字段，这里就断哪些字段。
"""

from __future__ import annotations

import httpx

from _helpers import PASSWORD, auth, register

# ── 注册 ──────────────────────────────────────────────────────


async def test_注册返回完整会话而且赠送_50_积分(api: httpx.AsyncClient) -> None:
    """§12.1 + §6.1：注册返回 `{token, user, credit_account}`，赠 50 积分。

    ─────────────────────────────────────────────────────────
    【为什么要一次断这么多字段】

    因为这三个对象是**两个不同模型的合体**：
    `RemoteAuthRepository` 用 `AuthSession.fromJson` 解它，
    而首页立刻用同一个响应里的 `credit_account` 渲染积分胶囊。
    少任何一个字段，用户看到的是「注册成功了 → 首页白屏」——
    而那种失败在服务端日志里是全绿的（201）。

    【50 这个数字为什么必须钉住】它是**契约值**，不是随手定的奖励：
    视频 5 秒要冻 32，赠送额低于 32 的话新用户第一次做视频必然撞墙，
    而 v1 没有充值入口（§7.6）。改动它要前后端一起改。
    ─────────────────────────────────────────────────────────
    """
    res = await api.post(
        "/auth/register",
        json={"invite_code": "MOCK", "username": "阿橘", "password": PASSWORD},
    )

    assert res.status_code == 201, res.text
    body = res.json()

    assert set(body) == {"token", "user", "credit_account"}, body
    assert body["token"], "token 不能是空的"
    assert body["user"]["username"] == "阿橘"
    assert isinstance(body["user"]["id"], int), "id 必须是 JSON 整数（前端 requireInt）"
    assert body["user"]["created_at"]

    assert body["credit_account"]["balance"] == 50
    assert body["credit_account"]["frozen"] == 0
    assert body["credit_account"]["updated_at"]


async def test_注册赠送那笔钱必须出现在流水里(api: httpx.AsyncClient) -> None:
    """§7.3：每一笔都要写流水。

    【为什么这条和上一条分开】因为「余额是 50」和「流水里有一笔 50」
    是**两件不同的事**，而对账靠的是后者。只断余额的话，某天有人
    把 `credits.grant` 里的 `_write_ledger` 删了，测试照样绿，
    而用户打开积分页看到的是「余额 50，流水是空的」——
    第一反应是「这钱哪来的」，第二反应是「这App在骗我」。
    """
    session = await register(api, "带流水的人")
    entries = (
        await api.get("/credits/ledger", headers=auth(session["token"]))
    ).json()["items"]

    assert len(entries) == 1
    assert entries[0]["kind"] == "grant"
    assert entries[0]["amount"] == 50
    assert entries[0]["balance_after"] == 50
    assert entries[0]["frozen_after"] == 0
    # 【为什么要断备注里的这四个字】§15.1 的验收剧本里写着「新用户注册赠送」，
    # 前端 Mock 也写的是同一句。文案对不上时，用户截图的流水和文档不一致。
    assert entries[0]["note"] == "新用户注册赠送"


async def test_邀请码为空是_400_INVITE_INVALID(api: httpx.AsyncClient) -> None:
    """空邀请码要落到 `INVITE_INVALID`，**不是** `INVALID_REQUEST`。

    【为什么这个区分要紧】前端 `ApiErrorCode.inviteInvalid` 有一句专门的
    上屏文案（「邀请码无效，请确认后再试」）。码错了的话，用户看到的是
    通用兜底的「出错了，请稍后重试」—— 而他手上明明有个空输入框
    等着他填。
    """
    res = await api.post(
        "/auth/register",
        json={"invite_code": "", "username": "谁都行", "password": PASSWORD},
    )

    assert res.status_code == 400
    assert res.json()["code"] == "INVITE_INVALID"


async def test_不存在的邀请码也是_400_INVITE_INVALID(api: httpx.AsyncClient) -> None:
    """⚠️ 这条是**真后端比 Mock 严格**的地方。

    Mock 的注释写着「不做邀请码白名单校验，任何非空邀请码都通过 ——
    真后端会去 `invite_codes` 表里查」。这里测的就是那句承诺。

    【为什么它重要到要单独一条】因为邀请制是 §7.5 里「成本自保四道闸」
    之一：用户总量受控等于花销总量受控。如果任意字符串都能过，
    这道理序闸门就等于不存在，而**没有任何别的测试会因此变红**。
    """
    res = await api.post(
        "/auth/register",
        json={"invite_code": "随便打的一串", "username": "谁都行", "password": PASSWORD},
    )

    assert res.status_code == 400
    assert res.json()["code"] == "INVITE_INVALID"


async def test_重名是_409_USERNAME_TAKEN(api: httpx.AsyncClient) -> None:
    """§12.3：用户名被占用是 409。

    【为什么不是 400】用户没写错什么，他只是晚了一步。409 的语义是
    「和当前状态冲突」，前端据此可以说「换一个名字」而不是「填错了」。
    """
    await register(api, "重名的人")
    res = await api.post(
        "/auth/register",
        json={"invite_code": "MOCK", "username": "重名的人", "password": PASSWORD},
    )

    assert res.status_code == 409
    assert res.json()["code"] == "USERNAME_TAKEN"


async def test_大小写不同的重名也要挡住(api: httpx.AsyncClient) -> None:
    """`Alice` 和 `alice` 在用户眼里是同一个人。

    【为什么用 `casefold()` 而不是直接比字符串】见 `models.py` 的
    `username_canonical`：唯一约束建在**规范化列**上，不是原始列上。
    直接比原始串的话，库里会同时存在 `Alice` 和 `alice` ——
    两个人长得一模一样，用户永远说不清哪个是自己的。
    """
    await register(api, "Alice")
    res = await api.post(
        "/auth/register",
        json={"invite_code": "MOCK", "username": "aLiCe", "password": PASSWORD},
    )

    assert res.status_code == 409
    assert res.json()["code"] == "USERNAME_TAKEN"


# ── 登录 ──────────────────────────────────────────────────────


async def test_登录成功返回同样的会话形状(api: httpx.AsyncClient) -> None:
    """登录的返回必须和注册**完全同构**。

    【为什么】因为前端这两个方法共用 `AuthSession.fromJson`。
    形状有一点不同，那个解析器的某一侧就是死的 —— 而它只在
    「退出登录后再登一次」这条路径上才被执行到。
    """
    await register(api, "回来的人")
    res = await api.post("/auth/login", json={"username": "回来的人", "password": PASSWORD})

    assert res.status_code == 200, res.text
    assert set(res.json()) == {"token", "user", "credit_account"}
    assert res.json()["user"]["username"] == "回来的人"


async def test_密码错和用户名不存在返回_一模一样_的_401(api: httpx.AsyncClient) -> None:
    """⚠️ 安全纪律：外部**无法区分**这两种失败。

    ─────────────────────────────────────────────────────────
    【为什么断言的是「响应体逐字节相同」而不是「状态码都是 401」】

    只断状态码的话，`message` 里写着「用户不存在」和「密码错误」的区别
    依然是一个可用的**用户名枚举探针** —— 攻击者拿一个字典跑一遍，
    就知道站里有哪些用户名。

    所以这里比的是 `r1.json() == r2.json()`。它比逐个字段断言更严格，
    也正是这条纪律真正的要求：两条路径下**没有任何可观察的差别**。
    ─────────────────────────────────────────────────────────
    """
    await register(api, "真实存在的人")

    wrong_password = await api.post(
        "/auth/login", json={"username": "真实存在的人", "password": "不是这个密码"}
    )
    no_such_user = await api.post(
        "/auth/login", json={"username": "根本没注册过", "password": PASSWORD}
    )

    assert wrong_password.status_code == 401
    assert no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()
    assert wrong_password.json()["code"] == "INVALID_CREDENTIALS"


# ── /me ───────────────────────────────────────────────────────


async def test_me_返回用户与积分总览(api: httpx.AsyncClient) -> None:
    """`GET /me` → `{user, credit_account}`。"""
    session = await register(api, "看自己的人")
    res = await api.get("/me", headers=auth(session["token"]))

    assert res.status_code == 200, res.text
    assert set(res.json()) == {"user", "credit_account"}
    assert res.json()["user"]["username"] == "看自己的人"
    assert res.json()["credit_account"]["balance"] == 50


async def test_me_的响应里绝不能有_available(api: httpx.AsyncClient) -> None:
    """⚠️ 契约守卫：`available` 由前端现算（`balance − frozen`），服务端不发。

    【为什么这条要读原始 JSON 文本而不是读 key】因为「没这个字段」
    和「有这个字段但值是 null」在前端是一条 `containsKey` 的差别，
    而这里要证明的是**服务端一个字都没往下发**。直接扫文本最直接。
    """
    session = await register(api, "查字段的人")
    raw = (await api.get("/me", headers=auth(session["token"]))).text

    assert "available" not in raw, f"/me 的响应里出现了 available：{raw}"


async def test_没有_token_时_me_是_401_UNAUTHORIZED(api: httpx.AsyncClient) -> None:
    """缺 token 是 **401**，不是 403。

    【为什么这条值得单独测】FastAPI 的 `HTTPBearer` 默认在缺头时抛
    **403** + `{"detail": ...}` —— 两个都错：403 的语义是「你不该看」，
    而这里是「你还没登录」；`{"detail":...}` 又是默认信封，
    前端读不到 `code`。所以 `deps.py` 里关掉了 `auto_error`。
    这条测试就是那次关闭的守卫：把 `auto_error` 改回默认值，它会红。
    """
    res = await api.get("/me")

    assert res.status_code == 401, "缺 token 必须是 401（前端靠它走登出分支）"
    assert res.json()["code"] == "UNAUTHORIZED"


async def test_伪造的_token_也是_401(api: httpx.AsyncClient) -> None:
    """签名不对的 token 不能换出任何东西。

    【为什么它和上一条不是重复】上一条走的是「没有凭据」，
    这一条走的是「有凭据但凭据是假的」—— `decode_access_token` 里
    那一段 `except PyJWTError` 是只有这条路径才执行到的代码。
    """
    res = await api.get("/me", headers=auth("not.a.jwt"))

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"
