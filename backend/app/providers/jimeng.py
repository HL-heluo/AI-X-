"""即梦（火山引擎视觉）适配层 —— §12.2 的第二个 provider 实现。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️⚠️ **这个文件是按文档写的，不是按真接口调通的。**

手头没有 AK/SK（§18-2 卡住），所以这里每一处「即梦会怎么回」
都是**推断**。能验证的和不能验证的必须分开记：

  **合成上游（`httpx.MockTransport`）能证**：
    · 信封的解析顺序（先看 `code` 再看 `data.status`）；
    · 状态机（`in_queue` / `generating` / `done` / `not_found` / `expired`）；
    · 审计码 → 处置的映射走的是 `moderation` 那一张表；
    · 产物地址与时长从响应里取得出来；
    · 请求体带上了 `req_key` 与 prompt；
    · `Authorization` 以 `HMAC-SHA256` 开头，且**不含密钥明文**。

  **合成上游不能证**：
    · 签名能不能过网关（差一个字节就是一个 403）；
    · 请求 JSON 的 schema 对不对（字段名是猜的）；
    · `req_key` / 模型 id 对不对（§18-2 要在控制台确认）；
    · 产物字段名对不对（`video_url` 还是 `url` 还是别的）；
    · 这个子账号到底开没开通这个能力。

**清单在 `HANDOFF.md` 里**：填完 AK/SK 与 req_key 之后照它走一遍，
上面那五条才第一次被真的回答。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件里刻意**没有**的东西】

  · **没有任何密钥的默认值**，也不读环境变量 —— AK/SK 由调用方从
    `Settings` 取出来传进去。这样「密钥从哪来」在这份实现里是
    看不见的，也就不可能被顺手写死。
  · **没有重试逻辑**。重试归 §7.5 的 worker（退避、次数上限都在
    那边），provider 只负责「把这一次调用说清楚」。两处都重试的话，
    一次抖动会被放大成 3×3 次调用。
  · **没有把响应体整体塞进日志**。它可能包含带签名的产物地址
    （即梦报错时会把请求原样回显），那东西进日志等于泄漏。
    要记的摘要在 `meta` 里，且已脱敏。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import base64
import binascii
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.enums import ErrorCode, TaskKind
from app.providers import pricing
from app.providers.base import (
    GenerationRequest,
    ProviderCallMeta,
    ProviderFailure,
    ProviderResult,
)
from app.providers.jimeng_sign import sign_request
from app.services.moderation import failure_from_code
from app.types import utcnow

logger = logging.getLogger("aivideo.providers.jimeng")

SUBMIT_ACTION = "CVSync2AsyncSubmitTask"
QUERY_ACTION = "CVSync2AsyncGetResult"
API_VERSION = "2022-08-31"
API_PATH = "/"

SUCCESS_CODE = "10000"
"""信封里的成功码。**先判它再看 `data`** —— 见 `_envelope` 的说明。"""

HTTP_TIMEOUT_SEC = 30.0
"""单次 HTTP 调用的超时。

【为什么 30 秒而不是「生成要十分钟所以给十分钟」】这两个接口都**不是**
同步出片的：`submit` 只是把任务交出去（回执），`GetResult` 只是问一句
「好了没」。它们各自都应该是亚秒级的。给十分钟的话，一个卡住的连接
会把 worker 的一个 tick 整个占住 —— 而 worker 是单线程的，
那十分钟里全平台一条任务都出不了队。
"""

HANDLE_SEP = "|"
"""`provider_task_id` 里我们加的分隔符。见 `_handle` 的说明。"""

STATUS_IN_QUEUE = "in_queue"
STATUS_GENERATING = "generating"
STATUS_DONE = "done"
STATUS_NOT_FOUND = "not_found"
STATUS_EXPIRED = "expired"

# 产物地址可能落在这些字段里。
#
# ⚠️ **这是一份猜测**，而且是**故意写宽**的：字段名错了要等 §18-2 才能
#    知道，而那时改这一行就行；写窄了的话，一次「其实成功但字段名不同」
#    会被我们判成「provider 没给地址」并**全额退款** —— 用户白等一场、
#    我们白付一次调用费，而日志里看不出区别。
URL_KEYS: tuple[str, ...] = ("video_url", "url", "image_url", "cover_url")
URL_LIST_KEYS: tuple[str, ...] = ("image_urls", "urls")
DURATION_KEYS: tuple[str, ...] = ("duration", "Duration", "video_duration")

PAYLOAD_LIST_KEYS: tuple[str, ...] = ("binary_data_base64",)
"""**产物可能是内联的字节，而不是一个地址**（2026-10-15 真网关实测）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`jimeng_t2i_v31` 文生图跑完之后的 `data` 原文是这样的：

    {"status": "done",
     "image_urls": null,          ← `URL_LIST_KEYS` 找这里，是 null
     "video_url": "",             ← `URL_KEYS` 找这里，是空串
     "binary_data_base64": ["/9j/4AAQSkZJRgABAQ…"],   ← 121 KB 的真 JPEG
     "resp_data": "{\"PreviewImage_121\": [\"uri://binary_data?index=0\"],
                    \"comfyui_cost\": 6.6782}",
     "aigc_meta_tagged": false}

