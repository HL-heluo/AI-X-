"""契约形状的守卫 —— **读原始 JSON 文本**，不读解析后的对象。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么单独一个文件，而且一律扫文本】

因为这里守的是**服务端一个字都不许往下发**的东西：

  · `available` —— 前端自己算 `balance − frozen`（两处都算迟早会不一致）
  · `provider_url` —— 即梦的产物地址只活 1 小时，App 永远不该碰它
  · `storage_key` —— 我们对象存储里的内部路径，换存储时只该改它

「这个字段的值为 null」和「这个字段根本不存在」在**按 key 断言**的
测试里是同一件事。而契约要的是后者，所以这里直接扫响应体原始文本。

【为什么这些字段会不小心冒出来】因为它们都是**方便**的字段：
`CreditAccount.available` 在模型上就是一个 property，
`Asset.storage_key` 是同一行上现成的一列。哪天有人给响应模型开了
`from_attributes=True`，它们会**自动**被序列化进去，而功能测试
一条都不会红 —— 所以必须有这样一组守卫。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from _helpers import grant_credits, new_user, submit_image, submit_video

FORBIDDEN = ("available", "provider_url", "storage_key", "params_json")
"""绝不能出现在任何响应体里的键名。

【为什么 `params_json` 也在列】它是**列名**。对外那个字段叫 `params`
且必须是**对象**（前端 `TaskParams.fromJson` 优先读对象形式）。
哪天有人顺手把 ORM 对象直接丢进 `response_model`，冒出来的就是它 ——
而前端会静默退回读字符串那一支，`ratio` 就显示不出来了。
"""


async def _all_bodies(api: httpx.AsyncClient) -> dict[str, str]:
    """把 12 个端点**全打一遍**，返回「名字 → 原始响应体」。

    【为什么要全打，而不是只在几条上扫】因为漏一个字段的方式
    通常是「某个端点的响应模型多继承了一层」—— 只在 `/me` 上扫的话，
    `/assets` 上冒出来的 `storage_key` 是扫不到的。
    """
    headers, session = await new_user(api, "要走遍所有端点的人")
    # 这条用例要「全打一遍」，而其中两个视频提交各要冻 32 —— 注册送的
    # 50 撑不到最后。先补足，免得扫描集合里混进几个**错误体**
    # （那样扫的就不是响应形状，而是错误形状了）。
    await grant_credits(api, "要走遍所有端点的人", 500)
    asset_id = (
        await api.post(
            "/uploads/image",
            files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"x" * 32, "image/png")},
            headers=headers,
        )
    ).json()["asset_id"]
    task = (await submit_image(api, headers)).json()
    video = (await submit_video(api, headers, source_asset_id=asset_id)).json()

    responses = {
        "register": await api.post(
            "/auth/register",
            json={"invite_code": "MOCK", "username": "另一个", "password": "pw123456"},
        ),
        "login": await api.post("/auth/login", json={"username": "另一个", "password": "pw123456"}),
        "me": await api.get("/me", headers=headers),
        "ledger": await api.get("/credits/ledger", headers=headers),
        "cost": await api.get("/generation/cost?kind=image_to_video&duration=5"),
        "generation_image": await submit_image(api, headers, idempotency_key="shape-1"),
        "generation_video": await submit_video(
            api, headers, source_asset_id=asset_id, idempotency_key="shape-2"
        ),
        "tasks": await api.get("/tasks", headers=headers),
        "task_detail": await api.get(f"/tasks/{task['id']}", headers=headers),
        "task_cancel": await api.post(f"/tasks/{video['id']}/cancel", headers=headers),
        "assets": await api.get("/assets", headers=headers),
        "assets_upload": await api.post(
            "/uploads/image",
            files={"file": ("b.png", b"\x89PNG\r\n\x1a\n" + b"y" * 32, "image/png")},
            headers=headers,
        ),
        "health": await api.get("/health"),
    }
    assert session["token"]
    return {name: res.text for name, res in responses.items()}


@pytest.mark.parametrize("key", FORBIDDEN)
async def test_任何响应里都不能出现这几个键(api: httpx.AsyncClient, key: str) -> None:
    """⚠️ 契约守卫：`available` / `provider_url` / `storage_key` / `params_json`。

    见本文件头。这条用例的写法刻意很「粗」（扫文本），因为它守的
    正是那种**功能全对、形状多一个字段**的改动。
    """
    bodies = await _all_bodies(api)

    for name, raw in bodies.items():
        assert key not in raw, f"{name} 的响应里出现了 {key!r}：{raw[:400]}"


async def test_错误体没有信封(api: httpx.AsyncClient) -> None:
    """错误响应**顶层**就是 `{code, message}`，不是 `{detail: ...}`。

    ─────────────────────────────────────────────────────────
    【为什么这条是整批最重要的一条】

    前端 `DioApiClient._toException` 从响应体**顶层**读 `code` 和
    `message`。形状错了的话，它读出来两个都是 null，于是
    `AppException.code == null`，UI 退回到那句什么都解释不了的
    「服务端返回 HTTP 4xx，且响应体里没有 message 字段」。

    而这条契约的真正分量在于：**错误码打错一个字母，用户听到的就是
    一句谎话** —— 认不出 `INVITE_INVALID` 的前端会显示
    「连不上服务器，检查一下网络再试」，而网络好得很。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "看错误体的人")

    res = await api.post("/generation/image", json={"prompt": "  "}, headers=headers)

    assert res.status_code == 400
    body = res.json()
    assert set(body) == {"code", "message"}, f"错误体多了/少了字段：{body}"
    assert "detail" not in body


