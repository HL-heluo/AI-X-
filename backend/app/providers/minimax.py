"""MiniMax（H3 / H3-Max）视频适配层 —— §12.2 的**第三个** provider 实现。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么会有第三个实现】

即梦那条链路上，文生图已经跑通了，**图生视频一步都没成** —— 而卡点
不在代码里：那个产品的**并发配额是 0**（`HANDOFF.md` §2.6 第四件事 ②、
§8.2 第 11 条），要人或钱去解。这个文件是把图生视频整条换到一条
**不依赖那个配额**的通道上。

所以：**它只管视频。** 文生图仍在即梦里（`config.provider`），
拿 MiniMax 当图片 provider 会在配置那一层就被拒
（见 `ProviderKind.minimax` 与 `Settings.model_post_init`）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件里刻意**没有**的东西】（与 `jimeng.py` 同款纪律）

  · **没有任何密钥的默认值**，也不读环境变量 —— 密钥由调用方从
    `Settings` 取出来传进去。这样「密钥从哪来」在这份实现里是看不见的，
    也就不可能被顺手写死。
  · **没有重试逻辑**。重试归 §7.5 的 worker（退避、次数上限都在那边）。
    两处都重试的话，一次抖动会被放大成 3×3 次调用。
  · **没有把响应体整体塞进日志**。MiniMax 的产物地址是**有时效的下载
    链接**（文档明说「请及时下载或转存」），把它打进日志等于多一处泄漏面。
    要记的摘要在 `meta` 里，且落库前还会被 `sanitize_message` 剥 URL 截断。
  · **没有第二份计价算式** —— `freeze_amount` / `settle_amount` 转手
    `pricing.py`，与 fake / jimeng 是同一段代码（见那个文件的文件头）。
  · **没有 spool 子目录**（即梦的 `JIMENG_SPOOL_SUBDIR` 那种）。
    即梦之所以要把字节落到 `provider_spool_root` 下，是因为它实测
    **不给地址、把 121KB 的真 JPEG 塞在 `binary_data_base64` 里**。
    MiniMax 的产物**永远是 `task.content.url` 一个地址**，文档里没有
    内联字节那条通道 —— 所以这里不需要那个目录，也不该预先造一个。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

文档出处：`platform.minimax.cn/docs/api-reference/video-generation-v2-create`
与 `…-v2-query`。**这一份是按文档写的，还没被真网关打过** —— 与
`jimeng.py` 2026-10-15 之前的处境一样。真打一次之后要复审的地方，
在下面各自标了「⚠️ 待真调用确认」。
"""

from __future__ import annotations

import logging
import re
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
from app.services.moderation import failure_from_code

logger = logging.getLogger("aivideo.providers.minimax")

CREATE_PATH = "/v2/video_generation"
QUERY_PATH = "/v2/query/video_generation"
"""两个端点。**提交是 POST 根路径 + JSON 体，查询是 GET 且 task_id 在路径里** ——
与即梦那种「同一个路径 + `Action` 参数路由」的形状完全不同。"""

HTTP_TIMEOUT_SEC = 30.0
"""单次 HTTP 调用的超时。理由与 `jimeng.HTTP_TIMEOUT_SEC` 逐字相同：
这两个接口都不是同步出片的（`submit` 只是交任务，`query` 只是问一句），
各自都该是亚秒级。给十分钟的话，一个卡住的连接会把 worker 的一个 tick
整个占住 —— 而 worker 是单线程的，那十分钟里全平台一条任务都出不了队。"""

