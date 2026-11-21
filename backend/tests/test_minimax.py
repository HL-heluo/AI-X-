"""MiniMax 适配层（图生视频）—— **对着合成上游**验证我们自己那一侧（B7.x）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件能证什么、不能证什么 —— 先说清楚，免得被当成「接好了」】

`httpx.MockTransport` 是一个**合成上游**：它按我们写的剧本回信封。
所以这里绿的每一条，说的都是「**给定这种响应，我们的处置是对的**」，
而不是「MiniMax 真的会这么回」。

  **能证**：请求体拼得对不对（`content` 数组里 text 与 first_frame
           各一条、`ratio=adaptive`、`resolution`/`duration` 就位）、
           `Authorization: Bearer` 的形状、密钥没有泄漏到别处、
           状态机（queued/running 不判死）、产物地址与时长的提取、
           错误码 → `(rejected, retryable)` 的映射、
           以及**按 kind 路由**：文生图仍走图片那一路。

  **不能证**：这个密钥能不能过它的网关、`model` 名字对不对、
           文档里的字段名与实际是否一致、这个账号开通了
           「按量购买 API」没有、**以及它的服务器能不能下载到
           我们桶里的那张参考图**（那是唯一一条本地无论如何
           都证不了的事，记在 HANDOFF 的缺口里）。

后五条要等密钥（由项目所有者填进 `.env`）之后真打一次。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings, get_settings
from app.enums import TaskKind
from app.providers.base import GenerationRequest, ProviderFailure, ProviderResult
from app.providers.fake import FakeProvider
from app.providers.minimax import MinimaxProvider
from app.providers.pricing import freeze_amount, settle_amount

MM_KEY = "mm-key-test-only"
MODEL = "MiniMax-H3-Max"
SOURCE_URL = "https://cdn.example.com/u/1/7/cat.png"


# ══════════════════════════════════════════════════════════════
# 合成上游
# ══════════════════════════════════════════════════════════════


def _settings(**overrides: object) -> Settings:
    """一个「图片走 fake、视频走 MiniMax」的配置。

    【为什么不走环境变量】同 `test_jimeng_b6.py` 那段：`get_settings()`
    带 `lru_cache`，而本文件有二十几条用例。直接构造 `Settings` 就没有
    缓存污染这回事，而缓存污染的表现是「上一条用例的配置跑到下一条里
    去了」—— 那看起来像业务 bug。
    """
    base: dict[str, object] = {
        "jwt_secret": "x" * 40,
        "provider": "fake",
        "video_provider": "minimax",
        "minimax_api_key": MM_KEY,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def _provider(handler, **overrides: object) -> MinimaxProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MinimaxProvider(settings=_settings(**overrides), client=client)


def _video_request(**overrides: object) -> GenerationRequest:
    base: dict[str, object] = {
        "kind": TaskKind.image_to_video,
        "prompt": "镜头缓慢推进",
        "params": {"duration": 5, "ratio": "16:9"},
        "source_asset_id": 7,
        "source_url": SOURCE_URL,
        "requested_duration_sec": 5,
    }
    return GenerationRequest(**{**base, **overrides})  # type: ignore[arg-type]


def _two_phase(query, *, submit_body: dict | None = None, seen: list | None = None):
    """造一个**分得清提交与查询**的替身。

    ─────────────────────────────────────────────────────────
    【为什么要按「方法 + 路径」分派】

    MiniMax 的两个动作走的是**两个不同的 URL**（`POST /v2/video_generation`
    与 `GET /v2/query/video_generation/{id}`），所以判据比即梦那边清楚。

    但仍然要判 —— 写成「提交用例只回提交的响应」的话，那条用例里的
    `poll` 会拿到一个 `{"task_id": ...}`（没有 `task` 对象），于是
    它测的是「响应形状不对」那条分支，而不是它想测的那条。
    这是本文件最容易写出的**假绿**。
    ─────────────────────────────────────────────────────────
    """
    created = submit_body if submit_body is not None else {"task_id": "mm-001"}

    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.method == "POST":
            return httpx.Response(200, json=created)
        if isinstance(query, httpx.Response):
            return query
        if isinstance(query, Exception):
            raise query
        return httpx.Response(200, json=query)

    return handler


def _task(status: str, **fields: object) -> dict:
    payload: dict[str, object] = {"id": "mm-001", "model": MODEL, "status": status}
    payload.update(fields)
    return {"task": payload}


def _error_body(message: str, http_code: int) -> dict:
    """MiniMax 的错误体：**OpenAI 风格**，内部码写在 `message` 末尾括号里。"""
    return {
        "type": "error",
        "error": {
            "type": "unprocessable_entity_error",
            "message": message,
            "http_code": str(http_code),
        },
        "request_id": "req-1",
    }


# ══════════════════════════════════════════════════════════════
# 一、提交：请求体拼对了没有
# ══════════════════════════════════════════════════════════════


def test_提交体_的字段与形状都对() -> None:
    """提交体的每一个字段都按文档拼。

    ─────────────────────────────────────────────────────────
    【为什么这条非有不可，而且必须逐字段断言】

    这是**唯一**能在本地证明「我们发出去的东西长得对」的地方。
    真打一次的时候，任何一处拼错都表现为一个 400 或 422 ——
    而那种错误**读起来像我们的参数写错了**，排查要从头翻文档。

    ⚠️ 这里面最容易被写错的是 `content`：MiniMax 与即梦的形状
       **完全不同**（即梦是一个 `prompt` 字段 + 一个 `image_urls`
       数组，MiniMax 是一个多模态内容数组，图像与文本**平级**）。
       而且文档明写「所有场景都必须有一个非空 `text`」——
       只发图不发字的请求会 400。
    ─────────────────────────────────────────────────────────
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    provider.submit(_video_request(prompt="镜头缓慢推进，猫的耳朵动了一下"))

    body = json.loads(seen[0].content)
    assert seen[0].method == "POST"
    assert str(seen[0].url).endswith("/v2/video_generation")
    assert body["model"] == MODEL
    assert body["resolution"] == "768P"
    assert body["duration"] == 5
    assert body["ratio"] == "adaptive"
    assert body["content"] == [
        {"type": "text", "text": "镜头缓慢推进，猫的耳朵动了一下"},
        {
            "type": "image_url",
            "image_url": {"url": SOURCE_URL},
            "role": "first_frame",
        },
    ]


