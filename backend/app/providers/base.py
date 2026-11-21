"""provider 接口 —— §12.2 定稿的四个方法。

【为什么用 Protocol 而不是抽象基类】
因为「实现方」将来可能是一个包装过的第三方客户端，或者测试里的一个
lambda。Protocol 是结构化的：只要有这四个方法就算数，不需要显式继承。
frozen dataclass 同理 —— 请求和结果是**值**，不该被就地修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.enums import ErrorCode, TaskKind


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """一次生成的全部输入。

    ⚠️ **这里面绝不放 AK/SK。** 密钥只从环境变量读、只在真 provider
    的内部使用（《工程文档.md》§4 铁律）。把它塞进这个对象的话，
    它会被日志、被 `repr`、被将来某个调试端点一路带出去。
    """

    kind: TaskKind
    prompt: str
    params: dict[str, Any] = field(default_factory=dict)
    source_asset_id: int | None = None
    source_url: str | None = None
        # 【B6】参考图的**公网可达**地址。图生视频要把它交给即梦 ——
    # 而即梦在它的机房里下载，所以它只能是一个 URL，不能是
    # `source_asset_id` 或我们本地的一个路径。
    #
    # 【为什么不在这里拼，而是调用方传进来】因为「公网地址」是
    # **部署形态**决定的（本地是 `/media/...`、OSS 是桶的域名），
    # 而 provider 不该知道我们的存储长什么样。拼地址的活归
    # `Storage.url_for`，解析的活归调用方（worker / services）。
    #
    # ⚠️ 它与 `source_asset_id` 是**两件事**：那个是我们库里的编号
    #    （记账、追溯用），这个是给对方下载的地址。B6 之前只有前者，
    #    于是即梦那边拿到的是一个它无从解析的整数。
    #
    # 【为什么默认 None 而不是空串】「没有参考图」和「参考图地址是空的」
    # 是同一件事，但空串会在下游被 `if url:` 之外的地方漏过
    # （比如拼日志、拼请求体时变成一个空字段）。
    requested_duration_sec: int = 0
        # 用户下单时选的时长。**不是成片时长** —— 见下面 output_duration_sec。
    input_duration_sec: int = 0
        # 输入视频时长。图生视频的输入是一张图，所以 v1 恒为 0；
        # 留着是因为 §7.2 的冻结公式里有它，v2 接参考视频时会用上。


@dataclass(frozen=True, slots=True)
class ProviderCallMeta:
    """这次调用**在 HTTP 那一层**发生了什么（B5）。

    ─────────────────────────────────────────────────────────
    【为什么它是一份单独的东西，而不是塞进 `ProviderResult` 的几个字段】

    因为要记录它的有**两个**返回值形态：成功的 `ProviderResult`
    和出错的 `ProviderFailure`。而 `provider_calls`（§11.1 的成本对账表）
    恰恰对**出错的那一次**最感兴趣 —— 一次 50429 限流和一次 10000 成功
    在对账上是两件事。

    写成「每个值对象各加五个字段」的话，那五个字段会在两处各写一遍，
    然后其中一处迟早少一个（多半是 `error_kind`，因为它只在出错时有值）。

    ⚠️ **这里绝不放请求头、绝不放 AK/SK。** 见 `models.ProviderCall`
      上面那段 —— 即梦的签名把 AK 放在 header 里，而「把一次调用原样
       记下来好排查」正是最容易把密钥写进库的念头。
       所以这份结构里只有**响应侧**的摘要。
    ─────────────────────────────────────────────────────────
    """

    http_status: int | None = None
    """HTTP 状态码。**连不上时是 `None`** —— 那不是「状态码 0」，
    是「压根没拿到响应」，两者在对账时完全不同。"""

    resp_code: str | None = None
    """provider 的业务码（即梦的 `10000` / `50411` / `50429`…）。

    【为什么它和 `ProviderFailure.code` 是两个字段】
    那个是**我们**的错误码（`PROVIDER_ERROR` 这种，要进响应体），
    这个是**它**的原始码（只进库和日志）。混用的话，审计表里就分不出
    「即梦说 50429」和「我们说 PROVIDER_ERROR」—— 而前者才是能拿去
    跟对方对账的东西。
    """

    resp_message: str | None = None
    """对方说的话（已脱敏、已截断，见 `services/provider_audit.py`）。"""

    error_kind: str | None = None
    """网络层的异常分类：`timeout` / `connect` / `decode` / `http`。

    它和 `resp_code` 是**互斥**的两个世界：一个是「连上了它说不」，
    一个是「压根没连上」。两者的重试策略不同，所以不能合并成一个字段。
    """

    req_key: str | None = None
    """**provider 侧决定单价的那个标识。** 它对对账很重要：
    同一个 `submit` 动作，这个值不同就是不同的能力、不同的单价。

    · **即梦** —— 填它自己的 `req_key`（`jimeng_req_key_image` /
      `jimeng_req_key_video`）。它真的是即梦的**路由键**：请求体里
      发哪个 `req_key`，就调哪个能力。
    · **MiniMax** —— 填**模型名**（`MiniMax-H3-Max`）。MiniMax 没有
      `req_key` 这个概念（它的模型是在请求体的 `model` 字段里选的），
      所以这里填的是同一个角色、不同名字的东西。

    【为什么字段名不改】它是**落库的列名**（`provider_calls.req_key`），
    改名就是一次迁移，而这条链路上没有任何一个读它的人会因为
    名字叫 `req_key` 而误解 —— 真正会误解的是「以为它一定是即梦的
    路由键」，那由这段注释挡住。B6 之前这个字段恒为 None（fake 不发 HTTP）。
    """

@dataclass(frozen=True, slots=True)
class ProviderResult:
    """provider 回来的东西。

    [output_duration_sec] 是**成片实际时长**，计费按它算。
    它与 `requested_duration_sec` 的差异正是「多退少补」的来源，
    也是前端为什么禁止在按钮下写死价格（§13.4）。

    [done] **这个结果是不是终局**。B3 新增，理由见下面那段。
    """

    output_duration_sec: int = 0
    provider_task_id: str | None = None
    provider_url: str | None = None
        # ⚠️ 即梦的产物地址**只活 1 小时**，只作转存的瞬时中转。
        # 它绝不能出现在任何响应里（`TaskOut` / `AssetOut` 都没有它）。

    done: bool = False
    """`True` = 这就是成品，`False` = 这只是一张「已受理」的回执。

    ─────────────────────────────────────────────────────────
    【为什么 B2 没有它、B3 必须有】

    B2 里只有 `fake` 一个实现，而它**提交即完成** —— 于是
    「`submit` 回来了」和「做好了」是同一件事，调用方不需要区分。

    B3 要跨时间排队，就必然有两种 provider：「当场给结果」（fake）
    和「先给个句柄、靠 `poll` 等」（即梦）。而**调用方必须能分辨**：

      · 分不出来 → 要么把回执当成品直接结算（钱扣错、产物是空的），
      · 要么一律再问一次 `poll` → 对当场就完成的 provider 白跑一次
        网络往返，而真 provider 的 `submit` 是一次真实的 HTTP 调用。

    所以让 provider **自己说出来**。这不是给 fake 开的后门 ——
    B6 的即梦实现返回 `done=False`，走的是同一个分支判断。

    ⚠️ 别用 `output_duration_sec == 0` 当「没做好」的判据：文生图的
      成片时长**本来就是 0**，那个判据会把每一张图都判成未完成。
    ─────────────────────────────────────────────────────────
    """

    meta: ProviderCallMeta | None = None
    """这次调用的 HTTP 侧摘要（B5），进 `provider_calls` 对账表。

    【为什么默认 `None` 是诚实的，而不是「忘了填」】因为 fake 与
    测试替身**根本不发 HTTP** —— 给它们编一个 `http_status=200` 出来，
    对账表就会多出一批「看起来真的调用了即梦」的行。
    `None` 在这里的含义是「这个 provider 没有网络层」。
    """


class ProviderFailure(Exception):
    """provider 明确报错 —— `PROVIDER_ERROR` / `CONTENT_REJECTED` 的源头。

    ─────────────────────────────────────────────────────────
    【为什么不用 `AppError`】

    因为这两件事的**处置方式完全不同**：`AppError` 是要变成 HTTP 响应
    给用户的，而 `ProviderFailure` 多数时候发生在 **worker 里** ——
    那时早就没有请求可回了，用户看到的是任务变成 `failed`。
    硬塞进 `AppError` 的话，worker 得吞掉一个「本来是给 HTTP 用的」
    异常，还得假装它的 `status` 有意义。

    [retryable] §7.5 的重试纪律：限流/5xx 退避重试，
    **审核类错误重试一万次也是同样结果**，重试只是白花钱。
    默认 True 是**保守的方向**：一个没写 `retryable=False` 的新错误码
    会被重试三次（浪费几秒），而反过来会把「本来等一下就好」的
    限流直接判死、用户白等一场。
    ─────────────────────────────────────────────────────────
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = ErrorCode.PROVIDER_ERROR.value,
        retryable: bool = True,
        rejected: bool = False,
        meta: ProviderCallMeta | None = None,
    ) -> None:
        self.meta = meta
            # 【为什么出错的这一次也要带上 HTTP 摘要】对账价值最高的
            # 恰恰是失败的那些调用 —— 一次 50429 限流和一次 10000 成功
            # 在成本表上是两件事，而在「只记成功的调用」的实现里，
            # 前者**根本不存在**（调用方只看见一个异常）。
        self.code = code
            # provider 的原始错误码（比如即梦的 `50429`）。一路写进
            # `tasks.error_code` —— 没有它，线上一个「生成失败」无法归因。
        self.retryable = retryable
        self.rejected = rejected
            # §11.3：内容审核未通过是 `rejected` 而不是 `failed`。
            # 两者对用户的意义不同（一个是「换个词试试」，一个是
            # 「我们这边坏了」），所以必须是两个状态。
        super().__init__(f"{code}: {message}")


