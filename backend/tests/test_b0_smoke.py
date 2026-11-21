"""B0 冒烟：骨架真的立起来了，而且该挡的地方挡住了。

这一组测的是**地基**，不是业务 —— 业务从 B1 开始。
但地基里有两条是安全性质的，必须从第一天就有守卫，不能等：

  · `/__test/*` 在 `TEST_MODE` 关着时**必须不存在**（不是「返回 403」，
    是路由表里查无此路）。它能把积分凭空造出来，也能把库删掉。
  · `/health` 是公开可达的，所以它**一个密钥都不能漏**。
"""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI

# ── 骨架 ──────────────────────────────────────────────────────


async def test_health_回报了连的是哪个环境(client: httpx.AsyncClient) -> None:
    """`/health` 的五个字段一个都不能少。

    【为什么每个字段都要断】因为这个接口存在的**全部意义**就是回答
    「这个进程连的是谁」。前端接后端时第一件事就是打它，用来确认
    自己连对了环境。少一个字段，那个确认就少一块依据。
    """
    r = await client.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"], "版本号不能是空的"
    assert body["env"] == "test", f"夹具设了 APP_ENV=test，实际是 {body['env']!r}"
    # 【为什么要断言 provider 是 fake】见 conftest 里的说明：测试**永远**
    # 不该打真即梦。这条断言就是那道闸门 —— 一旦有人把 .env 里的
    # PROVIDER 带进了测试，这里立刻红，而不是某天悄悄花了钱。
    assert body["provider"] == "fake"
    assert body["storage"] == "local"


async def test_health_不泄漏任何密钥(client: httpx.AsyncClient) -> None:
    """`/health` 是公开的，塞进任何密钥都是事故。

    【为什么用「扫描整个响应体文本」而不是逐个字段查】因为将来有人
    往这个接口里加字段时，最容易加进去的就是「当前配置摘要」这种
    顺手的东西。按文本扫，比逐个字段断言更能挡住那类改动。

    【为什么必须按词边界匹配，而不是 `term in raw`】
    这条测试的第一版就是 `term in raw`，然后它红了 —— 因为
    `"provider": "fake"` 里的 **fake 含 ak**。一个纯子串扫描会把
    合法值当成泄漏，于是要么测试被删掉（最坏），要么开始往
    白名单里加特例（也很坏，白名单会长到没人看）。

    所以这里用**起始词边界**：`\\bak` 匹配 `"ak":"<某串密钥>"` 这种真正的
    泄漏，但不匹配 `fake`。只钉起始边界、不钉结尾，是因为真实泄漏
    几乎总是带后缀的（`jwt_secret`、`ak_id`、`password_hash`），
    而 `\\bjwt\\b` 反而会漏掉 `jwt_secret`（`_` 也算词字符）。
    """
    raw = (await client.get("/health")).text.lower()

    for term in ("secret", "jwt", "ak", "sk", "password", "token", "database_url"):
        assert not re.search(rf"\b{re.escape(term)}", raw), (
            f"/health 的响应里出现了 {term!r} 打头的字段：{raw}"
        )


async def test_文档页与_openapi_都在(client: httpx.AsyncClient) -> None:
    """`/docs` 与 `/openapi.json` 是 B0 的门禁之一。

    【为什么要连 openapi 一起验】`/docs` 是个静态 HTML 壳子，它
    **真的能不能用**取决于 `/openapi.json` 出得来。只验 `/docs` 返回 200
    的话，schema 生成炸了也照样绿。
    """
    assert (await client.get("/docs")).status_code == 200

    spec = (await client.get("/openapi.json")).json()
    assert spec["info"]["title"] == "AI 视频创作平台"
    assert "/health" in spec["paths"], list(spec["paths"])


# ── 测试接口的硬门禁 ──────────────────────────────────────────


async def test_TEST_MODE_开着时测试接口可达(client: httpx.AsyncClient) -> None:
    """先确认正向：开着的时候它确实在。

    【为什么要先测正向】否则下面那条反向断言可能只是「这个接口
    根本就没实现过」而已 —— 那样它也会绿，而且绿得毫无意义。
    """
    r = await client.get("/__test/ping")
    assert r.status_code == 200, "TEST_MODE=1 时 /__test/ping 应当可达"