def test_用户的_ratio_进不了请求体() -> None:
    """图生视频的 `ratio` **恒为 adaptive**，哪怕 `params` 里写着 16:9。

    【为什么宁可忽略用户的输入也要写死】文档明说图生视频的宽高比由
    输入图决定，`ratio` 恒为 adaptive、传别的值「不报错但会被忽略」。
    把参数原样发过去是个**无害的谎**：它让下一个读代码的人以为
    那个值有用，于是哪天要调比例时会去改这里 —— 而真正决定比例的
    是那张参考图。
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    # `params` 里明确带了 16:9（前端真的会带这个值）
    provider.submit(_video_request())

    assert json.loads(seen[0].content)["ratio"] == "adaptive"


def test_文生视频不带_image_url_且_ratio_必填() -> None:
    """`text_to_video` 也实现对：**没有图**，而 `ratio` 必填且不能是 adaptive。

    【为什么接口今天发不出这个 kind 还要实现】见 `minimax._submit_body`
    那段：不留地雷。而这条测试保证「哪天有人打开了那个 kind」时，
    发出去的形状是对的 —— 否则第一次调用会换来一个 400，
    而那个 400 的原因（t2v 的 ratio 必填）不在任何人的脑子里。
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    provider.submit(
        _video_request(kind=TaskKind.text_to_video, source_url=None, params={})
    )

    body = json.loads(seen[0].content)
    assert body["content"] == [{"type": "text", "text": "镜头缓慢推进"}]
    assert body["ratio"] == "16:9"


