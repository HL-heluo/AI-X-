"""即梦适配层 —— **对着合成上游**验证我们自己那一侧（B6）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件能证什么、不能证什么 —— 先说清楚，免得被当成「接好了」】

`httpx.MockTransport` 是一个**合成上游**：它按我们写的剧本回信封。
所以这里绿的每一条，说的都是「**给定这种响应，我们的处置是对的**」，
而不是「即梦真的会这么回」。

  **能证**：信封的解析顺序、状态机、审计码 → 处置的映射、
           重试分类、产物地址/时长的提取、请求体里带没带该带的字段、
           `Authorization` 的形状、以及密钥没有泄漏到任何地方。

  **不能证**：签名能不能过网关、请求 JSON 的字段名对不对、
           `req_key` / 模型 id 对不对、产物字段名对不对、
           这个子账号开通了没有。

后五条要等 AK/SK（§18-2），清单在 `HANDOFF.md` 里。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings, get_settings
from app.enums import TaskKind
from app.providers.base import GenerationRequest, ProviderFailure, ProviderResult
from app.providers.jimeng import QUERY_ACTION, SUBMIT_ACTION, JimengProvider
from app.services.transfer import _local_path_for_file_url
from app.types import utcnow

AK = "AK-TEST-ONLY"
SK = "SK-TEST-ONLY"
REQ_KEY_IMAGE = "rk-image"
REQ_KEY_VIDEO = "rk-video"


# ══════════════════════════════════════════════════════════════
# 合成上游
# ══════════════════════════════════════════════════════════════


def _settings(**overrides: object) -> Settings:
    """一个「配了即梦」的配置。

    【为什么不走环境变量】`get_settings()` 带 `lru_cache`，而本文件
    有十几条用例、每条都要不同的假配置。用环境变量的话，每条都要
    `cache_clear()`，而漏掉一次就会让下一条用例拿着上一条的配置跑
    —— conftest 里那段说明写的正是这个坑。直接构造 `Settings` 就没有它。
    """
    base: dict[str, object] = {
        "jwt_secret": "x" * 40,
        "provider": "jimeng",
        "jimeng_ak": AK,
        "jimeng_sk": SK,
        "jimeng_req_key_image": REQ_KEY_IMAGE,
        "jimeng_req_key_video": REQ_KEY_VIDEO,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def _provider(handler, **overrides: object) -> JimengProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return JimengProvider(settings=_settings(**overrides), client=client)


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"code": 10000, "message": "", "data": data})


def _image_request(prompt: str = "一只在屋顶上看夕阳的猫") -> GenerationRequest:
    return GenerationRequest(
        kind=TaskKind.text_to_image, prompt=prompt, params={"aspect_ratio": "1:1"}
    )


def _video_request(**overrides: object) -> GenerationRequest:
    base: dict[str, object] = {
        "kind": TaskKind.image_to_video,
        "prompt": "镜头缓慢推进",
        "params": {"duration": 5, "ratio": "16:9"},
        "source_asset_id": 7,
        "source_url": "https://cdn.example.com/u/1/7/cat.png",
        "requested_duration_sec": 5,
    }
    return GenerationRequest(**{**base, **overrides})  # type: ignore[arg-type]


def _two_phase(poll: object, *, submit_data: dict | None = None, seen: list | None = None):
    """造一个**分得清提交与查询**的替身。

    ─────────────────────────────────────────────────────────
    【为什么要按 body 分派，而不是两条用例两个 handler】

    因为这个接口的两个动作走的是**同一个 URL**（靠 `Action` 查询参数
    与 body 区分），所以一个 handler 里必须判一下。写成「提交用例
    只回提交的响应」的话，那条用例里的 `poll` 会拿到一个没有 `status`
    的信封 —— 于是它测的是「未知状态」那条分支，而不是它想测的那条。

    这是本文件最容易写出的**假绿**：`provider.poll()` 返回了 `None`，
    而「还没好」和「没看懂」都是 `None`，断言 `is None` 照样通过。
    ─────────────────────────────────────────────────────────
    """
    payload = submit_data or {"task_id": "jm-001"}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if "task_id" in body:  # 查询
            if seen is not None:
                seen.append((body, req))
            if isinstance(poll, httpx.Response):
                return poll
            if isinstance(poll, Exception):
                raise poll
            return _ok(poll)  # type: ignore[arg-type]
        if seen is not None:
            seen.append((body, req))
        return _ok(payload)

    return handler


def _handle_of(provider: JimengProvider, request: GenerationRequest) -> str:
    """走一次 `submit`，把回执里的句柄取出来（下面几条用例要用它）。"""
    handle = provider.submit(request).provider_task_id
    assert handle, "提交没给出句柄"
    return handle


# ══════════════════════════════════════════════════════════════
# 提交：回执的形状与请求体
# ══════════════════════════════════════════════════════════════


def test_提交只回执_永远不是成品() -> None:
    """`done=False` + 非空句柄。

    ─────────────────────────────────────────────────────────
    【为什么「永远」是要紧的】`generation.submit` 里那句
    `if not result.done: return` 是同步路径上唯一挡住「把一张没有
    产物的回执当成成品结算掉」的东西 —— 钱扣了、资产落了、而文件
    根本不存在。即梦这边产物还要走「下载 → 转存 → 打标识」，
    那件事不该发生在用户那个 HTTP 请求里。

    这条例用**最像成品**的响应来测：信封成功、有 task_id，
    看起来像是可以马上结算的。
    ─────────────────────────────────────────────────────────
    """
    provider = _provider(lambda req: _ok({"task_id": "jm-001"}))
    result = provider.submit(_image_request())

    assert result.done is False
    assert result.provider_url is None
    assert result.provider_task_id and "jm-001" in result.provider_task_id


def test_提交的请求体带上了_req_key_与_prompt() -> None:
    """`req_key` 决定能力、也就决定单价，它必须是**配置里那个**。"""
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return _ok({"task_id": "jm-001"})

    _provider(handler).submit(_image_request(prompt="一只猫"))

    assert seen[0]["req_key"] == REQ_KEY_IMAGE
    assert seen[0]["prompt"] == "一只猫"


def test_图生视频把参考图地址放进_image_urls() -> None:
    """即梦在**它的机房里**下载参考图，所以它只能收到一个 URL。

    【为什么这条值得单独写】B6 之前 `GenerationRequest` 里根本没有
    承载它的字段（只有 `source_asset_id`）—— 于是「图生视频」这条
    线上跑起来时，provider 收到的是一个它无从解析的整数。这条用例
    钉的是那个字段真的被用上了。
    """
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return _ok({"task_id": "jm-002"})

    _provider(handler).submit(_video_request())

    assert seen[0]["req_key"] == REQ_KEY_VIDEO
    assert seen[0]["image_urls"] == ["https://cdn.example.com/u/1/7/cat.png"]
    assert seen[0]["duration"] == 5
    assert seen[0]["ratio"] == "16:9"


def test_签名头是_HMAC_SHA256_而且不含密钥明文() -> None:
    """铁律：**密钥绝不出现在任何会被记下来的地方**。

    ─────────────────────────────────────────────────────────
    【为什么这条断言比它看起来重要】`Authorization` 是要进
    HTTP 日志/抓包/报错页面的。把 SK 塞进头里（哪怕只是「方便调试」）
    是一次长期的泄漏 —— 而它**不会让任何一个功能测试变红**。
    AK 可以出现（协议要求），SK 不行：它是 HMAC 的钥匙，不是内容。
    ─────────────────────────────────────────────────────────
    """
    seen: list[httpx.Headers] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers)
        return _ok({"task_id": "jm-001"})

    _provider(handler).submit(_image_request())

    auth = seen[0]["Authorization"]
    assert auth.startswith("HMAC-SHA256 ")
    assert f"Credential={AK}/" in auth
    assert SK not in json.dumps(dict(seen[0]))
    assert seen[0]["Region"] == "cn-north-1"
    assert seen[0]["Service"] == "cv"


def test_签名里必须带上_host() -> None:
    """`host` 是参与签名的头 —— 少了它，网关的判决是 403 `InvalidAuthorization`。

    ─────────────────────────────────────────────────────────
    【这条测试是一次真网关事故的化石】

    第一版 `sign_request` 把 `host` 收成了参数，却没并进
    `signed_headers_in`。真网关回的是
        `InvalidAuthorization: Invalid 'Authorization' header,
         Pls check your authorization header.`
    —— 那是**网关**的错（业务码是数字，这个不是），说明请求连业务层
    都没进：网关拿 `SignedHeaders=` 里的清单重算规范请求，我们漏了
    `host`（它一定会算），两边逐字节就不同了。

    【为什么这条比它看起来重要】上面所有用 `MockTransport` 的用例
    **当时全绿**。合成上游只验「给定这种响应我们处置对」，它不看
    我们发出去的那串签名对不对 —— 也就是说，这个 bug 能在
    「本文件全绿」的情况下活到今天。所以这里钉的是**与网关的约定**，
    不是自洽性：`SignedHeaders=` 里必须同时有 `host` 和 `x-date`。
    ─────────────────────────────────────────────────────────
    """
    seen: list[httpx.Headers] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers)
        return _ok({"task_id": "jm-001"})

    _provider(handler).submit(_image_request())

    auth = seen[0]["Authorization"]
    signed = auth.split("SignedHeaders=")[1].split(",")[0].split(";")
    assert "host" in signed, signed
    assert "x-date" in signed, signed
    assert "x-content-sha256" in signed, signed
    # 算签名用的 Host 与实际发出去的那个，必须是同一个字符串。
    assert seen[0]["Host"] == "visual.volcengineapi.com"


def test_提交走的是_SUBMIT_ACTION() -> None:
    """两个动作走同一个地址、靠 `Action` 查询参数区分。"""
    seen: list[httpx.URL] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url)
        return _ok({"task_id": "jm-001"})

    _provider(handler).submit(_image_request())

    assert seen[0].params["Action"] == SUBMIT_ACTION
    assert seen[0].params["Version"] == "2022-08-31"


def test_受理了却没给_task_id_不可重试() -> None:
    """信封成功却缺 id = 我们对响应的理解和它实际的样子不一致。

    重试三次只会拿到三次同样的东西，而用户白等三倍时间。
    """
    provider = _provider(lambda req: _ok({"status": "done"}))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.retryable is False


# ══════════════════════════════════════════════════════════════
# 信封：**先看 code，再看 data**
# ══════════════════════════════════════════════════════════════


def test_非成功码即使带着_status_done_也算失败() -> None:
    """解析顺序的守卫。

    ─────────────────────────────────────────────────────────
    【顺序反了会怎样】一个 `code != 10000` 却**带着**
    `status: "done"` 的信封会被当成「成功且已完成」—— 也就是
    「钱扣了、资产落了、而文件根本不存在」那条路。

    这不是假想的：错误信封里带一个 `data` 占位对象是常见做法，
    而「先看 status」的写法在占位对象恰好是 `{"status": "in_queue"}`
    时碰巧不炸 —— 于是它会在上线很久之后、在某个特定的错误码上炸。

    【为什么用 `50500`（provider 内部错误）当例子】因为它是个
    **可重试的正常码**，最不容易被「这是个错误码，所以肯定不走
    成功分支」的直觉糊弄过去。
    ─────────────────────────────────────────────────────────
    """

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if "task_id" in body:
            return httpx.Response(
                200,
                json={
                    "code": 50500,
                    "message": "internal error",
                    "data": {"status": "done", "video_url": "https://evil.example.com/x.mp4"},
                },
            )
        return _ok({"task_id": "jm-001"})

    provider = _provider(handler)
    handle = _handle_of(provider, _image_request())

    with pytest.raises(ProviderFailure) as caught:
        provider.poll(handle)

    assert caught.value.retryable is True
    assert caught.value.code == "50500"
        # 【为什么原始码要一路带出去】它进 `tasks.error_code` 与
        # `provider_calls.resp_code` ——「即梦说 50429」和「我们说
        # PROVIDER_ERROR」在对账时是两件事，混在一起就查不清了。


def test_成功码的信封才继续看_data() -> None:
    provider = _provider(_two_phase({"status": "generating"}))
    assert provider.poll(_handle_of(provider, _image_request())) is None


# ══════════════════════════════════════════════════════════════
# 轮询：状态机
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("status", ["in_queue", "generating"])
def test_还没好是_None_不是失败(status: str) -> None:
    """把「还没好」当成失败，用户的视频会在生成到一半时被判失败并退款，
    而 provider 那边还在跑、还会出片 —— 我们白付一次调用费。"""
    provider = _provider(_two_phase({"status": status}))
    assert provider.poll(_handle_of(provider, _image_request())) is None


def test_done_取出产物地址与时长() -> None:
    provider = _provider(
        _two_phase({"status": "done", "video_url": "https://v.example.com/a.mp4", "duration": 6})
    )
    handle = _handle_of(provider, _video_request())
    result = provider.poll(handle)

    assert isinstance(result, ProviderResult)
    assert result.done is True
    assert result.provider_url == "https://v.example.com/a.mp4"
    assert result.output_duration_sec == 6
        # 【时长为什么必须有】结算按它算（§7.2 ④ 以实际时长为准）。
        # 取不到就按 0 结算 —— 平台吃亏，但不会多收用户的钱。


# ══════════════════════════════════════════════════════════════
# 内联的产物：它不给地址，给字节（2026-10-15 真网关实测）
# ══════════════════════════════════════════════════════════════

_SMALL_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60 + b"\xff\xd9"
    # 「像 JPEG」的一小串字节。`_sniff` 只看魔数（前 64 字节），
    # 所以这足够充当一张「转存层认得的图」，而不必真去渲一张。


def _inline_data(blobs: list[bytes], *, index: int = 0, **extra: object) -> dict:
    """一份**内联交付**的 `data`，字段名与取值都照真响应抄。"""
    return {
        "status": "done",
        "image_urls": None,          # 真响应里就是 null
        "video_url": "",             # 真响应里就是空串
        "binary_data_base64": [base64.b64encode(b).decode() for b in blobs],
        "resp_data": json.dumps(
            {"PreviewImage_121": [f"uri://binary_data?index={index}"], "comfyui_cost": 6.6782}
        ),
        **extra,
    }


@pytest.fixture
def spool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把暂存区钉到 `tmp_path`，并保证**两边读到的是同一个根**。

    ─────────────────────────────────────────────────────────
    【为什么这两步是一件事，缺一不可】

    内联产物落盘之后要交给转存层，而转存层的包含性检查读的是
    `get_settings().provider_spool_root` —— 一个**全局缓存**的值。
    被测的 provider 却是本文件用 `_settings()` 直接构造的。

    只 `monkeypatch.setenv` 不清缓存：`get_settings()` 还会回旧的那份，
    于是检查按**仓库根**判、而文件写进了 `tmp_path` → 被正确地拒掉，
    报成 `TransferFailure: provider 地址指向了暂存区之外`。
    那是「测试的搭法」被拒，不是被验的代码有问题 —— 一条会把人
    引向错方向的假红。

    反过来只清缓存不设环境变量：两边一致了，但产物会写进**仓库根**的
    `.provider_spool/`，跨用例、跨整次运行地留着（conftest 的 `api_app`
    夹具钉这一条就是为了这个）。所以两个一起做。

    `provider_spool_root` 没被 `_settings()` 显式传参，所以环境变量
    对它有效（优先级：构造参数 > 环境变量 > `.env` > 默认值）。
    ─────────────────────────────────────────────────────────
    """
    root = tmp_path / "spool"
    monkeypatch.setenv("PROVIDER_SPOOL_ROOT", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


def _inline_spool_path(root: Path, remote_id: str) -> Path:
    """内联产物应当落到的那个位置：`<spool 根>/jimeng/<id>.bin`。"""
    return root / "jimeng" / f"{remote_id}.bin"


def _tmp_sibling(root: Path, remote_id: str) -> Path:
    """写入中途用的临时名（`os.replace` 之前的那一份）。"""
    dest = _inline_spool_path(root, remote_id)
    return dest.with_name(f".tmp-{dest.name}")


def test_内联的_base64_产物被落成_spool_里的文件(spool: Path) -> None:
    """真网关不给地址，把 JPEG 塞在 `binary_data_base64` 里。

    ─────────────────────────────────────────────────────────
    【这条测试是一次真调用事故的化石】

    `jimeng_t2i_v31` 跑完之后 `image_urls` 是 `null`、`video_url` 是
    `""`，而 `binary_data_base64[0]` 是一张 121 KB 的真 JPEG。
    第一版只找地址，于是「成功率 100%、图也出来了」被我们判成
    `failed` + 全额退款 —— 即梦那边真的生成并计了一次费，
    我们这边一张图都没留下。

    【为什么断言里要过一遍转存层的地址解析】因为这条路的**唯一**风险
    就在那儿：`file://` 是转存层唯一会「按本地路径读」的形态，而它
    只放行 `provider_spool_root` **之内**的东西（那条检查挡的是
    「被污染的 provider_url 变成任意文件读取」）。所以「文件落了盘」
    还不够 —— 必须是**它认的那个位置**。
    ─────────────────────────────────────────────────────────
    """
    blob = _SMALL_JPEG
    provider = _provider(_two_phase(_inline_data([blob]), submit_data={"task_id": "inline-1"}))
    result = provider.poll(_handle_of(provider, _image_request()))

    assert isinstance(result, ProviderResult)
    assert result.done is True
    assert result.provider_url.startswith("file://"), result.provider_url

    # 转存层的包含性检查必须放行它 —— 放行不了，这条链就是断的。
    local = _local_path_for_file_url(result.provider_url)
    assert local.resolve() == _inline_spool_path(spool, "inline-1").resolve()
    assert local.read_bytes() == blob


def test_重复_poll_不会堆出第二份文件(spool: Path) -> None:
    """文件名用即梦的 task id → 确定性。

    【为什么这条要紧】`poll` 是会被重复调的（重启后的补转存、重试）。
    文件名里带上时间戳或 uuid 的话，每问一次就在磁盘上多留一张 121 KB
    的图 —— 而 v1 没有 GC（见 HANDOFF 的孤儿文件缺口），
    那些副本会**永久**留在那里。
    """
    provider = _provider(
        _two_phase(_inline_data([_SMALL_JPEG]), submit_data={"task_id": "inline-rep"})
    )
    handle = _handle_of(provider, _image_request())

    first = provider.poll(handle).provider_url
    second = provider.poll(handle).provider_url

    assert first == second
    assert _inline_spool_path(spool, "inline-rep").is_file()
    assert not _tmp_sibling(spool, "inline-rep").exists()
        # 写入中途的临时名不该留在磁盘上（`os.replace` 之后它就不存在了）。


def test_resp_data_指认的那个下标才算数() -> None:
    """`resp_data` 明说了是哪一个产物（`uri://binary_data?index=N`）。

    【为什么不取第 0 个】今天列表里只有一个、下标就是 0，但那是
    **这一次**的事实而不是约定。取第 0 个在「它将来指认第 1 个」的那天
    会静默地交付错的那张图，而库里每一条记录看起来都正常。
    """
    first, second = _SMALL_JPEG, b"\xff\xd8\xff\xe1" + b"\x11" * 40 + b"\xff\xd9"
    provider = _provider(
        _two_phase(_inline_data([first, second], index=1), submit_data={"task_id": "inline-idx"})
    )
    result = provider.poll(_handle_of(provider, _image_request()))

    assert _local_path_for_file_url(result.provider_url).read_bytes() == second


def test_指到列表外的下标退回第0个() -> None:
    """一个指到列表外的下标，唯一可能的解释是**我们对 `resp_data` 的理解错了**。

    那不该让任务失败：第 0 个至少是我们确证存在的那一个。
    """
    blob = _SMALL_JPEG
    provider = _provider(
        _two_phase(_inline_data([blob], index=9), submit_data={"task_id": "inline-oob"})
    )
    result = provider.poll(_handle_of(provider, _image_request()))

    assert _local_path_for_file_url(result.provider_url).read_bytes() == blob


def test_既没有地址也没有字节_不可重试() -> None:
    """两样都没有 = 我们和它对响应的理解不一致，再问一万次也一样。"""
    provider = _provider(_two_phase({"status": "done"}))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll(_handle_of(provider, _image_request()))

    assert caught.value.retryable is False
    assert "内联" in str(caught.value)


def test_坏_base64_不可重试_而且不落盘(spool: Path) -> None:
    """不是合法 base64 = 同一个任务再问一次还是同一串坏字节。"""
    data = _inline_data([b"x"])
    data["binary_data_base64"] = ["!!!! 这不是 base64 !!!!"]
    provider = _provider(_two_phase(data, submit_data={"task_id": "inline-bad"}))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll(_handle_of(provider, _image_request()))

    assert caught.value.retryable is False
    assert "base64" in str(caught.value)
    # 【为什么还要断言「没落盘」】一个解到一半的文件留在 spool 里，
    # 会在下一次 poll 时被当成**上一次的成功产物**用下去 ——
    # 而它的内容其实是坏的。宁可不留。
    assert not _inline_spool_path(spool, "inline-bad").exists()
    assert not _tmp_sibling(spool, "inline-bad").exists()


def test_内联产物超过上限就不落盘(spool: Path) -> None:
    """§9.3 的成本自保：对方给多少我们就往磁盘上写多少，那不行。

    【为什么闸门要在**解码之前**先判一次】base64 是 4:3 展开的。
    只判解码后的长度的话，一个远超上限的字符串会先被完整解进内存、
    再被判死刑 —— 那道闸门拦住的就不是「磁盘账单」而是「内存」了。
    """
    blob = b"\xff\xd8\xff\xe0" + b"\x00" * 4096 + b"\xff\xd9"
    provider = _provider(
        _two_phase(_inline_data([blob]), submit_data={"task_id": "inline-big"}),
        max_artifact_bytes=64,
    )
    with pytest.raises(ProviderFailure) as caught:
        provider.poll(_handle_of(provider, _image_request()))

    assert caught.value.retryable is False
    assert "上限" in str(caught.value)
    assert not _inline_spool_path(spool, "inline-big").exists()
    assert not _tmp_sibling(spool, "inline-big").exists()


def test_查询用的是_QUERY_ACTION_而且带回同一个_req_key() -> None:
    """`GetResult` 要求把**和提交时同一个** `req_key` 再传一遍。"""
    seen: list[tuple[dict, httpx.Request]] = []
    provider = _provider(
        _two_phase({"status": "generating"}, submit_data={"task_id": "jm-777"}, seen=seen)
    )
    provider.poll(_handle_of(provider, _video_request()))

    body, req = seen[-1]
    action = req.url.params["Action"]
    assert action == QUERY_ACTION
    assert body["req_key"] == REQ_KEY_VIDEO
    assert body["task_id"] == "jm-777"


@pytest.mark.parametrize("status", ["not_found", "expired"])
def test_任务在那边没了_判死而且不可重试(status: str) -> None:
    """再问一万次也是这个答案。"""
    provider = _provider(_two_phase({"status": status}))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll(_handle_of(provider, _image_request()))

    assert caught.value.retryable is False


def test_没见过的_status_当成还没好() -> None:
    """保守：等超时兜底（§8.2 全额退款），而不是在这里猜一个终态。

    【为什么不判死】未知状态更可能是**我们解析错了**或它新加了一种
    状态。判死的代价是用户白等一场（而且我们可能已经付了钱）；
    等超时的代价只是慢 —— 方向的代价不对称。
    """
    provider = _provider(_two_phase({"status": "waiting_for_gpu"}))
    assert provider.poll(_handle_of(provider, _image_request())) is None


def test_done_却没有产物地址_不可重试() -> None:
    provider = _provider(_two_phase({"status": "done"}))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll(_handle_of(provider, _image_request()))

    assert caught.value.retryable is False


@pytest.mark.parametrize(
    "data",
    [
        {"status": "done", "url": "https://v.example.com/a.mp4"},
        {"status": "done", "image_urls": ["https://v.example.com/a.png"]},
    ],
)
def test_产物字段名换个写法也认得(data: dict) -> None:
    """字段名是**推断**的，所以这里认几个候选。

    【为什么宁可写宽】字段名错了要等 §18-2 才知道，那时改一行就行；
    写窄了的话，一次「其实成功但字段名不同」会被我们判成
    「provider 没给地址」并**全额退款** —— 用户白等、我们白付，
    而日志里看不出区别。
    """
    provider = _provider(_two_phase(data))
    result = provider.poll(_handle_of(provider, _image_request()))
    assert result is not None and result.provider_url


def test_句柄形状不对_响亮地失败() -> None:
    """裸句柄只有一种来源：`provider_task_id` 里存着不是我们写进去的东西。

    【为什么没有兜底分支】猜一个 `req_key` 出来（比如「按当前配置」）
    会让这次查询**返回另一个能力的进度** —— 或者更糟，
    拿别人的结果当自己的。
    """
    provider = _provider(_two_phase({"status": "done"}))

    with pytest.raises(ProviderFailure) as caught:
        provider.poll("jm-001")

    assert caught.value.retryable is False


# ══════════════════════════════════════════════════════════════
# 网络层：四个失败形态各走各的分支
# ══════════════════════════════════════════════════════════════


def test_http_500_可重试_并且记下了状态码() -> None:
    provider = _provider(lambda req: httpx.Response(500, text="boom"))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.retryable is True
    assert caught.value.meta is not None
    assert caught.value.meta.http_status == 500


def test_4xx_的响应体被记进摘要() -> None:
    """2026-10-15 第一次真调用**真的踩过**这一条。

    `>= 400` 那条分支只记了状态码，正文压根没读 —— 于是失败时
    `provider_calls` 里四行的 `resp_message` 全是 `NULL`，而
    「它到底在抱怨什么」恰恰是那一刻唯一想知道的事。
    **对方明确告诉我们病因的那一类响应，反而是唯一不记录的一类。**
    """
    body = {"code": 50411, "message": "输入图审核未通过", "data": {}}
    provider = _provider(lambda req: httpx.Response(400, json=body))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.meta is not None
    assert caught.value.meta.resp_code == "50411"
    assert caught.value.meta.resp_message == "输入图审核未通过"


def test_网关的_4xx_信封也认得() -> None:
    """签名没过时**根本到不了业务层**，回的是火山网关那一套形状。

    只认 CV 的信封（`code` / `message`）的话，「签名算错了」这种最要紧的
    失败会退化成一句「HTTP 403」—— 那句话等于什么都没说。
    """
    body = {
        "ResponseMetadata": {
            "Error": {"Code": "SignatureDoesNotMatch", "Message": "签名与服务端计算结果不一致"}
        }
    }
    provider = _provider(lambda req: httpx.Response(403, json=body))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.meta is not None
    assert caught.value.meta.resp_code == "SignatureDoesNotMatch"
    assert caught.value.meta.resp_message == "签名与服务端计算结果不一致"


def test_不是_json的_4xx_原文照留一段() -> None:
    """HTML 错误页没有 `code` / `message` —— 那就把原文留下。

    （落库前 `sanitize_message` 会剥掉 URL 并截断到 200 字符，
    所以这里不必自己截。）
    """
    provider = _provider(lambda req: httpx.Response(502, text="<html>502 Bad Gateway</html>"))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.meta is not None
    assert caught.value.meta.resp_message is not None
    assert "502" in caught.value.meta.resp_message


def test_对方原文不进人话只进对账表() -> None:
    """⚠️ 这条钉的是**信息边界**，不是格式。

    `ProviderFailure` 的那句人话会一路走到用户的 `tasks.error_msg`
    （真调用那次，用户看到的就是「PROVIDER_ERROR: 即梦回了一个 HTTP 400」），
    而对方原文可能带着我们内部的请求参数、限流阈值、账号信息。
    所以：原文**只进** `provider_calls`（且落库前脱敏），不进人话。
    """
    body = {"code": 403, "message": "the access key of account 2100xxxx is not authorized"}
    provider = _provider(lambda req: httpx.Response(403, json=body))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert "2100xxxx" not in str(caught.value), "对方原文漏进了用户可见的人话"
    assert caught.value.meta is not None
    assert "2100xxxx" in (caught.value.meta.resp_message or "")


def test_超时归类为_timeout() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("太慢了")

    provider = _provider(handler)

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.meta is not None
    assert caught.value.meta.error_kind == "timeout"
    assert caught.value.retryable is True


def test_连不上归类为_connect() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("连不上")

    provider = _provider(handler)

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.meta is not None
    assert caught.value.meta.error_kind == "connect"


def test_响应不是_json_归类为_decode() -> None:
    provider = _provider(lambda req: httpx.Response(200, text="<html>502 gateway</html>"))

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.meta is not None
    assert caught.value.meta.error_kind == "decode"


def test_审计摘要里带着_req_key() -> None:
    """`provider_calls.req_key` 的来源 —— 同一个 `submit` 动作，
    `req_key` 不同就是不同的能力、不同的单价。"""
    provider = _provider(lambda req: httpx.Response(429, text="too many"))
    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_video_request())

    assert caught.value.meta is not None
    assert caught.value.meta.req_key == REQ_KEY_VIDEO