@runtime_checkable
class GenerationProvider(Protocol):
    """§12.2 的四个方法。"""

    name: str
    """写进 `tasks.provider` 列，用于**对账** —— fake 和 jimeng 的
    成本完全不同，混在一张表里而分不出来时，成本表就是错的。"""

    def freeze_amount(self, request: GenerationRequest) -> int:
        """下单时冻结多少。§7.2：`(输入时长 + 请求时长 + 余量) × 每秒单价`。"""
        ...

    def settle_amount(self, request: GenerationRequest, result: ProviderResult) -> int:
        """按**成片实际时长**该收多少。§7.2 ④：若超过冻结额，平台自担差额
        —— 那个钳位由调用方做，这里只报出「本该收多少」。"""
        ...

    def submit(self, request: GenerationRequest) -> ProviderResult:
        """提交生成。

        【为什么它是同步返回的】因为 v1 的形态由实现决定：`fake` 是
        「提交即完成」（见 `FakeProvider`），`jimeng` 会返回一个
        `provider_task_id` 然后靠 `poll` 等。返回类型对两种都成立。

        **看 `result.done` 判断这次是不是已经做完了**（B3 起）。
        没做完的话，`provider_task_id` 必须非空 —— worker 要靠它去
        `poll`。空 id 加 `done=False` 是一张无法兑现的回执，
        调用方只能等它超时。

        出错就抛 `ProviderFailure`（不要返回一个「失败的结果」——
        返回值那条路没有地方放 `retryable`，而重试与否正是
        §7.5 最要紧的一个判断）。
        """
        ...

    def poll(self, provider_task_id: str) -> ProviderResult | None:
        """问一次进度。`None` = 还没好。"""
        ...