def test_鉴权头是_Bearer_而且密钥不出现在别处() -> None:
    """`Authorization: Bearer <key>`，且密钥**只在**那个头里。

    ─────────────────────────────────────────────────────────
    【为什么「不出现在别处」要和「出现在那里」一起断言】

    只断言头对的话，一个把密钥同时塞进 body 或 URL 的实现照样绿 ——
    而那一刻它已经多了一条泄漏路径（URL 会进访问日志、body 会进
    对账表）。

    MiniMax 比即梦好一点：它**不签名**，所以没有「AK 进 HTTP 头」
    那条即梦特有的路径。但这不代表可以放宽 —— 密钥就是密钥。
    ─────────────────────────────────────────────────────────
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    provider.submit(_video_request())
    request = seen[0]

    assert request.headers["Authorization"] == f"Bearer {MM_KEY}"
    # 除了那一个头，整条请求的任何地方都不该出现密钥。
    for name, value in request.headers.items():
        if name.lower() == "authorization":
            continue
        assert MM_KEY not in value, f"密钥泄漏到了请求头 {name}"
    assert MM_KEY not in str(request.url)
    assert MM_KEY not in request.content.decode("utf-8", "replace")


def test_提交只回执_永远不是成品() -> None:
    """`done=False` —— 与即梦同款：产物要走「下载 → 转存 → 打标识」。

    【为什么「永远」是要紧的】`generation.dispatch` 里有一行专门看
    `result.done`：为真时它会在**同一个事务里**去搬产物。MiniMax
    的提交响应里只有 `task_id`，永远不会有 `content.url` ——
    所以这里为真的那天，就是那次调用把别人的产物地址猜成了自己的。
    """
    provider = _provider(_two_phase({"task": {}}))

    result = provider.submit(_video_request())

    assert result.done is False
    assert result.provider_url is None
    assert result.provider_task_id == "mm-001"


def test_句柄是裸_task_id_不编前缀() -> None:
    """`provider_task_id` **就是** `task_id` 本身。

    ─────────────────────────────────────────────────────────
    【为什么这条要单独钉，而且断言得这么死】

    即梦的句柄是 `req_key|task_id` —— 它**必须**编那个前缀，因为
    `GetResult` 要求把提交时的 `req_key` 再传一遍，而 `poll` 的签名里
    只有句柄。

    MiniMax 的查询接口**只要 task_id**，没有第二个要重传的东西。
    所以这里没有可编的东西。抄一份前缀过来的话：查询会带着一个
    它不认识的前缀去打，回 400 或者（更糟）查到一个别的任务 ——
    而 `tasks.provider_task_id` 是**落库的**，编错了的句柄
    在库里改不回来。
    ─────────────────────────────────────────────────────────
    """
    provider = _provider(_two_phase({"task": {}}))

    result = provider.submit(_video_request())

    assert result.provider_task_id == "mm-001"
    assert "|" not in (result.provider_task_id or "")


def test_受理了却没给_task_id_不可重试() -> None:
    """HTTP 2xx 却没有 `task_id` → 响亮失败且**不可重试**。

    【为什么不重试】成功的响应缺 id 不是抖动，是**我们对响应的理解
    和它实际的样子不一致**。重试三次会拿到三次同样的东西，
    而用户白等三倍的时间。
    """
    provider = _provider(_two_phase({"task": {}}, submit_body={}))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_video_request())

    assert caught.value.retryable is False
    assert caught.value.rejected is False
    assert "task_id" in str(caught.value)


# ══════════════════════════════════════════════════════════════
# 二、查询：状态机
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("status", ["queued", "running"])
def test_还没好是_None_不是失败(status: str) -> None:
    """`queued` / `running` → `None`。

    ─────────────────────────────────────────────────────────
    【这不是「随便返回一个空」】把「还没好」当成失败，用户的视频会
    在**生成到一半时**被判失败、退款，而 provider 那边还在跑、
    还会出片 —— 那次调用白付，而且用户看到的是一个假的失败。

    ⚠️ **它证明不了「这一支是显式写的」** —— 未知状态那条分支也返回
       `None`，所以把这两行删掉的改动在这条用例下照样是绿的
       （这是故意改坏跑一遍时发现的）。这条用例守的是**行为**：
       这两种状态不能判死。而「显式写出来」这件事的价值在于
       **保护**：哪天有人决定「未知状态一律判失败」，queued/running
       不该被一起带走 —— 那要靠下面那条未知状态的用例（它额外
       断言了 warning）和这一段注释来提醒。
    ─────────────────────────────────────────────────────────
    """
    provider = _provider(_two_phase({"task": {"id": "mm-001", "status": status}}))

    assert provider.poll("mm-001") is None


def test_查询用的路径与_G_E_T_方法都对() -> None:
    """`GET /v2/query/video_generation/{task_id}`。

    【为什么路径要单独断言】它和提交是**两个不同的端点**（不像即梦
    那样靠 `Action` 参数路由），写错了会打到提交端点上、拿到一个
    405 或一个让人看不懂的响应。
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase(_task("running"), seen=seen))

    provider.poll("mm-001")

    assert seen[0].method == "GET"
    assert str(seen[0].url).endswith("/v2/query/video_generation/mm-001")
    assert seen[0].content == b""  # GET 不带体


def test_succeeded_取出产物地址与时长() -> None:
    """成片地址取 `task.content.url`，时长取 `task.duration`。"""
    provider = _provider(
        _two_phase(
            _task(
                "succeeded",
                content={"url": "https://cdn.minimax.example.com/a.mp4"},
                duration=6,
                resolution="768P",
                ratio="adaptive",
            )
        )
    )

    result = provider.poll("mm-001")

    assert result is not None
    assert result.done is True
    assert result.provider_url == "https://cdn.minimax.example.com/a.mp4"
    assert result.output_duration_sec == 6


def test_时长取不到就是_0_而不是猜一个() -> None:
    """`task.duration` 缺失 → 0（**收得最少**那个方向）。

    【为什么方向必须是这个】计费按它算，而「多退少补」的规矩是
    以**实际**时长为准（§7.2）。真值拿不到时，凭请求时长猜一个
    意味着**多收用户的钱**；回 0 的代价是平台少收一点。
    两者的错法不一样，选那个不伤用户的。
    """
    provider = _provider(_two_phase(_task("succeeded", content={"url": "https://x/a.mp4"})))

    result = provider.poll("mm-001")

    assert result is not None
    assert result.output_duration_sec == 0


def test_succeeded_却没有地址_不可重试() -> None:
    """成功了但 `content.url` 是空的 → 响亮失败。

    【为什么不能「找不到就当失败退款了事」】那是即梦 2026-10-15
    踩过的坑的另一副面孔：那一次是「成功却判失败」，这一次是
    「成功了但交付不出东西」。两者都是**我们不该静默吞掉**的 ——
    响亮失败会留下 `error_code` 与一条 `provider_calls`，
    而静默退款什么都不留，下周还会再发生一次。
    """
    provider = _provider(_two_phase(_task("succeeded", content={})))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.retryable is False
    assert "content.url" in str(caught.value)


@pytest.mark.parametrize(
    "error",
    [
        {"code": "1004", "message": "auth failed"},
        {"message": "没有 code 的形状"},
    ],
)
def test_failed_把上游原始码带进摘要(error: dict) -> None:
    """`failed` → `ProviderFailure`，上游的原始码与话进 `meta`。

    【为什么原始码一定要留】它进 `provider_calls.resp_code`，而那是对账
    表的判据列。丢掉它的话，「今天失败的 40 条里有 38 条是同一个码」
    这件事就看不出来了 —— 那正是要修的那一个东西。
    """
    provider = _provider(_two_phase(_task("failed", error=error)))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.meta is not None
    assert caught.value.meta.resp_message == error["message"]
    assert caught.value.meta.resp_code == error.get("code")


