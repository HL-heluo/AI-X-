"""枚举 —— **全项目唯一定义处**。

《工程文档.md》§0.4 立了「术语锁定」的规矩：一处写 `canceled`、
另一处写 `cancelled`，最后就对不上了。所以状态、类型这些**要写进数据库、
要跨版本兼容、要跟前端对齐**的字符串，全部只在这里定义一次，别处引用。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么每个枚举都单独存一个 `value`，而不是直接用成员名】

Python 的 `StrEnum` 成员名看起来够用（`TaskStatus.canceled` 的
`str()` 就是 `"canceled"`）。但把**对外契约**和**代码里的标识符**绑死
是危险的：哪天有人把成员重命名成 `cancelled`，序列化会静默跟着变，
而已经写进数据库的值、已经发给前端的值都还是 `canceled`。

前端 `lib/core/constants/task_status.dart` 踩的是同一个坑，
它的注释写得比这里更细 —— 两边刻意保持一致。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """任务状态。§11.3 定义 8 个。

    ⚠️ 与前端 `lib/core/constants/task_status.dart` 的 `TaskStatus`
    **逐字对齐**。前端的 `fromWire` 认不出来会**抛异常**
    （它拒绝静默退化），所以这里多一个或少一个都会当场炸。

    【为什么 8 个而不是 §11.2 表格里写的 7 个】
    §11.2 的 `tasks.status` 行写「§8.3 的 7 个状态之一」，但 §11.3
    自己列的是 8 个，§8.3 → §11.3 才是权威，且前端枚举与 Mock 都是 8 个。
    这是文档自身的一处笔误，不是后端 bug。
    """

    pending = "pending"
    """已创建，待入队。"""

    queued = "queued"
    """排队中，未提交 provider。**只有这个状态可以取消并全额退回**（§7.4）。"""

    submitted = "submitted"
    """已提交 provider，处理中。"""

    succeeded = "succeeded"
    """成功，产物已转存。**这个状态必须有 settled_amount**（见表约束）。"""

    failed = "failed"
    """provider 报错 / 超时 / 转存重试耗尽。"""

    rejected = "rejected"
    """内容审核未通过。§7.4：全额退回，且**绝不重试**。"""

    canceled = "canceled"
    """用户取消。"""

    expired = "expired"
    """超过 provider 的 12 小时窗口。"""

    @property
    def is_terminal(self) -> bool:
        """终态：不会再变了。

        【为什么这个判断也要在服务端有一份】App 靠它决定「还要不要继续轮询」，
        服务端靠它决定「还能不能取消」「要不要退积分」。两边各写一份
        `if status in (...)` 是漏项的经典来源 —— 漏掉一个终态就是
        一个永远转下去的定时器，或者一次重复退款。
        """
        return self in _TERMINAL

    @property
    def is_active(self) -> bool:
        """进行中。正好对应 `GET /tasks?status=active`。"""
        return not self.is_terminal


_TERMINAL = frozenset(
    {
        TaskStatus.succeeded,
        TaskStatus.failed,
        TaskStatus.rejected,
        TaskStatus.canceled,
        TaskStatus.expired,
    }
)
"""终态的**唯一清单**。

⚠️ 独立成一个 frozenset 而不是在 `is_terminal` 里写 `if`，
是为了让「哪些是终态」成为一个**可以被测试直接遍历**的数据 ——
下面 `tests/` 里有条测试会遍历它，确认前端认为终态的那几个
和这里完全一致。
"""

ACTIVE_STATUSES = frozenset({TaskStatus.pending, TaskStatus.queued, TaskStatus.submitted})
"""/tasks?status=active 的筛选清单。"""

TERMINAL_STATUSES = _TERMINAL
"""/tasks?status=done 的筛选清单。就是 `_TERMINAL` 的公开别名。