MIN_DURATION_SEC = 5
MAX_DURATION_SEC = 15
"""H3-Max 支持的时长区间（H3 是 4~15，**H3-Max 不支持 4 秒**）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这里要按住一个接口层没按住的东西】

`schemas.VideoGenIn.duration` 是 `int = 5`，**没有上下界** ——
所以 `POST /generation/video {"duration": 4}` 在接口层是**合法**的，
而 H3-Max 会回一个 400。

前端只发 5 和 10（`video_gen_page.dart` 的 `_durations`），所以线上
碰不到。但「碰不到」不等于「不用拦」：拦在这里的代价是一行判断，
不拦的代价是**花掉一次真调用**换回一个我们自己拼错的请求被拒。

【为什么不在 `VideoGenIn` 上加 `ge=5, le=15`】那是**契约变更** ——
契约里 `duration` 今天是没有范围的，加范围要前后端一起动
（前端得能表达「这个档位不可用」）。这一批不动契约，把这条记进
HANDOFF 当缺口。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

RATIO_ADAPTIVE = "adaptive"
"""图生视频的宽高比**恒为这个值**，由输入图决定。见 `_submit_body`。"""

DEFAULT_T2V_RATIO = "16:9"
"""文生视频的兜底比例。文档要求 t2v 的 `ratio` **必填且不能是 adaptive**。"""

ERROR_CODE_RE = re.compile(r"\((\d{3,6})\)\s*$")
"""从 `error.message` 末尾抠出内部码：`"... sensitive content (1026)"` → `1026`。

⚠️ **待真调用确认**：这是**对方的文案约定**，不是契约（文档没保证
那个括号永远在末尾）。认不出来的后果是可控的 —— `code` 为 `None` 时
落到**按 HTTP 状态码**那张表上（见 `moderation.MINIMAX_HTTP_STATUS_MAP`），
而状态码是文档明确写死的。所以抠不出来只会丢掉「更细的那一档」，
不会丢掉「该不该重试」这个判断。
"""

_client: httpx.Client | None = None


def reset_client() -> None:
    """丢掉进程级 HTTP 客户端（**测试用**，同 `jimeng.reset_client`）。

    【为什么需要它】`httpx.Client` 拿着连接池，而测试要往
    `MockTransport` 上打 —— 不丢的话，第二个用例还在用第一个用例
    的假传输层，而那种失败看起来像「被测代码不发请求了」。
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None


def _http_client() -> httpx.Client:
    """进程级复用的客户端。理由逐字同 `jimeng._http_client`：
    `build_provider()` 每轮 worker（2 秒）和每个请求都会调一次，
    每次 `httpx.Client()` 都开一套连接池。"""
    global _client
    if _client is None:
        _client = httpx.Client(timeout=HTTP_TIMEOUT_SEC)
    return _client