def test_取消了的任务不可重试() -> None:
    """`cancelled` → 不可重试，与即梦的 `not_found` / `expired` 同一处置。

    【为什么它不能落到「未收录 = 可重试」上】因为再问一万次也是这个
    答案。重试它只是把「这条不会好了」这件事推迟三次确认。
    """
    provider = _provider(_two_phase(_task("cancelled")))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.retryable is False
    assert caught.value.rejected is False


def test_没见过的_status_当成还没好而且记一条警告(caplog: pytest.LogCaptureFixture) -> None:
    """未知状态 → `None` + `logging.warning`，**不在这里猜终态**。

    ─────────────────────────────────────────────────────────
    【为什么这条断言里必须有日志】

    因为「未知状态」与「还在跑」的返回值是**同一个 `None`** ——
    只断言 `is None` 的话，这段代码哪天被改成「一律返回 None」
    也照样是绿的，而那意味着成片永远交付不出来。

    这条 warning 是那个分支存在的**唯一证据**，所以它必须被钉住。

    而这里为什么**不**判死：可能是我方解析错了，也可能是它新加了
    一种状态。等 `task_timeout_sec` 兜底（会全额退款）比在这里
    猜一个终态安全 —— 猜错的代价是「片子生成到一半被判失败」。
    ─────────────────────────────────────────────────────────
    """
    provider = _provider(_two_phase(_task("processing")))

    with caplog.at_level("WARNING", logger="aivideo.providers.minimax"):
        assert provider.poll("mm-001") is None

    assert any(
        "processing" in r.getMessage() for r in caplog.records
    ), "未知 status 必须留下一条 warning，否则它和「还在跑」分不出来"


def test_响应里没有_task_对象_不可重试() -> None:
    """成功码却没有 `task` 对象 —— 同「缺 task_id」：是理解不一致，不是抖动。"""
    provider = _provider(_two_phase({"request_id": "req-1"}))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.retryable is False
    assert "task" in str(caught.value)


# ══════════════════════════════════════════════════════════════
# 三、错误码 → 处置（§7.4 / §7.5）
# ══════════════════════════════════════════════════════════════