async def test_幂等冲突的错误体里带着_task(api: httpx.AsyncClient) -> None:
    """`DUPLICATE_REQUEST` 是**唯一**一个顶层多一个字段的错误。

    【为什么它必须多这一个】§12.3 写着这个码的客户端行为是
    「静默复用已存在的任务」。不带 task 的话，客户端只知道重了、
    不知道重的是哪一个 —— 前端 `_submitOrReuse` 明确拒绝
    「随便造一个空任务糊过去」，于是用户会看到一次莫名其妙的
    「生成失败」，而其实任务已经在跑。

    ⚠️ 这个额外字段必须由**异常处理器**直接产出，不能走 `response_model`
    —— 那样它会被过滤掉，而这正是它存在的意义。
    """
    headers, _ = await new_user(api, "看冲突体的人")
    await submit_image(api, headers, idempotency_key="dup")

    body = (await submit_image(api, headers, idempotency_key="dup")).json()

    assert set(body) == {"code", "message", "task"}
    assert isinstance(body["task"]["id"], int)


async def test_所有_id_都是_JSON_整数(api: httpx.AsyncClient) -> None:
    """⚠️ 前端的 `requireInt()` 对字符串会**抛异常**。

    ─────────────────────────────────────────────────────────
    【为什么这条必须读原始文本、不能读 `res.json()`】

    因为我要断言的是「**JSON 里它就是数字**」—— `"id": 1` 而不是
    `"id": "1"`。解析之后再 `isinstance(x, int)` 也能测，
    但那测的是 Python 侧的转换；扫文本扫的是**真的发出去的那几个字节**。

    这条不是洁癖：`requireInt` 抛的是 `FormatException`，而它没有
    被任何地方捕获 —— 表现是**整个页面白屏**，而服务端日志全绿。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "看 id 类型的人")
    await submit_image(api, headers)
    asset_id = (
        await api.post(
            "/uploads/image",
            files={"file": ("c.png", b"\x89PNG\r\n\x1a\n" + b"z" * 32, "image/png")},
            headers=headers,
        )
    ).json()["asset_id"]
    assert asset_id

    for path in ("/me", "/tasks", "/assets", "/credits/ledger"):
        raw = (await api.get(path, headers=headers)).text
        assert not re.search(r'"(id|user_id|task_id|asset_id)":\s*"', raw), (
            f"{path} 里有被序列化成字符串的 id：{raw[:300]}"
        )


async def test_is_ai_generated_是真的布尔(api: httpx.AsyncClient) -> None:
    """⚠️ `boolOr` 对 `'true'` 和 `1` **都抛异常** —— 它刻意不接受
    「像布尔的东西」。

    【为什么这条不是小事】`is_ai_generated` 是《人工智能生成合成
    内容标识办法》要求的那条义务字段（§10.1）。前端专门为它写了
    一个**严格**的解析器（`boolOr` 的注释里写着「不接受 'true' 和 1」），
    就是怕某天有人「顺手」把它变成字符串 —— 那样整页崩掉，
    而不是静默地把 AI 标识丢掉。两边都在守同一个东西。
    """
    headers, _ = await new_user(api, "看布尔的人")
    await submit_image(api, headers, idempotency_key="bool-1")

    raw = (await api.get("/assets", headers=headers)).text

    # 用正则而不是找 `"is_ai_generated": true` 这个字面量：FastAPI 序列化
    # 出来的是**紧凑** JSON（冒号后没有空格），钉死空格会让这条用例
    # 在某次换序列化器时莫名其妙地红。
    assert re.search(r'"is_ai_generated":\s*true\b', raw), raw[:300]
    assert not re.search(r'"is_ai_generated":\s*("|\d)', raw), (
        f"is_ai_generated 必须是真布尔：{raw[:300]}"
    )


async def test_所有时间戳都是带_Z_的_UTC(api: httpx.AsyncClient) -> None:
    """⚠️ 时间戳必须带时区，而且是 UTC。

    ─────────────────────────────────────────────────────────
    【为什么这条能防一个真实存在过的 8 小时偏差】

    前端 `asDateTimeOrNull` 解析之后会 `.toUtc()`。如果服务端存的是
    **naive** 时间（没有时区），Dart 会按**本机时区**解释它，
    再转成 UTC —— 在 UTC+8 的机器上，用户看到的时间就整整差 8 小时，
    而服务端、数据库、日志三处全都是对的。这类 bug 表现为
    「时间显示不对」但查不出是谁的错。

    这一列的形状由 `app/types.py` 的 `UtcDateTime` 保证（两个方向都
    强制转成 tz-aware UTC）。这条测试是那道保证的守卫：
    有人把它换回裸 `DateTime` 时，这里会红。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "看时间的人")
    await submit_image(api, headers)

    for path in ("/me", "/tasks", "/credits/ledger"):
        body = (await api.get(path, headers=headers)).json()
        stamps = re.findall(r'"\w+_at":\s*"([^"]+)"', json.dumps(body))
        assert stamps, f"{path} 里一个时间戳都没有，这条用例就没在测东西"
        for stamp in stamps:
            assert stamp.endswith("Z") or stamp.endswith("+00:00"), (
                f"{path} 里的 {stamp!r} 不是 UTC —— 不带时区会让前端差 8 小时"
            )