def test_TEST_MODE_关着时测试接口在路由表里根本不存在(make_app: object) -> None:
    """⚠️ 安全守卫：`TEST_MODE=0` 时 `/__test/*` 必须查无此路。

    ─────────────────────────────────────────────────────────
    【为什么断言的是「不在路由表里」，而不是「返回 404」】

    两者在 HTTP 层看起来一模一样，但含义差很远：

      · **不注册** → 这个路径不存在。将来某次重构把那个 `if` 挪走了，
        改动的意图是可见的（要删掉一行 `return`）。
      · **注册了但抛错 / 返回 403** → 路径存在。某次重构顺手把那个
        `if` 挪到函数体里、或改成「记个日志继续」，**接口就静默地开了**，
        而 HTTP 层看到的现象从 403 变成 200，没人会去注意。
    ─────────────────────────────────────────────────────────
    """
    app: FastAPI = make_app(TEST_MODE="0")  # type: ignore[operator]

    paths = [getattr(r, "path", "") for r in app.routes]
    leaked = [p for p in paths if p.startswith("/__test")]
    assert leaked == [], f"TEST_MODE=0 却注册了测试路由：{leaked}"


@pytest.mark.parametrize("value", ["0", "false", "False", "no", ""])
def test_TEST_MODE_的各种假写法都要关掉(make_app: object, value: str) -> None:
    """`TEST_MODE` 是**配置值的字符串**，而人对「关」的写法很不一致。

    【为什么这条值得测】环境变量永远是字符串。如果有人写
    `TEST_MODE=False`，而代码里是 `bool(raw)` 那种判断，
    `bool("False")` 是 **True** —— 于是「我明明关了」变成了开着。
    这里把几种常见的「假」写法都钉一遍。

    ⚠️ 其中 `""`（留空）这一档最初是**红的**：pydantic 把它当成
    「提供了一个空串」而不是「没写」，于是 app 直接起不来，报一句
    `Input should be a valid boolean`。修法是 `env_ignore_empty=True`
    （见 app/config.py），那同时也堵上了 JWT_SECRET 留空的洞
    —— 见下面那条。
    """
    app: FastAPI = make_app(TEST_MODE=value)  # type: ignore[operator]
    paths = [getattr(r, "path", "") for r in app.routes]
    assert [p for p in paths if p.startswith("/__test")] == [], (
        f"TEST_MODE={value!r} 应当关闭测试接口"
    )


# ── 密钥防线 ──────────────────────────────────────────────────


def test_JWT_SECRET_留空也必须启动失败(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ 安全守卫：`JWT_SECRET=`（留空）不是「用默认密钥」，是「起不来」。

    ─────────────────────────────────────────────────────────
    【为什么这条非有不可】

    `JWT_SECRET` 没有默认值，缺了会启动失败 —— 这是本项目密钥防线的
    核心。但**「缺了」和「留空」是两件事**：`.env` 里写一行
    `JWT_SECRET=`，pydantic 收到的是一个空串，而空串对 `str` 类型
    是完全合法的。于是：

        服务正常启动 → 用一把空密钥签发 token → 任何人都能伪造登录态

    而更要命的是**没有任何迹象**：日志正常、`/health` 正常、
    测试全绿。这条防线在「最容易被触发的写法」上本来是失效的。

    修法是 `SettingsConfigDict(env_ignore_empty=True)`：空值一律
    按「没提供」处理，于是必填项老老实实报「字段缺失」。
    ─────────────────────────────────────────────────────────
    """
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("JWT_SECRET", "")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_空白字符的密钥不算密钥(monkeypatch: pytest.MonkeyPatch) -> None:
    """`JWT_SECRET="   "`（纯空格）也要挡住。

    【为什么和上一条分开写】因为 `env_ignore_empty=True` 只处理**空串**，
    不处理纯空格 —— 那是一个同样合法、同样没用的字符串。如果它被
    当成密钥收下，等于用一把「所有人都猜得到」的密钥签发 token。
    """
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("JWT_SECRET", "   ")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


# ── 前端要在浏览器里跑 ────────────────────────────────────────


async def test_CORS_预检能过(client: httpx.AsyncClient) -> None:
    """浏览器验收（HANDOFF §9）要能跑，CORS 就得先通。

    【为什么 B0 就要验这条】因为前端是在 `flutter build web` 之后
    跑在**真 Chrome** 里的，跨源请求会被浏览器拦下。那条失败
    在前端看起来是「连不上服务器」，排查时会一路往网络配置找，
    而真正的原因只是后端少了一个响应头。
    """
    r = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204), r.status_code
    assert r.headers.get("access-control-allow-origin") in ("*", "http://localhost:5000")