class MinimaxProvider:
    """MiniMax 视频的两段式适配层：`submit` 拿回执，`poll` 等结果。"""

    name = "minimax"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """`client` 是**注入**的，测试用 `httpx.MockTransport` 当合成上游。

        与 `JimengProvider.__init__` 同款、同理由：测试要能造一个
        「配了假密钥、接到假传输层上」的实例，而走 `get_settings()`
        就得先污染进程级配置缓存，那种污染会漏给下一个用例。
        """
        self._settings = settings or get_settings()
        self._client = client

    # ── 计价：和 fake / jimeng 共用同一段算式（`pricing.py`）────

    def freeze_amount(self, request: GenerationRequest) -> int:
        """§7.2 的冻结额。**算式在 `pricing.py`，这里只是转手。**"""
        return pricing.freeze_amount(request)

    def settle_amount(self, request: GenerationRequest, result: ProviderResult) -> int:
        """§7.2 的结算额。**算式在 `pricing.py`，这里只是转手。**"""
        return pricing.settle_amount(request, result)

    # ── 调用 ───────────────────────────────────────────────

    def submit(self, request: GenerationRequest) -> ProviderResult:
        """交出去。**永远返回 `done=False` 的回执。**

        【为什么「永远」是要紧的】与 `jimeng.submit` 同款：产物要走
        「下载 → 转存 → 打标识」，那件事不该发生在 HTTP 请求线程里，
        而且 B6 起它必须在**事务外**做。所以这里只回执。
        """
        self._reject_unsupported(request)

        body = self._submit_body(request)
        model = str(body["model"])
        payload, meta = self._send(
            "POST", CREATE_PATH, body=body, model=model, params=None
        )

        task_id = payload.get("task_id")
        if not task_id:
            # 【为什么不重试】响应是成功的（HTTP 2xx）却缺 id —— 这不是抖动，
            # 是**我们对响应的理解和它实际的样子不一致**。重试三次会拿到
            # 三次同样的东西，而用户白等三倍的时间。
            raise _final_failure(
                "MiniMax 受理了任务但没给 task_id（响应字段名可能与文档不一致）",
                meta,
            )

        return ProviderResult(
            output_duration_sec=0,
            # 【为什么是裸 task_id，不编前缀】即梦要把 `req_key` 编进句柄，
            # 是因为 `GetResult` 要求把提交时那个 `req_key` **再传一遍**，
            # 而 `poll` 的签名里只有句柄（拿不到 kind）。MiniMax 的查询
            # 接口**只要 task_id**，没有第二个要重传的东西 —— 所以这里
            # 没有可编的东西，编一个前缀只会是凭空多出来的格式。
            provider_task_id=str(task_id),
            provider_url=None,
            done=False,
            meta=meta,
        )

    def poll(self, provider_task_id: str) -> ProviderResult | None:
        """问一次。`None` = 还没好。

        `provider_task_id` 就是 `submit` 收到的那个裸 `task_id`。
        """
        path = f"{QUERY_PATH}/{provider_task_id}"
        payload, meta = self._send(
            "GET", path, body=None, model=self._settings.minimax_video_model, params=None
        )

        task = payload.get("task")
        if not isinstance(task, dict):
            # 成功状态码却拿不到 `task` 对象 —— 与「缺 task_id」同类：
            # 是我们对响应形状的理解不对，不是抖动。
            raise _final_failure(
                "MiniMax 的查询响应里没有 task 对象（响应形状可能与文档不一致）",
                meta,
            )

        # 【为什么用响应里的 model，而不是配置里的】任务可能是**换配置之前**
        # 提交的。对账表要回答的是「这一次调用花在哪个模型上」，
        # 而响应里那个 `task.model` 才是这一次的事实。
        model = task.get("model") or self._settings.minimax_video_model
        meta = ProviderCallMeta(
            http_status=meta.http_status,
            resp_code=meta.resp_code,
            resp_message=meta.resp_message,
            error_kind=meta.error_kind,
            req_key=str(model),
        )

        status = task.get("status")

        if status in (STATUS_QUEUED, STATUS_RUNNING):
            # ⚠️ 这里必须回 None 而不是「失败」：把「还没好」当成失败，
            #    用户的视频会在生成到一半时被判失败并退款，
            #    而 provider 那边还在跑、还会出片（白付一次）。
            return None

        if status == STATUS_FAILED:
            error = task.get("error")
            code = message = None
            if isinstance(error, dict):
                raw_code = error.get("code")
                code = None if raw_code is None else str(raw_code)
                raw_message = error.get("message")
                message = None if raw_message is None else str(raw_message)
            raise failure_from_code(
                code,
                "MiniMax 报这条任务生成失败" + (f"：{message}" if message else ""),
                provider="minimax",
                http_status=meta.http_status,
                meta=_with_upstream(meta, code=code, message=message),
            )

        if status == STATUS_CANCELLED:
            # 任务在 provider 那边被取消了。再问一万次也是这个答案 ——
            # 判死 + 全额退，与即梦的 `not_found` / `expired` 同一处置。
            raise _final_failure("MiniMax 那边这条任务已被取消（不会再好了）", meta)

        if status != STATUS_SUCCEEDED:
            # 未知状态：可能是我方解析错了，也可能是它新加了一种状态。
            # 保守地当「还没好」—— 等超时兜底（§8.2 的 `task_timeout_sec`
            # 会全额退款），比在这里猜一个终态安全。
            logger.warning("MiniMax 回了一个没见过的 status：%r（当成「还没好」）", status)
            return None

        url = _content_url(task)
        if not url:
            # 【为什么不在这里「找不到就退款了事」】这正是即梦 2026-10-15
            # 踩过的那个坑的另一副面孔：那一次是「成功却判失败」，
            # 这一次是「成功了但交付不出东西」。两者都是**我们不该
            # 静默吞掉**的 —— 响亮失败会留下 `error_code` 与一条
            # `provider_calls`，而静默退款什么都不留，下周还会再发生一次。
            raise _final_failure(
                "MiniMax 说 succeeded，但 content.url 是空的（字段名可能与文档不一致）",
                meta,
            )

        return ProviderResult(
            output_duration_sec=_duration_of(task),
            provider_task_id=provider_task_id,
            provider_url=url,
            done=True,
            meta=meta,
        )

    # ── 请求体 ─────────────────────────────────────────────

    def _reject_unsupported(self, request: GenerationRequest) -> None:
        """这个 provider 只走视频 —— 以及走视频时必须有的那几个前提。"""
        if request.kind is TaskKind.text_to_image:
            # 【为什么要有这一条（配置层已经拦过一次了）】纵深防御：
            # `model_post_init` 拦的是「配置写错」，这里拦的是
            # 「有人绕过配置直接把任务递进来」（测试、将来的批处理）。
            # 而且它可单测 —— 配置那条要动环境变量才能验。
            raise ProviderFailure(
                "MiniMax 这条路只走视频（图生视频 / 文生视频），不进文生图。"
                "文生图请留在即梦或 fake —— 见 ProviderKind.minimax 的说明。",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
            )

        if request.kind is TaskKind.image_to_video and not request.source_url:
            # 【为什么缺了它必须响亮失败】MiniMax 在**它自己的机房里**
            # 下这张图，所以它只能是一个公网 URL，不能是
            # `source_asset_id` 或本地路径（同 `base.GenerationRequest.source_url`
            # 上面那段）。没有地址就发过去的话，得到的是一个
            # 「参数错误 (2013)」—— 而那读起来像是我们拼错了字段，
            # 不是「参考图没有公网地址」。
            raise ProviderFailure(
                "图生视频缺参考图的公网地址（source_url 为空）—— "
                "MiniMax 要在自己的机房里下载它，所以只能是 URL。",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
            )

        seconds = request.requested_duration_sec
        if not (MIN_DURATION_SEC <= seconds <= MAX_DURATION_SEC):
            raise ProviderFailure(
                f"MiniMax 只支持 {MIN_DURATION_SEC}~{MAX_DURATION_SEC} 秒，"
                f"这次请求的是 {seconds} 秒（接口层没有上下界，见本模块顶部说明）。",
                code=ErrorCode.PROVIDER_ERROR.value,
                retryable=False,
            )

    def _submit_body(self, request: GenerationRequest) -> dict[str, Any]:
        """拼提交的 JSON。

        ─────────────────────────────────────────────────────
        【`content` 为什么是**数组**，而且 text 必须在里面】

        这是 MiniMax 与即梦最不一样的地方 —— 即梦是「一个 `prompt` 字段
        + 一个 `image_urls` 数组」，MiniMax 是**一个多模态 content 数组**，
        图像和文本是**平级的元素**，靠 `type` 与 `role` 区分用途。

        所以两个都必给：
          · `text` —— 文档明写「**所有场景都需包含一个非空 `text`**，
            缺失会返回参数错误」；
          · `image_url` + `role=first_frame` —— 图生视频的首帧。

        少任何一个都是 400。顺序按文档的示例：text 在前。
        ─────────────────────────────────────────────────────
        """
        content: list[dict[str, Any]] = [
            {"type": "text", "text": request.prompt}
        ]

        if request.kind is TaskKind.image_to_video:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": request.source_url},
                    "role": "first_frame",
                }
            )
            # 【为什么 ratio 写死 adaptive，而不是把用户选的 16:9 发过去】
            # 文档明说图生视频的宽高比**由输入图决定**，`ratio` 恒为
            # adaptive，传其他值「不会报错，但会被忽略」。
            # 把用户的 16:9 原样发过去是个**无害的谎**：它让下一个读这段
            # 代码的人以为那个值有用，于是哪天要调比例时会去改这里 ——
            # 而真正决定比例的是那张参考图。
            ratio = RATIO_ADAPTIVE
        else:
            # 文生视频（接口今天发不出这个 kind，见 `routers/generation.py`
            # 里「kind 恒为 image_to_video」那段说明；实现它是为了不留地雷）。
            # 文档：t2v 的 `ratio` **必填，且不能是 adaptive**。
            ratio = request.params.get("ratio") or DEFAULT_T2V_RATIO

        return {
            "model": self._settings.minimax_video_model,
            "resolution": self._settings.minimax_video_resolution,
            "duration": request.requested_duration_sec,
            "content": content,
            "ratio": ratio,
        }

    # ── HTTP ───────────────────────────────────────────────

    def _send(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None,
        model: str,
        params: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], ProviderCallMeta]:
        """发一次请求，返回 `(响应体, HTTP 摘要)`。

        【为什么返回 `meta` 而不是让它记日志】它要一路走到
        `provider_calls`（§11.1 的成本对账表）—— 那张表是回答
        「钱花在哪了」的唯一工具，而日志会被轮转掉。
        """
        settings = self._settings
        url = f"https://{settings.minimax_api_host}{path}"

        # 【为什么 meta 的 req_key 填的是模型名】`provider_calls` 那张表
        # **没有 provider 列**（见 `models.ProviderCall`），要靠 task_id
        # 关联 `tasks.provider` 才认得出是谁。把模型名填进 `req_key`
        # 是为了让「同一路上换过模型」这件事在成本表里留得下痕迹 ——
        # 它和即梦的 `req_key` 是同一个角色：决定单价的那个标识。
        meta_base = {"req_key": model}

        client = self._client or _http_client()
        headers = {
            # MiniMax 用 Bearer，**不签名**（不像即梦的 Signature V4 要把
            # AK 放进头里）。但它仍然是密钥：一个头都不记进库这条纪律
            # 不因为「这次不用签名」而放宽 —— 见 `models.ProviderCall`
            # 上面那段「绝不存 AK/SK、绝不存请求头」。
            "Authorization": f"Bearer {settings.minimax_api_key}",
            "Content-Type": "application/json",
        }

        try:
            if method == "POST":
                response = client.post(url, json=body, headers=headers, params=params)
            else:
                response = client.request(
                    "GET", url, headers=headers, params=params
                )
        except httpx.TimeoutException as exc:
            raise failure_from_code(
                None,
                f"调用 MiniMax 超时（{HTTP_TIMEOUT_SEC:.0f}s）",
                provider="minimax",
                meta=ProviderCallMeta(error_kind="timeout", **meta_base),
            ) from exc
        except httpx.HTTPError as exc:
            # `HTTPError` 是 httpx 的异常树根（连接失败、TLS、代理…）。
            # 全部归成 `connect`：对我们而言它们的处置一样（重试）。
            raise failure_from_code(
                None,
                f"调用 MiniMax 时网络失败：{type(exc).__name__}",
                provider="minimax",
                meta=ProviderCallMeta(error_kind="connect", **meta_base),
            ) from exc

        meta = ProviderCallMeta(http_status=response.status_code, **meta_base)

        if response.status_code >= 400:
            # ⚠️ 出错的响应**正文一定要读**。即梦那边 2026-10-15 吃过一次亏：
            #    唯独 `>= 400` 那条分支只记了状态码，而它恰恰是**唯一**
            #    能告诉我们病因的一类响应（密钥错、参数错、配额满全在这儿），
            #    于是四行 `provider_calls` 的 `resp_message` 全是 NULL。
            #    MiniMax 的病因就在 `error.message` 里，还带着内部码。
            code, message = _error_from_body(response)
            raise failure_from_code(
                code,
                f"MiniMax 回了一个 HTTP {response.status_code}",
                provider="minimax",
                http_status=response.status_code,
                meta=_with_upstream(meta, code=code, message=message),
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise failure_from_code(
                None,
                "MiniMax 的响应不是 JSON（可能是网关的错误页）",
                provider="minimax",
                meta=_with_upstream(
                    ProviderCallMeta(
                        error_kind="decode", **meta_base
                    ),
                    code=None,
                    message=response.text,
                ),
            ) from exc

        if not isinstance(payload, dict):
            raise failure_from_code(
                None,
                "MiniMax 的响应顶层不是一个对象",
                provider="minimax",
                meta=_with_upstream(
                    ProviderCallMeta(error_kind="decode", **meta_base),
                    code=None,
                    message=response.text,
                ),
            )

        return payload, meta


def _error_from_body(response: httpx.Response) -> tuple[str | None, str | None]:
    """从错误响应里取 `(内部码, 人话)`。

    MiniMax 的错误体是 **OpenAI 风格**：

        {"type": "error",
         "error": {"type": "unprocessable_entity_error",
                   "message": "video description contains sensitive content (1026)",
                   "http_code": "422"},
         "request_id": "..."}

    内部码**不在一个独立字段里**，而是写在 `message` 末尾的括号里 ——
    所以要用 `ERROR_CODE_RE` 抠。抠不出来就 `None`，落到按状态码那张表上。

    【为什么不用 `error.http_code` 当状态码】那个字段和真实 HTTP 状态码
    是同一个数（文档示例里 422 对 422），但它是个**字符串**、且是
    「对方说它回了几」——真正的 `response.status_code` 才是事实。
    保留它没有收益，所以这里只取 message 与内部码。
    """
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None

    code: str | None = None
    message: str | None = None

    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            raw_message = error.get("message")
            message = None if raw_message is None else str(raw_message)
        if message is None:
            # 也可能是一个更扁平的形状（或网关自己回的）。留一段文本 ——
            # 它常常是一张 HTML 错误页，而那正是「502 但后端以为自己在
            # 说人话」那种情况里唯一的线索。
            message = response.text
    else:
        message = response.text

    if message:
        found = ERROR_CODE_RE.search(message.strip())
        if found:
            code = found.group(1)

    return code, message


def _final_failure(message: str, meta: ProviderCallMeta) -> ProviderFailure:
    """一个**再问一万次也是这个答案**的失败。直接抛，不走错误码映射表。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么它不经过 `failure_from_code`】

    因为那两件事的判据不同：

      · `failure_from_code` 的判据是**对方给的码**（`1026` / 401…）——
        「这个码算不算审核、要不要重试」是个产品判断，所以它有一张
        共享的表（`moderation.MINIMAX_*`）。
      · 这里的判据是**响应根本没有我们要的那个形状**：HTTP 200、
        没有错误码、没有 `task_id` / `task` / `content.url`，
        或者状态是 `cancelled`。**没有码可查**，所以没有表可走。

    ⚠️ **这一条是被测试抓出来的，不是一开始就想清楚的。** 第一版
       让这几种情况也走 `failure_from_code(None, …)`，于是
       `_classify_minimax(None, 200)` 落到「未收录 = 可重试」上 ——
       而「重试三次拿三次同样的畸形响应」正是这些分支存在的理由。
       注释里写对了、代码里没做对，这就是为什么每条守真东西的
       测试都要故意改坏跑一遍。

    【为什么 `rejected=False` 要写出来而不是省掉】省掉也是 False
    （默认值），但写出来的意思是「这一点被想过」—— 一条「响应形状
    不对」的失败**绝不能**变成用户看到的「内容违规」。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    return ProviderFailure(
        message,
        code=ErrorCode.PROVIDER_ERROR.value,
        retryable=False,
        rejected=False,
        meta=meta,
    )


def _with_upstream(
    meta: ProviderCallMeta, *, code: str | None, message: str | None
) -> ProviderCallMeta:
    """把对方原始的错误码与它说的话塞进摘要（脱敏留给 `provider_audit`）。"""
    return ProviderCallMeta(
        http_status=meta.http_status,
        resp_code=code,
        resp_message=message,
        error_kind=meta.error_kind,
        req_key=meta.req_key,
    )


def _content_url(task: dict[str, Any]) -> str | None:
    """从 `task` 里取产物地址（`content.url`）。"""
    content = task.get("content")
    if not isinstance(content, dict):
        return None
    url = content.get("url")
    return url if isinstance(url, str) and url else None


def _duration_of(task: dict[str, Any]) -> int:
    """成片时长（秒）。**找不到就是 0。**

    【为什么 0 是安全的方向】计费按它算，而 0 意味着「收得最少」——
    真值拿不到时，宁可少收（平台吃亏）也不要凭请求时长猜一个
    （多收用户的钱，而 §7.2 明说多退少补以**实际**时长为准）。

    ⚠️ **待真调用确认**：文档里 `task.duration` 是「生成视频时长（秒）」，
    语义正对。真打过一次要顺手把这条注释删掉 —— 留着它会让下一个
    读的人以为这里还没接完。
    """
    value = task.get("duration")
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return 0