async def test_openapi_里十二条端点都在(api: httpx.AsyncClient) -> None:
    """§12.1 的 12 个端点一个都不能少。

    【为什么用端点清单来验，而不是逐条写功能测试】功能测试证明的是
    「这条能用」，这条证明的是「**没有漏掉**」—— 前者不会因为
    少了一个端点而红。
    """
    spec = (await api.get("/openapi.json")).json()
    paths = spec["paths"]

    expected = [
        "/auth/register",
        "/auth/login",
        "/me",
        "/credits/ledger",
        "/uploads/image",
        "/generation/image",
        "/generation/video",
        "/generation/cost",
        "/tasks",
        "/tasks/{task_id}",
        "/tasks/{task_id}/cancel",
        "/assets",
        "/assets/{asset_id}",
    ]

    missing = [path for path in expected if path not in paths]
    assert missing == [], f"这些端点不见了：{missing}"
    # 13 条 = §12.1 的 12 个业务端点 + DELETE /assets/{id}
    # （文档把资产的查与删写在一行，实际是两条）。
    assert len(paths) >= len(expected)


async def test_settled_amount_未结算时是_null_不是_0() -> None:
    """⚠️ `null` 与 `0` 的语义差别 —— 这条是**故意不经过 HTTP** 的。

    ─────────────────────────────────────────────────────────
    【为什么在 B2 里拿不到这个状态】

    走 fake provider 时所有任务提交即成功，所以每个任务的
    `settled_amount` 都已经有值了 —— 通过接口**造不出**一个未结算的任务。
    （真实排队要等 B3。）所以这条只能在模型层验。

    【为什么它必须存在】

    `None` 和 `0` 在 JSON 里是两个不同的东西，而它们在这条业务上
    差得很远：

      · `null` = 「还没结算，钱还冻着」—— 用户看到的是「预计扣 32」
      · `0`    = 「结算了，一分没花」—— 用户看到的是「免费」

    前端 `asIntOrNull` 对两者同样处理（都是「没有值」），所以把它
    改成 0 时，**功能测试一条都不会红**。而数据库那边有一条约束
    钉着它（`ck_tasks_succeeded_implies_settled`）：succeeded 的任务
    必须有 settled_amount —— 于是「0」会被当成合法的已结算值，
    一个本该退钱的任务就悄悄变成了一分不花。

    把 `None` 写成 `0` 是这条代码上最容易犯的「顺手改」，所以它在
    这里被单独钉一次。
    ─────────────────────────────────────────────────────────
    """
    from app.enums import TaskKind, TaskStatus
    from app.models import Task
    from app.schemas import TaskOut
    from app.types import utcnow

    task = Task(
        id=1,
        user_id=1,
        kind=TaskKind.text_to_image,
        status=TaskStatus.pending,
        provider="fake",
        prompt="还没结算",
        params_json="{}",
        freeze_amount=32,
        settled_amount=None,
        created_at=utcnow(),
    )

    dumped = TaskOut.from_task(task, queue_position=3).model_dump(mode="json")

    assert dumped["settled_amount"] is None, "未结算必须是 null（不是 0）"
    # 排队位次由**调用方**算好传进来，见 `TaskOut.from_task` 的注释。
    assert dumped["queue_position"] == 3
    assert "provider_url" not in dumped
    assert TaskOut.from_task(task, queue_position=None).model_dump()["queue_position"] is None