【为什么不直接在 service 里写 `{s for s in TaskStatus if s.is_terminal}`】
因为那会在每次请求里重建一个 frozenset，而且 —— 更要紧的 ——
「哪些是终态」这件事就有了第二个出处。`_TERMINAL` 上面那段注释
明说了它存在的意义就是「成为唯一一份可被遍历的清单」。
这里只是给它起一个能对外用的名字（下划线打头的名字不该跨模块引用）。"""


class TaskKind(StrEnum):
    """任务类型。§11.2。

    【为什么 `text_to_video`（v2 的能力）现在就要写进枚举】
    因为「类型」是要**写进数据库**的东西。v1 只定义两个的话，
    等 v2 加第三个时，老版本 App 拿到 `text_to_video` 会解析失败
    （前端的 `TaskKind.fromWire` 认不出就抛）。提前占位，
    老版本至少能显示成「未知类型」而不是崩掉。

    【注意「枚举里有」≠「界面上能选」】v1 的创作页只放图片/视频两个模式，
    文生视频的入口由后端能力开关控制，不由这个枚举控制。
    """

    text_to_image = "text_to_image"
    image_to_video = "image_to_video"
    text_to_video = "text_to_video"


class AssetKind(StrEnum):
    """资产类型。§11.2。

    【为什么缩略图是一种**独立的**资产，而不是视频的附属字段】
    因为它们是三个独立的文件，各有独立的大小和存储地址。
    视频列表一屏要显示 9 个视频，如果每个都直接加载视频文件当封面，
    流量和内存都会炸。缩略图是单独的一张图，列表读它，点开才读视频。
    """

    image = "image"
    video = "video"
    thumbnail = "thumbnail"


class LedgerKind(StrEnum):
    """积分流水类型。§7.3。

    【为什么是五种，而不是简单记「充了」「扣了」】
    因为冻结/结算/退回是三段式，一次生成会留下最多三条记录。
    压成一条「扣了 24」的话，用户来问「为什么我刚下单就少了 32」时，
    账本上根本查不出答案 —— 这是对账能力的底线。

    ⚠️ `amount` 恒为正数，**方向靠 kind 推导**。见
    `app/services/credits.py` 与前端 `CreditLedgerKind.reducesAvailable`。
    """

    grant = "grant"
    """赠送（注册送 50 积分记这个）。"""

    freeze = "freeze"
    """冻结（下单预扣）。**总余额不变**，只是从可用搬到了冻结。"""

    settle = "settle"
    """结算（按实际成片时长扣走）。**只有它真正减少总余额。**"""

    refund = "refund"
    """退回（任务失败全退，或成功时退回多冻结的部分）。"""

    adjust = "adjust"
    """人工调整（客服补积分等，App 端只读）。"""


class TransferState(StrEnum):
    """转存状态 —— **内部状态，绝不作为公开状态暴露**。

    ─────────────────────────────────────────────────────────
    【为什么需要它：§9.3 发明了第 9 个状态，但前端只认 8 个】

    §9.3 描述了一个「生成成功但转存失败」的情形。天真的做法是给它
    加一个公开状态 `transfer_failed`，但前端的 `TaskStatus.fromWire`
    遇到未知状态会**抛异常** —— 也就是说，后端加了这个状态，
    用户看到的就是**白屏或崩溃**，而不是「生成失败，积分已退」。

    所以这里的做法是：转存过程**藏在 `submitted` 后面**。
    重试期间公开状态仍是 `submitted`（前端显示「生成中」，是对的 ——
    用户确实还在等）；重试耗尽才转成 `failed`，
    并在 `error_code` 上写 `TRANSFER_FAILED`。

    这就是「不自造公开状态」这条决定的落点：内部可以有多细，
    对外只有那 8 个。
    ─────────────────────────────────────────────────────────
    """

    none = "none"
    """不需要转存（比如任务还在排队）。"""

    running = "running"
    """正在下载 → 上传到我们自己的存储。"""

    done = "done"
    """转存完成，产物已是永久 URL。"""

    failed = "failed"
    """重试耗尽。此时任务会转成公开状态 `failed`。"""


# 错误码常量。§12.3 的八个 + 明确点名的追加项。
#
# 【为什么错误码是字符串常量而不是枚举】因为它们会**原样出现在响应体**里，
# 且前端只认字符串。用 `StrEnum` 也行，但这里的关键是：
# **每一处 raise 都必须引这里的常量**，不许写字面量 ——
# 写字面量的话，某处打错一个字母，前端就认不出来了，
# 而认不出来的表现是那句撒谎的「连不上服务器，检查一下网络再试」。
class ErrorCode(StrEnum):
    """§12.3 平台对外错误码。"""

    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"  # 400 可用积分不足
    INVALID_PROMPT = "INVALID_PROMPT"  # 400
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"  # 400
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"  # 409 幂等重放，体里带已有 task
    RATE_LIMITED = "RATE_LIMITED"  # 429
    CONTENT_REJECTED = "CONTENT_REJECTED"  # 422
    PROVIDER_ERROR = "PROVIDER_ERROR"  # 502
    QUEUE_SATURATED = "QUEUE_SATURATED"  # 503
    # ── 以下为契约缺口补齐，理由见 HANDOFF §5 与 §3.2 ──
    UNAUTHORIZED = "UNAUTHORIZED"  # 401
    NOT_FOUND = "NOT_FOUND"  # 404
    USERNAME_TAKEN = "USERNAME_TAKEN"  # 409
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"  # 401
    INVITE_INVALID = "INVITE_INVALID"  # 400
    TASK_NOT_CANCELABLE = "TASK_NOT_CANCELABLE"  # 409
    """任务已经是终态了，不能取消。

    【为什么必须补这个码】§12.3 没有它，而 Mock 的 `_cancelTask` 给出了
    一个 409 + 一句具体的话（`任务已经是已完成，不能再取消`）。但那时
    前端的 `AppException.code` 是 **null**，`userMessage` 会退回到
    「出错了，请稍后重试」—— 用户看不懂。

    ⚠️ 补上之后前端**仍然认不出**这个码（它在 F8 只加了 INVITE_INVALID），
    所以文案依旧走通用兜底。真正的收益是**服务端日志里能看出是哪一类冲突**，
    以及给别人用 curl 打时有一个说得清的错误码。前端要显示精确文案的话，
    得在 `ApiErrorCode` 里补一条 —— 那是 F 侧的一次小改动，不属于 B2。
    """

    INVALID_REQUEST = "INVALID_REQUEST"  # 400
    """请求体**形状**不对（缺字段、类型不对、路径参数不是数字）。

    ─────────────────────────────────────────────────────────
    【为什么它必须存在，而不是沿用 FastAPI 默认的 422 + `{"detail":[...]}`】

    那个默认形状**破了「无信封」这条契约**：前端的 `DioApiClient._toException`
    从顶层读 `code` 和 `message`，读到的是两个 null —— 于是用户看到的是
    那句开发者兜底的「服务端返回 HTTP 422，且响应体里没有 message 字段」。

    【为什么它在前端认不出来也没关系】
    `ApiErrorCode.tryFromWire` 对未知码返回 null（宽松），所以走到这里的
    请求会退化成通用文案。而这一条路径前端**够不到** —— 前端有本地校验，
    真发出去的一定有 `prompt` / `idempotency_key`。它是一条给
    「用 curl 手打」和「将来某个新客户端写错了」用的兜底，不是业务错误。

    ⚠️ 正因如此，**业务校验绝不许借用这个码**。空提示词要抛的是
    `INVALID_PROMPT`（前端认它，会说「提示词不能为空，且不超过 2000 字」）；
    借用这个码的话，用户会看到一句和真实原因无关的通用文案。
    ─────────────────────────────────────────────────────────
    """


class TaskErrorCode(StrEnum):
    """写进 `tasks.error_code` 的**内部**码（B4）。

    ─────────────────────────────────────────────────────────
    【为什么它和 `ErrorCode` 是两个东西，而不是一张表】

    上面那张是**对外**的：它的值会原样出现在响应体里，前端按它选文案。
    这张是**对内**的：它只进数据库、只进日志，从不作为响应里的 `code`
    出现 —— 用户看到的仍然是 `TaskStatus` 那 8 个状态之一。

    混成一张表会立刻造成一个错误：有人看到 `TRANSFER_FAILED` 在前端
    认不出来，就去前端补一条映射 —— 于是「转存失败」变成了一个
    前端要显示的状态，而那正是 §9.3 明确禁止的（前端 8 个状态，
    多一个会白屏）。

    【为什么 `TASK_TIMEOUT` 也搬进来】它本来在
    `generation.expire_stale` 里是一个字符串字面量。项目里已经有
    「错误码不许写字面量」这条约定 —— 内部码同样是码，
    哪天有人 grep `TRANSFER_FAILED` 找「转存失败的任务」，
    字面量拼错一个字母就漏掉一整类记录，而 SQL 不会报错。
    ─────────────────────────────────────────────────────────
    """

    TRANSFER_FAILED = "TRANSFER_FAILED"
    """转存重试耗尽。§9.3：任务是 `failed`，积分**全额**退回。

    【为什么是全额退，而不是「按已生成的成片扣」】成片在 provider 那边
    确实做出来了，但我们**没把它交付出去** —— 用户什么都没拿到。
    §7.6 的退款纪律就一条：没交付就全退。按内部状态扣钱的话，
    用户会为一份他永远看不到、也永远不会出现在他作品页里的文件付钱。
    """

    TASK_TIMEOUT = "TASK_TIMEOUT"
    """超过 `task_timeout_sec` 仍是活跃状态 → `expired` + 全额退回。"""


__all__ = [
    "AssetKind",
    "ErrorCode",
    "LedgerKind",
    "TaskErrorCode",
    "TaskKind",
    "TaskStatus",
    "TransferState",
]