def test_敏感内容是判拒绝且绝不重试() -> None:
    """`422` + `(1026)` → `rejected=True` + `retryable=False`（§7.4）。

    ─────────────────────────────────────────────────────────
    【§7.4 那条为什么是硬的】「内容审核未通过 → 全额退回 + 任务记
    rejected」，而重试一次已经被判不合规的输出，就是**再付一次钱**
    去买同一个结果。

    ⚠️ 1026 是**文档里逐字给出的唯一一个审核号**
       （`"video description contains sensitive content (1026)"`）。
       即梦那边「输出之后才判不合规」还有一个 50511，MiniMax 大概率
       也有一个对应号 —— 但**我们没见过它**，所以表里没有猜的条目，
       那个缺口记在 HANDOFF 里。
    ─────────────────────────────────────────────────────────
    """
    body = _error_body("video description contains sensitive content (1026)", 422)
    provider = _provider(_two_phase(httpx.Response(422, json=body)))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.rejected is True
    assert caught.value.retryable is False
    assert caught.value.meta is not None
    assert caught.value.meta.resp_code == "1026"
    assert caught.value.meta.http_status == 422


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "invalid api key (1004)"),
        (402, "insufficient balance (1008)"),
        (400, "invalid params (2013)"),
    ],
)
def test_重试没有意义的一类不可重试(status: int, message: str) -> None:
    """鉴权 / 余额 / 参数错 → **不可重试**。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【这是本批**唯一新引入**的处置方向，即梦那条链路上没有对应码】

    既有规则是「未收录的错误码一律保守判可重试」，而它对这三个是
    **错的**：

      · 鉴权失败：密钥不对，重试三次错三次 —— 只是慢了 3 倍。
        响亮失败才有人去修密钥。
      · 余额不足：我方账户没钱，重试不产生任何新信息，而每次
        重试都是一次真实的 HTTP 往返。
      · 参数错：请求是**我们**拼的。重试等于把同一个 bug 打三遍，
        还会让退避把它掩盖过去。

    ⚠️ 这三条**必须显式列在表里**，不能靠「反正状态码那张表也判不可
       重试」—— 因为内部码是从 `error.message` 末尾正则抠出来的，
       那段文本是对方的文案约定。哪天抠不出来，`code` 就是 `None`，
       这时**状态码那张表仍然兜得住**（下面那条用例钉的就是这个）。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    body = _error_body(message, status)
    provider = _provider(_two_phase(httpx.Response(status, json=body)))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.retryable is False
    assert caught.value.rejected is False


@pytest.mark.parametrize("status", [401, 402, 400])
def test_认不出内部码时靠状态码兜底(status: int) -> None:
    """`error.message` 抠不出码时，**状态码那张表仍然判不可重试**。

    【为什么要单独测这一条】内部码的正则依赖对方的文案格式（括号在
    末尾），而那不是契约。这条用例模拟「它改了文案」：处置必须不变。
    """
    body = _error_body("something went wrong", status)
    provider = _provider(_two_phase(httpx.Response(status, json=body)))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.meta is not None
    assert caught.value.meta.resp_code is None
    assert caught.value.retryable is False


@pytest.mark.parametrize("status", [429, 500, 529])
def test_限流与服务端错误可重试(status: int) -> None:
    """`429` / `5xx` / `529` → 可重试，且**不是** rejected。

    【为什么 `rejected is False` 和 `retryable is True` 一样重要】
    判成 rejected 的话，用户看到的是「换个词试试」—— 而他的词一点
    问题都没有，换什么词都还是限流。
    """
    body = _error_body("rate limited", status)
    provider = _provider(_two_phase(httpx.Response(status, json=body)))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.retryable is True
    assert caught.value.rejected is False


def test_出错的响应正文被记进摘要() -> None:
    """`>= 400` 那条分支**必须读正文**。

    ─────────────────────────────────────────────────────────
    【即梦那边 B7.3 吃过一次亏】唯独 `>= 400` 那条分支只记了状态码，
    而它恰恰是**唯一**能告诉我们病因的一类响应（密钥错、参数错、
    配额满全在这儿）—— 于是四行 `provider_calls` 的 `resp_message`
    全是 NULL，只能靠重放来查。

    MiniMax 的病因就在 `error.message` 里，还带着内部码。
    ─────────────────────────────────────────────────────────
    """
    body = _error_body("prompt rejected by policy (1026)", 422)
    provider = _provider(_two_phase(httpx.Response(422, json=body)))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.meta is not None
    assert "policy" in (caught.value.meta.resp_message or "")
    # 【而它不该进人话】人话是给用户看的（`tasks.error_msg`），
    # 对方原文只进对账表。
    assert "policy" not in str(caught.value)


def test_对账摘要里的_req_key_是响应里那个模型名() -> None:
    """`meta.req_key` 填**模型名**，而且取的是**响应里**那个。

    ─────────────────────────────────────────────────────────
    【为什么要填模型名】`provider_calls` 那张表**没有 provider 列**，
    要靠 task_id 关联 `tasks.provider` 才认得出是谁。模型名让它
    在「同一路上换过模型」之后仍然读得懂 —— 和即梦的 `req_key` 是
    同一个角色：决定单价的那个标识。

    【为什么用响应里的而不是配置里的】任务可能是**换配置之前**
    提交的。对账表要回答的是「这一次调用花在哪个模型上」，
    而响应里那个 `task.model` 才是这一次的事实。所以这里故意
    让配置值（默认 `MiniMax-H3-Max`）与响应值不同，看它取的是哪个。
    ─────────────────────────────────────────────────────────
    """
    other_model = "MiniMax-H3"
    provider = _provider(
        _two_phase(
            _task("succeeded", model=other_model, content={"url": "https://x/a.mp4"})
        )
    )

    result = provider.poll("mm-001")

    assert result is not None
    assert result.meta is not None
    assert result.meta.req_key == other_model


def test_提交时的_req_key_用的是配置里的模型名() -> None:
    """提交那一次没有「响应里的模型」可用，用配置值 —— 它就是发出去的那个。"""
    provider = _provider(_two_phase({"task": {}}))

    result = provider.submit(_video_request())

    assert result.meta is not None
    assert result.meta.req_key == MODEL


# ══════════════════════════════════════════════════════════════
# 四、网络层
# ══════════════════════════════════════════════════════════════


def test_超时归类为_timeout() -> None:
    provider = _provider(_two_phase(httpx.ConnectTimeout("慢")))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.meta is not None
    assert caught.value.meta.error_kind == "timeout"
    assert caught.value.retryable is True


def test_连不上归类为_connect() -> None:
    provider = _provider(_two_phase(httpx.ConnectError("断了")))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.meta is not None
    assert caught.value.meta.error_kind == "connect"


def test_响应不是_json_归类为_decode() -> None:
    provider = _provider(_two_phase(httpx.Response(200, text="<html>502</html>")))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("mm-001")

    assert caught.value.meta is not None
    assert caught.value.meta.error_kind == "decode"


# ══════════════════════════════════════════════════════════════
# 五、提交前就把不该发的挡住
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("seconds", [4, 1, 16, 0])
def test_时长越界在提交前就响亮失败(seconds: int) -> None:
    """H3-Max 只吃 5~15 秒，越界时**一个请求都不发**。

    ─────────────────────────────────────────────────────────
    【这条是真会碰到的】

    `schemas.VideoGenIn.duration` 是 `int = 5`，**没有上下界** ——
    所以 `POST /generation/video {"duration": 4}` 在接口层是**合法**的，
    而 H3-Max 会回一个 400（它不支持 4 秒，H3 才支持）。

    前端只发 5 和 10（`video_gen_page.dart` 的 `_durations`），所以
    线上碰不到。「碰不到」不等于「不用拦」：拦在这里的代价是一行判断，
    不拦的代价是**花掉一次真调用**换回一个我们自己拼错的请求被拒。

    ⚠️ 这里断言 `seen == []`，也就是**真的没发请求** —— 只断言
       「抛了异常」的话，一个「先发再判」的实现照样绿。
    ─────────────────────────────────────────────────────────
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_video_request(requested_duration_sec=seconds))

    assert caught.value.retryable is False
    assert seen == []