# ══════════════════════════════════════════════════════════════
# 审计码 → 处置：**走 `moderation` 那一张表**
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("code", "rejected", "retryable"),
    [
        ("50413", True, False),  # 输入文本审核未通过
        ("50429", False, True),  # QPS 限流
        ("50500", False, True),  # provider 内部错误
        ("99999", False, True),  # 没见过的码 → 保守可重试
    ],
)
def test_审计码按_moderation_的表处置(code: str, rejected: bool, retryable: bool) -> None:
    """适配层**不自己判**哪个码算审核 —— 那是产品判断，只有一张表。

    【为什么这条要参数化四条】因为这里真正被验的是「映射表被用上了」，
    而不是某一个码对不对。四个码覆盖了表里的三类走向
    （审核 / 限流 / 未知），换掉任何一个都会让对应那一格红。
    """
    provider = _provider(
        lambda req: httpx.Response(200, json={"code": int(code), "message": "nope"})
    )

    with pytest.raises(ProviderFailure) as caught:
        provider.submit(_image_request())

    assert caught.value.rejected is rejected
    assert caught.value.retryable is retryable
    assert caught.value.code == code


# ══════════════════════════════════════════════════════════════
# 装配：配置决定造谁
# ══════════════════════════════════════════════════════════════


def test_build_provider_按配置造即梦(monkeypatch: pytest.MonkeyPatch) -> None:
    """`PROVIDER=jimeng` 时，**两路都是即梦**（`VIDEO_PROVIDER` 没设）。

    【B7.x：`build_provider` 的形参是 `kind`】这里两条各断一次，
    而不是只断一次 —— 因为路由本身就是这一批新加的东西，
    而「不传 kind 就悄悄退回默认那一路」正是要防的错。
    """
    from app.config import get_settings
    from app.enums import TaskKind
    from app.providers import build_provider

    for key, value in {
        "PROVIDER": "jimeng",
        "JIMENG_AK": AK,
        "JIMENG_SK": SK,
        "JIMENG_REQ_KEY_IMAGE": REQ_KEY_IMAGE,
        "JIMENG_REQ_KEY_VIDEO": REQ_KEY_VIDEO,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        assert isinstance(build_provider(TaskKind.text_to_image), JimengProvider)
        # `VIDEO_PROVIDER` 没设 → 视频跟随图片。这是 2026-10-16 之前
        # 唯一存在过的部署形态，所以它必须仍然是即梦 —— 不然这次改动
        # 对既有部署就不是零行为变化了。
        assert isinstance(build_provider(TaskKind.image_to_video), JimengProvider)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ({"jimeng_req_key_video": ""}, "JIMENG_REQ_KEY_VIDEO"),
        ({"jimeng_req_key_image": ""}, "JIMENG_REQ_KEY_IMAGE"),
        ({"jimeng_ak": ""}, "JIMENG_AK"),
    ],
)
def test_配了即梦却缺配置_启动就炸(missing: dict[str, str], expected: str) -> None:
    """**进程起不来**，而不是等到第一次生成才失败。

    ─────────────────────────────────────────────────────────
    【为什么这条比它看起来重要】缺 `req_key` 的部署会**正常启动**、
    `/health` 正常、测试全绿 —— 然后在第一次生成时花掉一次真调用
    换回一句「不支持的 req_key」。那笔钱不多，但它是**在能事前
    拦住的情况下花掉的**。

    这里验的是构造 `Settings` 那一刻（也就是进程启动那一刻），
    而不是 `build_provider()` —— 校验放在配置那一层，
    见 `build_provider` 的说明。
    ─────────────────────────────────────────────────────────
    """
    with pytest.raises(ValueError) as caught:
        _settings(**missing)

    assert expected in str(caught.value)


def test_时间戳进签名_所以签名随天变化() -> None:
    """签名的输入里有 X-Date —— 它必须**来自传入的 now**。

    【为什么顺手钉一下】`sign_request` 若改用 `datetime.now()`，
    它是不可测的（每次结果不同），而这里那句 `now=utcnow()`
    在 `_post` 里读起来像一句无关紧要的样板。
    """
    from app.providers.jimeng_sign import sign_request

    def sign(now):
        return sign_request(
            method="POST",
            host="visual.volcengineapi.com",
            path="/",
            query={"Action": "X", "Version": "1"},
            body=b"{}",
            headers={"content-type": "application/json"},
            ak=AK,
            sk=SK,
            region="cn-north-1",
            service="cv",
            now=now,
        )["Authorization"]

    from datetime import timedelta

    today = utcnow()
    assert sign(today) != sign(today + timedelta(days=1))