也就是说成功率 100%、图也真的出来了，但**它不给我们地址 —— 它把字节
塞在响应体里**。第一版只找地址，于是把它判成「即梦说 done 却没有产物
地址」、任务 `failed` + 全额退款：即梦那边真的生成并计了一次费，
我们这边一张图都没留下。

【为什么这一条不是「字段名写错了」】上面 `URL_KEYS` 那段说的是
「地址在哪个键里」；这里是**「它可能根本不是一个地址」** —— 换任何
键名都修不了。真正漏掉的是那个前提。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

INLINE_INDEX_RE = re.compile(r"binary_data\?index=(\d+)")
"""`resp_data` 里用 `uri://binary_data?index=N` 指认第几个产物。

`resp_data` 是一个**字符串**（JSON 套 JSON），而且键名是
`PreviewImage_121` 这种带版本号的 —— 解析它的结构不值得，认这个
URI 形状就够：认不出来时退回第 0 个（见 `_inline_payload`）。
"""

JIMENG_SPOOL_SUBDIR = "jimeng"
"""即梦的内联产物落在 `provider_spool_root/jimeng/`。

【为什么与 `fake` 的 `generated/` 分开】两个 provider 的产物放在同一
个目录里，一次「换 provider 重跑同一个任务」会互相覆盖，而排查的人
看到的是一个**内容对不上文件名**的文件。分开之后各自的目录只增不减
（v1 没有 GC，见 HANDOFF 的孤儿文件缺口）。
"""

_client: httpx.Client | None = None