def test_图生视频缺参考图地址_响亮失败() -> None:
    """`source_url` 为空时**不发请求**。

    【为什么是硬失败而不是「让它回一个参数错误」】MiniMax 在**它自己的
    机房里**下这张图，所以它只能是一个公网 URL。没有地址就发过去的话，
    得到的是一个「参数错误 (2013)」—— 而那读起来像是我们拼错了字段，
    不是「参考图没有公网地址」。这两件事的修法完全不同。
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_video_request(source_url=None))

    assert caught.value.retryable is False
    assert seen == []


def test_文生图交给它_响亮失败() -> None:
    """`text_to_image` → 响亮失败。

    【为什么配置层已经拦了还要再拦一次】纵深防御：配置那条拦的是
    「配置写错」，这条拦的是「有人绕过配置直接把任务递进来」
    （测试、将来的批处理）。而且它可单测 —— 配置那条要动环境变量。
    """
    seen: list[httpx.Request] = []
    provider = _provider(_two_phase({"task": {}}, seen=seen))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_video_request(kind=TaskKind.text_to_image))

    assert caught.value.retryable is False
    assert "视频" in str(caught.value)
    assert seen == []


# ══════════════════════════════════════════════════════════════
# 六、计价：转手给 pricing，不许自己算
# ══════════════════════════════════════════════════════════════


def test_计价与_fake_逐字相同() -> None:
    """冻结 32 / 结算 24 —— 与 fake 逐字相同。

    【为什么这条要紧】这一批**不动计费契约**：H3-Max 的真实单价与
    这个价的差额是一个**定价决策**，留作单独一批。所以 MiniMax
    这条链路上冻的和收的必须还是老那三个数。
    """
    request = _video_request()
    mm = _provider(_two_phase({"task": {}}))
    fake = FakeProvider()

    assert mm.freeze_amount(request) == fake.freeze_amount(request) == 32
    assert mm.freeze_amount(request) == freeze_amount(request)

    result = ProviderResult(output_duration_sec=6, done=True)
    assert mm.settle_amount(request, result) == fake.settle_amount(request, result) == 24
    assert mm.settle_amount(request, result) == settle_amount(request, result)


# ══════════════════════════════════════════════════════════════
# 七、装配：按 kind 路由
# ══════════════════════════════════════════════════════════════


def test_build_provider_按_kind_路由(monkeypatch: pytest.MonkeyPatch) -> None:
    """`PROVIDER=fake` + `VIDEO_PROVIDER=minimax`：图片 fake、视频 MiniMax。

    ─────────────────────────────────────────────────────────
    【这是这一批的全部目的，所以它是本文件最该有的那条】

    在它之前，「图片走一家、视频走另一家」这件事**表达不出来** ——
    `worker` 一个 tick 只造一个 provider，然后在 `for kind in TaskKind`
    里用在所有类型上。所以 `build_provider` 长出了 `kind` 形参。

    ⚠️ 两条各断一次，而不是只断视频那一条：只断视频的话，
       「实现成——不管什么 kind 都返回 MiniMax」也能通过，
       而那意味着文生图**悄悄换了一家**（即梦那条是真外部验过的，
       动它要有理由）。
    ─────────────────────────────────────────────────────────
    """
    from app.providers import build_provider
    from app.providers.jimeng import JimengProvider

    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("VIDEO_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", MM_KEY)
    get_settings.cache_clear()
    try:
        assert isinstance(build_provider(TaskKind.text_to_image), FakeProvider)
        assert isinstance(build_provider(TaskKind.image_to_video), MinimaxProvider)
        # `text_to_video` 也要落视频那一路（接口今天发不出它，
        # 但它不是文生图，走图片 provider 是错的）。
        assert isinstance(build_provider(TaskKind.text_to_video), MinimaxProvider)
        # 图片那一路**不许**是即梦（没配密钥）—— 这一条挡的是
        # 「路由实现成按 VIDEO_PROVIDER 返回一切」。
        assert not isinstance(build_provider(TaskKind.text_to_image), JimengProvider)
    finally:
        get_settings.cache_clear()


def test_build_provider_不自己写一遍解析逻辑() -> None:
    """`build_provider` 必须调 `settings.resolved_video_provider`，
    **不许自己写 `video_provider or provider`**。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这条必须是语法层面的守卫，而不是断言行为】

    因为那两处 `or` **今天算出来是同一个值** —— 任何行为断言都是绿的。
    它们会在**将来**漂开：`resolved_video_provider` 是一个属性，谁给它
    加一条规则（第三档 provider、按 kind 的默认值……），`build_provider`
    里那份手抄的就不会跟着变。

    而错位的后果是这个仓库里最贵的一类：`model_post_init` 判的是属性
    那一个（守卫会说「配置没问题，启动吧」），运行时用的是手抄的那一个
    （真的去打另一家）。表现是「配置里写着 MiniMax，实际按即梦跑」，
    账单月底才知道。

    ⚠️ 这条**不是**我一开始想到要写的 —— 它是「故意改坏跑一遍」时
       发现的：把 `resolved_video_provider` 换成手抄的 `or`，
       `test_build_provider_按_kind_路由` 照样绿。所以这里补一条。

    【为什么用 `ast` 而不是查子串】因为 `build_provider` 的文档字符串
    **逐字写着** `settings.video_provider or settings.provider`（就是
    上面那段警告）。查子串的版本会被自己的注释骗到 —— 那个坑
    `test_pricing_b6.py` 里那条同款守卫的说明写得很清楚。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    import ast
    import inspect
    import textwrap

    from app.providers import build_provider

    tree = ast.parse(textwrap.dedent(inspect.getsource(build_provider)))
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }

    assert "resolved_video_provider" in attributes, (
        "`build_provider` 没有调 `settings.resolved_video_provider` —— "
        "它多半在自己写一遍 `video_provider or provider`，那会和 "
        "`model_post_init` 的判据漂开。"
    )
    assert "video_provider" not in attributes, (
        "`build_provider` 直接读了 `settings.video_provider` —— "
        "解析逻辑只准有一处，就是 `Settings.resolved_video_provider`。"
    )