async def test_响应里不带任何多余字段(api: httpx.AsyncClient) -> None:
    """逐字对齐：`MeOut` 就两个键、`CreditAccountOut` 就三个键。

    【为什么把「不多不少」也钉住】多出来的字段不会让前端崩，
    所以它不会被任何功能测试发现。但它会把契约慢慢撑大 ——
    而契约一旦被撑大，前端就会开始依赖那些字段，然后某次
    后端重构把它们删掉，两边就再也对不上了。
    """
    headers, _ = await new_user(api, "看键集合的人")

    me = (await api.get("/me", headers=headers)).json()

    assert set(me) == {"user", "credit_account"}
    assert set(me["user"]) == {"id", "username", "created_at"}
    assert set(me["credit_account"]) == {"balance", "frozen", "updated_at"}


async def test_上传响应的键集合(api: httpx.AsyncClient) -> None:
    """`UploadOut` 就 `asset_id` + `public_url`（见 §12.1 的矛盾与取舍）。"""
    headers, _ = await new_user(api, "看上传键的人")

    body = (
        await api.post(
            "/uploads/image",
            files={"file": ("d.png", b"\x89PNG\r\n\x1a\n" + b"z" * 32, "image/png")},
            headers=headers,
        )
    ).json()

    assert set(body) == {"asset_id", "public_url"}


def test_枚举清单不含任何不在契约里的状态() -> None:
    """`TaskStatus` 的 8 个值必须与前端 `task_status.dart` **逐字一致**。

    【为什么这条是硬约束】前端 `TaskStatus.fromWire` 认不出来会**抛异常**
    （它拒绝静默退化）。所以后端多一个公开状态，用户看到的不是
    「未知状态」而是**白屏** —— 这就是 `TransferState` 为什么
    要藏在 `submitted` 后面的原因（§9.3 那个第 9 个状态）。
    """
    from app.enums import TaskStatus

    assert {status.value for status in TaskStatus} == {
        "pending",
        "queued",
        "submitted",
        "succeeded",
        "failed",
        "rejected",
        "canceled",
        "expired",
    }
    assert {status.value for status in TaskStatus if status.is_terminal} == {
        "succeeded",
        "failed",
        "rejected",
        "canceled",
        "expired",
    }


async def test_健康检查说明了连的是哪个_provider(api: httpx.AsyncClient) -> None:
    """接后端那天，第一件事就是打 `/health` 确认连对了环境。

    【为什么它和上面那条「不能泄漏密钥」不冲突】`provider` / `storage`
    是**能力开关**，不是密钥 —— 它们决定「生成出来的东西是真的还是假的」，
    而这正是接错环境时最需要立刻看见的东西。AK/SK 则一个字都不能出现。
    """
    body = (await api.get("/health")).json()

    assert body["provider"] == "fake"
    assert body["storage"] == "local"
    assert body["status"] == "ok"