def reset_client() -> None:
    """丢掉进程级 HTTP 客户端（**测试用**，同 `database.reset_engine`）。

    【为什么需要它】`httpx.Client` 拿着连接池，而测试要往
    `MockTransport` 上打 —— 不丢的话，第二个用例还在用第一个用例
    的假传输层，而那种失败看起来像「被测代码不发请求了」。
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None


def _http_client() -> httpx.Client:
    """进程级复用的客户端。

    【为什么不是每个 provider 实例一个】`build_provider()` 每轮
    worker（2 秒）和每个请求都会调一次，而每次 `httpx.Client()`
    都开一套连接池。不复用的话，一个跑一周的进程会攒下几十万个
    没关的连接 —— 症状是「句柄耗尽」，而病因在两个月前的一行
    `httpx.Client()`。
    """
    global _client
    if _client is None:
        _client = httpx.Client(timeout=HTTP_TIMEOUT_SEC)
    return _client


class JimengProvider:
    """即梦的两段式适配层：`submit` 拿回执，`poll` 等结果。"""

    name = "jimeng"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """`client` 是**注入**的，测试用 `httpx.MockTransport` 当合成上游。

        【为什么它和 `settings` 都是构造参数】测试要能造一个
        「配了假密钥、接到假传输层上」的实例。走 `get_settings()`
        的话，测签名得先污染进程级配置缓存 —— 而那种污染会漏给
        下一个用例（conftest 里那段说明写过同一个坑）。
        """
        self._settings = settings or get_settings()
        self._client = client

    # ── 计价：和 fake 共用同一段算式（`pricing.py`）────────────

    def freeze_amount(self, request: GenerationRequest) -> int:
        """§7.2 的冻结额。**算式在 `pricing.py`，这里只是转手。**

        【为什么即梦不能自己算一份】因为「冻结 32 / 结算 24 / 退回 8」
        是**契约**（前端写死了），而 fake 是跨仓门禁里的那一份。
        各写一份的话，两份都还是绿的 —— 而线上跑的是即梦、门禁跑的是
        fake，于是契约在两边开始说不同的话。见 `pricing.py` 的文件头。
        """
        return pricing.freeze_amount(request)

    def settle_amount(self, request: GenerationRequest, result: ProviderResult) -> int:
        """§7.2 的结算额。**算式在 `pricing.py`，这里只是转手。**"""
        return pricing.settle_amount(request, result)

    # ── 调用 ───────────────────────────────────────────────

    def submit(self, request: GenerationRequest) -> ProviderResult:
        """交出去。**永远返回 `done=False` 的回执。**

        【为什么「永远」是要紧的】`generation.submit` 里那条
        `if not result.done: return` 是同步路径上唯一挡住
        「把一张没有产物的回执当成成品结算掉」的东西。即梦这边
        产物要走「下载 → 转存 → 打标识」，那件事**不该发生在 HTTP
        请求线程里**（用户点一下要等十几秒，而 B6 起它还必须在**事务外**
        做）。所以这里只回执，剩下的交给 worker 的轮询。
        """
        req_key = self._req_key(request.kind)
        body = self._submit_body(request, req_key)

        envelope, meta = self._post(SUBMIT_ACTION, body, req_key=req_key)
        data = envelope.get("data") or {}

        task_id = data.get("task_id")
        if not task_id:
            # 【为什么不重试】信封是成功的（`code == 10000`）却缺 id ——
            # 这不是抖动，是**我们对响应的理解和它实际的样子不一致**。
            # 重试三次会拿到三次同样的东西，而用户白等三倍的时间。
            raise ProviderFailure(
                "即梦受理了任务但没给 task_id（响应字段名可能与文档不一致）",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            )

        return ProviderResult(
            output_duration_sec=0,
            provider_task_id=_handle(req_key=req_key, task_id=str(task_id)),
            provider_url=None,
            done=False,
            meta=meta,
        )

    def poll(self, provider_task_id: str) -> ProviderResult | None:
        """问一次。`None` = 还没好。

        ─────────────────────────────────────────────────────────
        【上一版：`req_key` 从哪来】

        `GetResult` 要求把**和提交时同一个** `req_key` 再传一遍，而
        `poll` 的签名里只有 `provider_task_id`（Protocol 定的，见
        `base.py`）—— 拿不到 `kind`，也就推不出 `req_key`。

        第一版是在 provider 实例上记一个 `{task_id: req_key}` 的字典。
        那是**错的**，而且错得很典型：它是「任务状态放在进程内存里」
        （铁律里明令禁止的那一条）。进程一重启，所有在飞的任务都
        问不出结果 —— 表现是「部署一次，正在生成的任务全部失败退款」，
        而排查的人会先怀疑即梦。

        现在把 `req_key` 编进 `provider_task_id`（见 `_handle`），
        于是它**跟着任务一起进库、一起重启**。代价是这个句柄看起来
        比「即梦给的 id」长一截 —— 换来的是它不再依赖任何内存状态。
        ─────────────────────────────────────────────────────────
        """
        req_key, task_id = _split_handle(provider_task_id)
        body: dict[str, Any] = {"req_key": req_key, "task_id": task_id}

        envelope, meta = self._post(QUERY_ACTION, body, req_key=req_key)
        data = envelope.get("data") or {}
        status = data.get("status")

        if status in (STATUS_IN_QUEUE, STATUS_GENERATING):
            # ⚠️ 这里必须回 None 而不是「失败」：把「还没好」当成失败，
            #    用户的视频会在生成到一半时被判失败并退款，
            #    而 provider 那边还在跑、还会出片（白付一次）。
            return None

        if status in (STATUS_NOT_FOUND, STATUS_EXPIRED):
            # 任务在 provider 那边**不存在了**（过期或被清）。
            # 再问一万次也是这个答案，所以不可重试 —— 判死 + 全额退。
            #
            # 【为什么这里不走 `failure_from_code`】因为那不是**审计码**
            # 而是**任务状态**，`moderation` 那张表里没有它的位置 ——
            # 而那张表对「没见过的码」的默认判断是**可重试**
            # （保守方向，那条规则对码是对的）。拿它来判状态的话，
            # 一个永久的 `not_found` 会被重试三次、白等十几秒，
            # 然后落到同一个结局。
            raise ProviderFailure(
                f"即梦那边这条任务的状态是 {status}（不会再好了）",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            )

        if status != STATUS_DONE:
            # 未知状态：可能是我方解析错了，也可能是它新加了一种状态。
            # 保守地当「还没好」—— 等超时兜底（§8.2 的 `task_timeout_sec`
            # 会全额退款），比在这里猜一个终态安全。
            logger.warning("即梦回了一个没见过的 status：%r（当成「还没好」）", status)
            return None

        url = _extract_url(data)
        if not url:
            # 没给地址 —— 可能是**内联的字节**（见 `PAYLOAD_LIST_KEYS`）。
            url = self._materialize_inline(data, remote_id=task_id, meta=meta)

        return ProviderResult(
            output_duration_sec=_extract_duration(data),
            provider_task_id=provider_task_id,
            provider_url=url,
            done=True,
            meta=meta,
        )

    # ── 内联产物 ───────────────────────────────────────────

    def _spool(self) -> Path:
        """内联产物的落地目录（`provider_spool_root/jimeng`）。"""
        return self._settings.provider_spool_root_ready / JIMENG_SPOOL_SUBDIR

    def _materialize_inline(
        self, data: dict[str, Any], *, remote_id: str, meta: ProviderCallMeta
    ) -> str:
        """把**内联的 base64 产物**落成 spool 里的一个文件，回它的 `file://` 地址。

        ─────────────────────────────────────────────────────────
        【为什么是「落成文件」而不是「把字节塞进 ProviderResult」】

        因为产物要**跨进程活得下去**：转存在 `defer_io` 之后做，而那段
        IO 可能发生在进程重启之后 —— worker 的「补转存」扫的正是
        库里的 `tasks.provider_url`。所以产物必须以**地址**的形态进库。

        把 20MB 的 bytes 放进 `ProviderResult` 再落库是另一条路，代价是
        加一列 + 一次迁移 + 每一行都变胖；而 `provider_spool_root` 之下
        正是 `fake` **已经在用**的那条路（provider 自己把字节落到自己的
        暂存区、回一个 `file://` 地址）。转存层的 `_local_path_for_file_url`
        只放行这个根**之内**的路径，于是**那条包含性检查是被使用，
        而不是被放宽** —— 这里没有任何新的信任边界。
        ─────────────────────────────────────────────────────────
        """
        picked = _inline_payload(data)
        if picked is None:
            raise ProviderFailure(
                "即梦说 done，但既没有产物地址、也没有内联的产物字节（字段名可能与文档不一致）",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            )
        encoded, index = picked

        limit = self._settings.max_artifact_bytes
        # 【为什么先按**编码长度**判一次】base64 是 4:3 展开的，先粗判
        # 能让一个远超上限的字符串**在解码之前**就被拦下 —— 否则 200MB
        # 的闸门会先被解进内存判一次死刑，再被 string 本身撑爆一次。
        if len(encoded) // 4 * 3 > limit:
            raise ProviderFailure(
                f"即梦内联回来的产物（第 {index} 个）超过上限 {limit} 字节",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            )
        try:
            blob = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            # 【为什么不可重试】同一个任务再问一次，回来的还是同一串
            # 坏 base64。重试三次只是把同一句话等三遍。
            raise ProviderFailure(
                f"即梦内联回来的产物不是合法的 base64（第 {index} 个）",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            ) from exc
        if not blob:
            raise ProviderFailure(
                f"即梦内联回来的产物是空的（第 {index} 个）",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            )
        if len(blob) > limit:
            raise ProviderFailure(
                f"即梦内联回来的产物超过上限 {limit} 字节",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
                meta=meta,
            )

        self._spool().mkdir(parents=True, exist_ok=True)
        dest = self._spool() / f"{remote_id}.bin"
        # 先写临时名再 `os.replace`（同 `fake._render_atomically`）：
        # 半截文件被转存层读到，会变成一张「加载失败」的图，而库里
        # 的记录看起来完全正常 —— 那是这类流水线里最难归因的一种。
        tmp = dest.with_name(f".tmp-{dest.name}")
        tmp.write_bytes(blob)
        os.replace(tmp, dest)

        # 名字里不带扩展名是**有意的**：格式由转存层的 `_sniff` 按魔数判
        # （见它那段「不能信 URL 的后缀」）。这里猜一个后缀，只会让
        # 「名字说 png、内容其实是 mp4」这类不一致多一个来源。
        # 文件名用即梦的 task id → **确定性**：重复 poll 只会覆盖同一个
        # 文件，不会一次一次地堆。
        return dest.as_uri()

    # ── 请求体 ─────────────────────────────────────────────

    def _req_key(self, kind: TaskKind) -> str:
        return (
            self._settings.jimeng_req_key_image
            if kind is TaskKind.text_to_image
            else self._settings.jimeng_req_key_video
        )

    def _submit_body(self, request: GenerationRequest, req_key: str) -> dict[str, Any]:
        """拼提交的 JSON。

        ─────────────────────────────────────────────────────────
        ⚠️ **字段名是猜的。** 这是这个文件里最不可信的一段，理由：
        官方文档给的是「按 `req_key` 路由到不同的能力」，而每种能力的
        body schema 分布在各能力的文档里 —— 我们手头没有那种能力的
        开通凭证，也就看不到它那一页。

        所以这里只写**能推断的部分**，并且错的方向是可控的：
          · 多写一个它不认的字段 → 它多半会回一个 4xx，
            是一次**响亮且不花钱**的失败；
          · 少写一个它要的字段 → 同样 4xx。
        两种都不会变成「扣了钱但做出来的是别的东西」。

        【`image_urls` 为什么要 `request.source_url`】图生视频必须给它
        一个**它下得动**的地址，而它在自己的机房里下 —— 所以只能是
        公网 URL。`source_url` 由调用方从 `Storage.url_for` 拼好传进来
        （B6 才有的字段，见 `base.GenerationRequest`）。
        ─────────────────────────────────────────────────────────
        """
        body: dict[str, Any] = {"req_key": req_key, "prompt": request.prompt}

        if request.kind is TaskKind.text_to_image:
            # 图：把用户选的画幅原样带上。名字（`aspect_ratio`）是我们
            # 契约里的叫法，对方叫什么要等 §18-2 —— 见类文档。
            for key in ("aspect_ratio", "width", "height"):
                if request.params.get(key) is not None:
                    body[key] = request.params[key]
            return body

        # 视频（v1 只有图生视频）
        body["duration"] = request.requested_duration_sec
        if request.source_url:
            body["image_urls"] = [request.source_url]
        if request.params.get("ratio") is not None:
            body["ratio"] = request.params["ratio"]
        return body

    # ── HTTP ───────────────────────────────────────────────

    def _post(
        self, action: str, body: dict[str, Any], *, req_key: str
    ) -> tuple[dict[str, Any], ProviderCallMeta]:
        """发一次签过名的请求，返回 `(信封, HTTP 摘要)`。

        【为什么返回 `meta` 而不是让它记日志】它要一路走到
        `provider_calls`（§11.1 的成本对账表）—— 那张表是回答
        「钱花在哪了」的唯一工具，而日志会被轮转掉。
        """
        settings = self._settings
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        url = f"https://{settings.jimeng_host}{API_PATH}"
        query = {"Action": action, "Version": API_VERSION}

        headers = sign_request(
            method="POST",
            host=settings.jimeng_host,
            path=API_PATH,
            query=query,
            body=payload,
            headers={
                "content-type": "application/json",
                # 即梦接入文档 §2：这两个头是它路由到正确区域/服务的依据。
                "region": settings.jimeng_region,
                "service": settings.jimeng_service,
            },
            ak=settings.jimeng_ak,
            sk=settings.jimeng_sk,
            region=settings.jimeng_region,
            service=settings.jimeng_service,
            now=utcnow(),
        )

        client = self._client or _http_client()
        try:
            response = client.post(url, params=query, content=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise failure_from_code(
                None,
                f"调用即梦超时（{HTTP_TIMEOUT_SEC:.0f}s）",
                meta=ProviderCallMeta(error_kind="timeout", req_key=req_key),
            ) from exc
        except httpx.HTTPError as exc:
            # `HTTPError` 是 httpx 的异常树根（连接失败、TLS、代理…）。
            # 全部归成 `connect`：对我们而言它们的处置一样（重试）。
            raise failure_from_code(
                None,
                f"调用即梦时网络失败：{type(exc).__name__}",
                meta=ProviderCallMeta(error_kind="connect", req_key=req_key),
            ) from exc

        meta = ProviderCallMeta(http_status=response.status_code, req_key=req_key)
        if response.status_code >= 400:
            raise failure_from_code(
                None,
                f"即梦回了一个 HTTP {response.status_code}",
                meta=_with_body(meta, response),
            )

        try:
            envelope = response.json()
        except ValueError as exc:
            raise failure_from_code(
                None,
                "即梦的响应不是 JSON（可能是网关的错误页）",
                meta=_with_body(
                    ProviderCallMeta(
                        http_status=response.status_code,
                        error_kind="decode",
                        req_key=req_key,
                    ),
                    response,
                ),
            ) from exc

        if not isinstance(envelope, dict):
            raise failure_from_code(
                None,
                "即梦的响应顶层不是一个对象",
                meta=_with_body(
                    ProviderCallMeta(
                        http_status=response.status_code,
                        error_kind="decode",
                        req_key=req_key,
                    ),
                    response,
                ),
            )

        return _envelope(envelope, meta=meta), _with_code(meta, envelope)


def _with_body(meta: ProviderCallMeta, response: httpx.Response) -> ProviderCallMeta:
    """把**非成功响应**的正文塞进摘要 —— 这就是「对方说错在哪」的那句话。

    ─────────────────────────────────────────────────────────
    【为什么它存在（2026-10-15，第一次真调用）】

    第一次打真即梦，四次提交全回 `HTTP 400`，任务失败、钱全额退回、
    `provider_calls` 记了四行 —— 一切「正常」，除了**我们不知道它
    在抱怨什么**：那四行的 `resp_message` 全是 `NULL`，因为
    `>= 400` 那条分支只记了状态码，正文压根没读。

    也就是说：**对方明确告诉我们病因的那一类响应，恰恰是唯一不记录
    的一类**。而 HTTP 400 是最常出现、也最必须看见正文的一种
    （签名错、`req_key` 错、字段名错，全都会落在这里）。

    【为什么要认两种信封，而不是只取 `code` / `message`】

    因为 4xx 有两个可能的来源，形状不一样：

      · **CV 接口自己**：`{"code": "50411", "message": "..."}`
        —— 成功路径的信封（`_envelope` 认的那种）；
      · **火山网关**（签名没过、路径不对时根本到不了业务层）：
        `{"ResponseMetadata": {"Error": {"Code": "...", "Message": "..."}}}`

    只认第一种的话，「签名错了」这种最要紧的失败会退化成一句
    「HTTP 403」，而那等于什么都没说。

    【为什么不把这句话也放进 `ProviderFailure` 的人话里】

    因为那条人话会**走到用户的响应体上**（`tasks.error_msg`），
    而对方原文可能带着我们内部的请求参数、限流阈值、账号信息。
    用户该看到的是「生成失败」，我们该看到的是原文 ——
    所以它只进 `provider_calls`，落库前还会被 `sanitize_message`
    剥掉 URL 并截断。
    ─────────────────────────────────────────────────────────
    """
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None

    code: Any = None
    message: Any = None

    if isinstance(parsed, dict):
        code = parsed.get("code")
        message = parsed.get("message")
        if code is None and message is None:
            error: Any = parsed.get("ResponseMetadata")
            if isinstance(error, dict):
                error = error.get("Error")
            if isinstance(error, dict):
                code = error.get("Code")
                message = error.get("Message")

    if code is None and message is None:
        # 两种信封都不是 —— 原样留一段文本。它常常是一张 HTML 错误页，
        # 而那正是「502 但后端以为自己在说人话」那种情况里唯一的线索。
        message = response.text

    return ProviderCallMeta(
        http_status=meta.http_status,
        resp_code=None if code is None else str(code),
        resp_message=None if message is None else str(message),
        error_kind=meta.error_kind,
        req_key=meta.req_key,
    )


def _envelope(envelope: dict[str, Any], *, meta: ProviderCallMeta) -> dict[str, Any]:
    """先判 `code`，再看 `data`。**顺序不能反。**

    ─────────────────────────────────────────────────────────
    【反了会怎样】一个 `code != 10000` 却**带着** `status: "done"` 的
    信封会被当成「成功且已完成」—— 也就是「钱扣了、资产落了、
    而文件根本不存在」那条路。这不是假想的：错误信封带一个
    `data` 占位对象是常见做法，而「先看 status」的写法在错误码是
    `in_queue` 那种时才碰巧不炸。

    【为什么返回信封而不是直接抛】`data` 的形状每次不同
    （提交回 `task_id`、查询回 `status`），所以「怎么判成功」留在这里、
    「怎么解读 data」留给调用方。**但成功与否只在这里判一次。**
    ─────────────────────────────────────────────────────────
    """
    code = envelope.get("code")
    if str(code) != SUCCESS_CODE:
        raise failure_from_code(
            None if code is None else str(code),
            str(envelope.get("message") or "即梦返回了非成功码"),
            meta=_with_code(meta, envelope),
        )
    return envelope


def _with_code(meta: ProviderCallMeta, envelope: dict[str, Any]) -> ProviderCallMeta:
    """把对方原始的业务码与它说的话塞进摘要（脱敏留给 `provider_audit`）。"""
    code = envelope.get("code")
    message = envelope.get("message")
    return ProviderCallMeta(
        http_status=meta.http_status,
        resp_code=None if code is None else str(code),
        resp_message=None if message is None else str(message),
        error_kind=meta.error_kind,
        req_key=meta.req_key,
    )


def _handle(*, req_key: str, task_id: str) -> str:
    """把 `req_key` 和即梦的 `task_id` 编成一个句柄。见 `poll` 里那段说明。"""
    return f"{req_key}{HANDLE_SEP}{task_id}"


def _split_handle(handle: str) -> tuple[str, str]:
    """`_handle` 的逆运算。

    【为什么没有裸句柄的兜底分支】没有分隔符只有一种可能：
    `tasks.provider_task_id` 里存着一个不是我们写进去的东西。
    那时候猜一个 `req_key` 出来（比如「按当前配置的默认值」）会让
    这次查询**返回另一个能力的进度**，或者更糟：拿别人的结果当自己的。
    响亮地失败是这里唯一安全的选项。
    """
    req_key, sep, task_id = handle.partition(HANDLE_SEP)
    if not sep or not req_key or not task_id:
        raise ProviderFailure(
            f"provider_task_id 的形状不对（{handle!r}）—— "
            "它应该是 `_handle()` 编出来的",
            code=ErrorCode.PROVIDER_ERROR.value,
            retryable=False,
        )
    return req_key, task_id


def _extract_url(data: dict[str, Any]) -> str | None:
    """从 `data` 里找产物地址。见 `URL_KEYS` 上面那段（**是一份猜测**）。"""
    for key in URL_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    for key in URL_LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0]
    return None


def _inline_payload(data: dict[str, Any]) -> tuple[str, int] | None:
    """把内联的产物挑出来，回 `(base64 文本, 它在列表里的下标)`。

    【为什么下标要从 `resp_data` 里认，而不是直接取第 0 个】
    因为 `resp_data` 明说了是哪一个：`"PreviewImage_121":
    ["uri://binary_data?index=0"]`。今天列表里只有一个、下标就是 0，
    但那是**这一次**的事实，不是约定 —— 取第 0 个在「它将来指认第 1 个」
    的那天会静默地交付错的那张图，而库里每一条记录看起来都正常。

    【为什么用正则而不是解析 `resp_data`】它是个字符串，里面那段 JSON
    的键名是 `PreviewImage_121` 这种**带版本号**的，解析它等于把
    一个会随版本变的内部结构钉进我们的代码。认 URI 形状、认不出来
    就退回第 0 个 —— 认不出来时退回是安全的（今天就是 0）。
    """
    for key in PAYLOAD_LIST_KEYS:
        value = data.get(key)
        if not (isinstance(value, list) and value and isinstance(value[0], str)):
            continue
        index = 0
        resp = data.get("resp_data")
        if isinstance(resp, str):
            found = INLINE_INDEX_RE.search(resp)
            if found:
                candidate = int(found.group(1))
                # 越界就退回 0：一个指到列表外的下标，唯一可能的解释是
                # 我们对 `resp_data` 的理解错了，而那不该让任务失败 ——
                # 第 0 个至少是我们**确证**存在的那一个。
                index = candidate if candidate < len(value) else 0
        return value[index], index
    return None


def _extract_duration(data: dict[str, Any]) -> int:
    """成片时长（秒）。**找不到就是 0。**

    【为什么 0 是安全的方向】计费按它算，而 0 意味着「收得最少」——
    真值拿不到时，宁可少收（平台吃亏）也不要凭请求时长猜一个
    （多收用户的钱，而 §7.2 明说多退少补以实际时长为准）。
    这条会在 §18-2 之后被真响应替掉，而那时要顺手把这条注释删掉 ——
    留着它会让下一个读的人以为这里还没接完。
    """
    for key in DURATION_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0