def test_没设_VIDEO_PROVIDER_时视频跟随图片(monkeypatch: pytest.MonkeyPatch) -> None:
    """`VIDEO_PROVIDER` 缺省 = 跟随 `provider` —— **既有部署零行为变化**。

    【为什么这条必须存在】它是这次改动的**兼容性断言**。2026-10-16
    之前只有一种形态（一个 provider 管全部），而那种部署今天照旧
    必须工作：不设 `VIDEO_PROVIDER` 的话，视频那一路和图片那一路
    是同一个实现。
    """
    from app.providers import build_provider

    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.delenv("VIDEO_PROVIDER", raising=False)
    get_settings.cache_clear()
    try:
        assert type(build_provider(TaskKind.text_to_image)) is FakeProvider
        assert type(build_provider(TaskKind.image_to_video)) is FakeProvider
    finally:
        get_settings.cache_clear()


def test_配了_minimax_视频却没有密钥_启动就炸() -> None:
    """**进程起不来**，而不是等到第一次出片才失败。

    【为什么这条比它看起来重要】缺密钥的部署会**正常启动**、
    `/health` 正常、测试全绿 —— 然后在第一次出片时花掉一次真调用
    换回一个 401。那笔钱不多，但它是**在能事前拦住的情况下花掉的**。
    """
    with pytest.raises(ValueError) as caught:
        _settings(minimax_api_key="")

    assert "MINIMAX_API_KEY" in str(caught.value)


def test_拿_MiniMax_当图片_provider_启动就炸() -> None:
    """`PROVIDER=minimax` → 报错，消息里指出路。

    【为什么是硬拒而不是静默回退】MiniMax 在本仓库**只有视频**
    （文生图是另一套接口 `POST /v1/image_generation`，v1 没接）。
    静默回退到 fake 的话，一个以为「全平台换 MiniMax」的部署会看到
    文生图照常出图 —— 只是出的是假的图，而成本表上两笔账从此分不开。
    """
    with pytest.raises(ValueError) as caught:
        _settings(provider="minimax", video_provider=None)

    assert "VIDEO_PROVIDER" in str(caught.value)


def test_图片走即梦时_视频配_minimax_也合法() -> None:
    """`PROVIDER=jimeng` + `VIDEO_PROVIDER=minimax` —— 这是本批的推荐配置。

    【为什么它要单独一条】因为 `model_post_init` 里那两条即梦守卫
    （AK/SK、两个 req_key）**只该管图片那一路**。判据写错的话，
    一个「图片即梦、视频 MiniMax」的部署会因为缺 `JIMENG_REQ_KEY_VIDEO`
    而起不来 —— 而视频那一路根本不用那个键。
    """
    settings = _settings(
        provider="jimeng",
        jimeng_ak="ak",
        jimeng_sk="sk",
        jimeng_req_key_image="rk-image",
        # ⚠️ `jimeng_req_key_video` **故意留空**：视频那一路是 MiniMax。
        jimeng_req_key_video="",
    )

    assert settings.image_provider.value == "jimeng"
    assert settings.resolved_video_provider.value == "minimax"


# ══════════════════════════════════════════════════════════════
# 八、端到端：走完接口，看 `tasks.provider` 落的是谁
# ══════════════════════════════════════════════════════════════
#
# ── 【为什么这一段要自己搭 app / api 夹具】────────────────────
#
# `conftest.py` 的 `api_app` 在造 app 之前只设了几个数据库/目录类的
# 环境变量，而这一组用例还要 `PROVIDER` / `VIDEO_PROVIDER` /
# `MINIMAX_API_KEY` 在**配置被读之前**就位。
#
# 让 `api_app` 依赖一个本模块的夹具是不行的：那要改 conftest，
# 而 conftest 是所有人共用的。覆盖 conftest 的同名夹具（pytest
# 允许，module 级优先）也能work，但那样读的人会以为它还是原来那个。
# 所以这里**照抄一份**，并把差异摊开写清楚。
# ─────────────────────────────────────────────────────────


@pytest.fixture
def routing_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`PROVIDER=fake` + `VIDEO_PROVIDER=minimax` 的 app，连临时库。"""
    from app.database import reset_engine
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'route.db').as_posix()}")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("PROVIDER_SPOOL_ROOT", str(tmp_path / "spool"))
    monkeypatch.setenv("TEST_MODE", "1")
    # ── 这一组就是与 `api_app` 的全部差异 ──────────────────────
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("VIDEO_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", MM_KEY)

    # ⚠️ 顺序不能反：先清配置缓存，再丢引擎（同 `conftest` 那段）。
    get_settings.cache_clear()
    reset_engine()

    yield create_app()

    reset_engine()
    get_settings.cache_clear()


@pytest.fixture
async def routing_api(routing_app):
    transport = httpx.ASGITransport(app=routing_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/__test/reset")
        assert res.status_code == 200, res.text
        yield c


@pytest.fixture
def routing_session(routing_api):
    from app.database import get_session_factory

    with get_session_factory()() as s:
        yield s


@pytest.fixture
def fake_minimax_upstream(monkeypatch: pytest.MonkeyPatch):
    """把 MiniMax 的进程级 HTTP 客户端换成**合成上游**。

    ─────────────────────────────────────────────────────────
    【这一步为什么必需，而不是可选】

    `submit` 那一步是真的会发 HTTP 的（`generation.submit` 在有闸门
    空位时当场 `dispatch`）。不换掉的话，这组用例会去打
    `api.minimax.cn` —— 而它带的是一个假密钥，所以结果是一个 401，
    看起来像鉴权坏了。

    这也正是「`build_provider` 造出来的实例要用进程级客户端」那条
    设计的用处：测试**不需要**注入实例就能拦住它。
    ─────────────────────────────────────────────────────────
    """
    import app.providers.minimax as mm

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={"task_id": "mm-live-1"})
        return httpx.Response(200, json=_task("running"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(mm, "_http_client", lambda: client)
    return client


async def test_端到端_两条路各走各的(
    routing_api, routing_session, fake_minimax_upstream
) -> None:
    """提交一条文生图 + 一条图生视频，看 `tasks.provider` 分别落的是谁。

    ─────────────────────────────────────────────────────────
    【它证的是整条链路上的一句话】

    「`tasks.provider` 是按 **kind** 定的」—— 这一列是对账表的入口
    （`provider_calls` 没有 provider 列，要靠它关联才认得出是谁），
    所以它落错的那一刻，成本表就已经在骗人了。

    【它不走完 worker】因为这一段要证的是**提交**这一跳的路由，
    而 worker 那一跳（② 问进度、③ 出队）另有 `_provider_for`，
    由 `test_worker_按_kind_取_provider` 在单元层面钉住。
    走完整的 worker 需要造参考图字节、转存、抽帧…… 那些与
    「谁在跑」无关，只会让这条用例里真正想看的那两行被埋掉。
    ─────────────────────────────────────────────────────────
    """
    from _helpers import auth, new_user, submit_image, submit_video
    from app.models import Task

    headers, _ = await new_user(routing_api, "路由验证的人")

    # ── 文生图：图片那一路 ────────────────────────────────────
    res = await submit_image(routing_api, headers, idempotency_key="k-img")
    assert res.status_code == 200, res.text
    image_task_id = res.json()["id"]

    # ── 图生视频：视频那一路 ─────────────────────────────────
    up = await routing_api.post(
        "/uploads/image",
        files={"file": ("ref.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")},
        headers=headers,
    )
    assert up.status_code == 200, up.text
    res = await submit_video(
        routing_api,
        headers,
        source_asset_id=up.json()["asset_id"],
        idempotency_key="k-vid",
        duration=5,
    )
    assert res.status_code == 200, res.text
    video_task_id = res.json()["id"]

    assert routing_session.get(Task, image_task_id).provider == "fake"
    assert routing_session.get(Task, video_task_id).provider == "minimax"


def test_worker_按_kind_取_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_provider_for`：**注入优先**，没注入才按 kind 现造。

    ─────────────────────────────────────────────────────────
    【为什么要单测这一个私有函数】

    因为它是 worker 那条链路上「谁在跑」的唯一判据，而它的两种输入
    （有注入 / 没注入）在端到端用例里只会走到一种。

    更要紧的是**注入优先那一半**：被测代码里那一行是 `injected or
    build_provider(kind)`，而 `or` 的左边一旦被写成 `build_provider(kind)`
    的实参、或者 `injected` 被当成「某个 kind 的替身」，测试注入的
    剧本替身就会**被顶掉**，于是用例真的去连了配置里那家网关 ——
    它不会报错，只会变慢或变红，而红的原因看起来像业务 bug。

    ⚠️ 这里显式设环境变量，不依赖进程当前是什么配置：`.env` 里可能
       配着真 provider，那样断言会随机器的配置漂。
    ─────────────────────────────────────────────────────────
    """
    from app.worker import _provider_for

    injected = FakeProvider()

    assert _provider_for(injected, TaskKind.text_to_image) is injected
    assert _provider_for(injected, TaskKind.image_to_video) is injected

    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("VIDEO_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", MM_KEY)
    get_settings.cache_clear()
    try:
        assert isinstance(_provider_for(None, TaskKind.text_to_image), FakeProvider)
        assert isinstance(_provider_for(None, TaskKind.image_to_video), MinimaxProvider)
    finally:
        get_settings.cache_clear()
