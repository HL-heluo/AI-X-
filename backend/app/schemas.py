"""响应形状与请求体 —— **全部契约断言的依据**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件的地位：它是「无信封」这条契约的落点】

§12.1 的表格只写了「返回 `{token}`」「返回 `{min,max,freeze}`」这种摘要。
真正精确的形状在**冻结的前端**里 —— 可执行规格是
`flutter_application_1/lib/data/mock/fake_api_client.dart`，它返回什么，
后端就得返回什么。这里逐字段对着它写。

三条绝不能违反的：
  1. **响应体没有信封**。顶层就是对象本身（`{"id":1,...}`），
     不是 `{"code":0,"data":{...}}`。
  2. **所有 id 是 JSON 整数**。前端四个模型的 `fromJson` 都走
     `requireInt()`，字符串会抛 `FormatException`。
  3. **`available` 与 `provider_url` 绝不出现在响应里**。
     前者由前端现算（`balance − frozen`），后者是即梦的临时地址
     （只活 1 小时）—— 两条都有前端守卫测试盯着。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【⚠️ 一条容易被顺手改掉的纪律：这里所有 `from_xxx` 都是**显式构造器**，
不用 `model_config = ConfigDict(from_attributes=True)`】

两个理由，都不是风格问题：

  · `Task.params_json` 是**列名**，而对外字段叫 `params` 且必须是**对象**。
    `from_attributes` 是按字段名去 ORM 对象上取属性的，列名对不上就取不到。
  · `CreditAccount.available` 是一个 **property**，而 `from_attributes`
    **能读到 property** —— 一旦给 `CreditAccountOut` 开了它，
    `available` 会被自动序列化进响应，直接把守卫测试打红。

显式构造器同时解决这两件事，且顺带让「这个字段从哪来」在代码里一眼可见。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.enums import AssetKind, LedgerKind, TaskKind, TaskStatus
from app.models import Asset, CreditAccount, CreditLedger, Task, User

T = TypeVar("T")


# ══════════════════════════════════════════════════════════════
# 用户 / 积分账户
# ══════════════════════════════════════════════════════════════


class UserOut(BaseModel):
    """对应前端 `User.fromJson`（`lib/models/user.dart`）。"""

    id: int
    username: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserOut:
        return cls(id=user.id, username=user.username, created_at=user.created_at)


class CreditAccountOut(BaseModel):
    """对应前端 `CreditAccount.fromJson`。

    ⚠️ **这里永远不能出现 `available` 字段。**
    前端 `CreditAccount.available` 是现算的 getter，服务端也不该存它
    （见 `app/models.py` 的 `CreditAccount` 类注释）。两边都不存，
    就不可能出现「余额 100、可用 80」这种对不上的数字。
    """

    balance: int
    frozen: int
    updated_at: datetime

    @classmethod
    def from_account(cls, account: CreditAccount) -> CreditAccountOut:
        return cls(
            balance=account.balance,
            frozen=account.frozen,
            updated_at=account.updated_at,
        )


class SessionOut(BaseModel):
    """注册 / 登录的返回：`{token, user, credit_account}`。

    【为什么超出 §12.1 的字面（文档只写 `{token}`）】
    因为登录后马上要进首页，而首页右上角就是积分胶囊。只给 token 的话
    必须再补一个 `/me`，用户会看到「进去了 → 积分那栏空一下 → 数字才出来」。
    前端的 `AuthSession` 就是这么期待的（见 `lib/models/auth_session.dart`）。
    """

    token: str
    user: UserOut
    credit_account: CreditAccountOut


class MeOut(BaseModel):
    """`GET /me` → 对应前端 `MeProfile.fromJson`。"""

    user: UserOut
    credit_account: CreditAccountOut


# ══════════════════════════════════════════════════════════════
# 积分流水
# ══════════════════════════════════════════════════════════════


class LedgerEntryOut(BaseModel):
    """对应前端 `CreditLedgerEntry.fromJson`。

    【`amount` 恒为正，方向看 `kind`】这是本项目拍板冻结的约定
    （见 `app/models.py` 的 `CreditLedger.amount`）。权威快照是
    `balance_after` / `frozen_after`，前端显示余额时以它们为准。

    【为什么带上 `user_id`】因为 Mock 的 `_writeLedger` 就带着它
    （`fake_api_client.dart:965`），对齐即可。它不泄漏任何东西
    （流水本来就按当前用户过滤过了）。前端解析时不读它。
    """

    id: int
    user_id: int
    kind: LedgerKind
    amount: int
    adjustment_debit: bool = False
    balance_after: int
    frozen_after: int
    task_id: int | None = None
    note: str | None = None
    created_at: datetime

    @classmethod
    def from_entry(cls, entry: CreditLedger) -> LedgerEntryOut:
        return cls(
            id=entry.id,
            user_id=entry.user_id,
            kind=entry.kind,
            amount=entry.amount,
            adjustment_debit=entry.adjustment_debit,
            balance_after=entry.balance_after,
            frozen_after=entry.frozen_after,
            task_id=entry.task_id,
            note=entry.note,
            created_at=entry.created_at,
        )


# ══════════════════════════════════════════════════════════════
# 任务
# ══════════════════════════════════════════════════════════════


class TaskOut(BaseModel):
    """对应前端 `Task.fromJson`（`lib/models/task.dart`）。

    ⚠️ **这里没有 `provider_url`，也不能加。**
    前端的 `Task` 模型刻意没有这个字段，并且有守卫测试盯着；
    即梦给的产物 URL 只活 1 小时，App 永远不该碰它。

    【`params` 为什么是裸 dict 而不是一个子模型】
    因为前端 `TaskParams.toJson` **省略掉值为 null 的键**
    （`{if (ratio != null) 'ratio': ratio, ...}`），而 `TaskParams.fromJson`
    对「键不存在」和「键是 null」是同样处理的。用一个 `dict` 直接透传
    存下来的那根 JSON，形状和 Mock 逐字一致，也不会出现
    「ratio: null」这种多出来的键。

    反过来说：**不要给这个模型开 `exclude_none`** —— `settled_amount`
    未结算时必须是显式的 `null`（不是缺字段），那是 `null` 与 `0` 的
    语义差别（见 `app/models.py` 文件头第 3 条）。
    """

    id: int
    kind: TaskKind
    status: TaskStatus
    prompt: str
    params: dict[str, Any] = Field(default_factory=dict)
    source_asset_id: int | None = None
    idempotency_key: str | None = None
    freeze_amount: int
    settled_amount: int | None = None
    input_duration_sec: int | None = None
    output_duration_sec: int | None = None
    error_code: str | None = None
    error_msg: str | None = None
    queue_position: int | None = None
    created_at: datetime
    queued_at: datetime | None = None
    submitted_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_task(cls, task: Task, *, queue_position: int | None = None) -> TaskOut:
        """显式构造 —— 见本文件头的说明。

        [queue_position] 由调用方算好传进来（service 层知道队列的全貌）。
        **不要**把它做成 `Task` 上的 property：那会让 `from_attributes`
        那条路重新变得可行，而那条路会把 `available` 那类 property 一起
        带出去。
        """
        return cls(
            id=task.id,
            kind=task.kind,
            status=task.status,
            prompt=task.prompt,
            params=_decode_params(task.params_json),
            source_asset_id=task.source_asset_id,
            idempotency_key=task.idempotency_key,
            freeze_amount=task.freeze_amount,
            # 未结算时这里是 None → JSON 里是 `null`。**不能写成 0**，
            # 表约束也钉了这一条（tasks.ck_tasks_succeeded_implies_settled）。
            settled_amount=task.settled_amount,
            input_duration_sec=task.input_duration_sec,
            output_duration_sec=task.output_duration_sec,
            error_code=task.error_code,
            error_msg=task.error_msg,
            queue_position=queue_position,
            created_at=task.created_at,
            queued_at=task.queued_at,
            submitted_at=task.submitted_at,
            finished_at=task.finished_at,
        )


def _decode_params(raw: str | None) -> dict[str, Any]:
    """把 `params_json` 那根字符串解成对象。

    【为什么容错到「解不开就当空对象」】因为这是一个**展示**字段：
    它坏了不该让整个任务接口 500（那会让用户连"任务失败了"都看不到）。
    真正要紧的字段（金额、时长）都另有独立的列，不从这里走。
    """
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


class TaskListOut(BaseModel):
    """`GET /tasks` 的返回：**不是分页接口**。

    ─────────────────────────────────────────────────────────
    【为什么它和 `PageOut` 是两个模型，而不是共用一个 `Paged[TaskOut]`】

    §12.1 里 `/tasks` **没有分页参数**，语义是「给我全部（按状态筛）」。
    前端 `RemoteTaskRepository._fetchList` 专门写了注释解释它为什么
    **不用** `Paged.fromJson`：「借 Paged 来解包会让人误以为这里有翻页，
    读代码的人会去找一个根本不存在的 page 参数」。

    所以这里刻意用两个不同的模型。共用一个的话，读到
    `response_model=Paged[TaskOut]` 的人会去找那两个不存在的查询参数。
    ─────────────────────────────────────────────────────────

    那几个 `page` / `page_size` / `total` 字段**要发**（Mock 就发），
    只是它们的值是平凡的：`page=1`、`page_size=total=len(items)`。
    【为什么 page_size 是 len(items) 而不是 20】因为默认 20 会让
    第 21 条任务**静默消失** —— 前端拿到 `items` 就渲染，从不翻页。
    """

    items: list[TaskOut]
    page: int = 1
    page_size: int
    total: int


# ══════════════════════════════════════════════════════════════
# 资产
# ══════════════════════════════════════════════════════════════


class AssetOut(BaseModel):
    """对应前端 `Asset.fromJson`（`lib/models/asset.dart`）。

    ⚠️ **绝不出现 `storage_key`**：那是我们对象存储里的内部路径，
    换存储/换域名时要改的是它，对外只该有 `public_url`。
    ⚠️ **绝不出现 `provider_url`**：理由同 `TaskOut`。
    """

    id: int
    user_id: int
    kind: AssetKind
    task_id: int | None = None
    public_url: str
    mime: str | None = None
    size_bytes: int | None = None
    duration_sec: int | None = None
    width: int | None = None
    height: int | None = None
    is_ai_generated: bool
    created_at: datetime

    @classmethod
    def from_asset(cls, asset: Asset) -> AssetOut:
        return cls(
            id=asset.id,
            user_id=asset.user_id,
            kind=asset.kind,
            task_id=asset.task_id,
            public_url=asset.public_url,
            mime=asset.mime,
            size_bytes=asset.size_bytes,
            duration_sec=asset.duration_sec,
            width=asset.width,
            height=asset.height,
            # 【必须是真的 JSON 布尔】前端 `boolOr` 对 `'true'`（字符串）
            # 和 `1`（数字）**都抛异常** —— 它刻意不接受「像布尔的东西」，
            # 因为这一列是法律义务字段（§10.1）。
            is_ai_generated=asset.is_ai_generated,
            created_at=asset.created_at,
        )


# ══════════════════════════════════════════════════════════════
# 通用分页 / 问价 / 上传 / 删除
# ══════════════════════════════════════════════════════════════


class PageOut(BaseModel, Generic[T]):
    """**真分页**接口的返回：`/credits/ledger` 与 `/assets`。

    对应前端 `Paged.fromJson`：它读 `items`（也兼容 `list`）、
    `page`（**从 1 起**）、`page_size`、`total`。
    """

    items: list[T]
    page: int
    page_size: int
    total: int


class CostOut(BaseModel):
    """`GET /generation/cost` → 对应前端 `TaskCostEstimate.fromJson`。

    【为什么是「区间 + 冻结额」而不是一个确定数字】
    成片时长由 provider 侧的 Agent 自主决定，下单那一刻**连后端也不知道**
    最终会扣多少（§7.2）。前端据此禁止在按钮下写确定数字（§13.4）。
    """

    min: int
    max: int
    freeze: int


class UploadOut(BaseModel):
    """`POST /uploads/image`。

    【为什么同时给 `asset_id` 和 `public_url`，这是刻意的】
    §12.1 的表格说这个接口「返回公网 URL」，但 `/generation/video` 要的
    参数却是 `source_asset_id` —— 文档自相矛盾。两个都给，App 就能
    用 id 提交、用 URL 显示预览。前端 `RemoteAssetRepository.uploadImage`
    取的是 `asset_id`，取不到会直接 `StateError`。
    """

    asset_id: int
    public_url: str


class OkOut(BaseModel):
    """`DELETE /assets/{id}` 之类的「就一个 ok」返回。

    前端忽略 body（`RemoteAssetRepository.delete` 连解包都不解），
    但形状对齐 Mock（`{'ok': true}`）是免费的。
    """

    ok: bool = True


class ErrorOut(BaseModel):
    """错误响应的形状。**只用于自动生成的 OpenAPI 文档**。

    真正的错误响应由 `app/errors.py` 的处理器直接产出 —— 走
    `response_model` 的话，`DUPLICATE_REQUEST` 那个额外的 `task` 字段
    会被过滤掉，而这正是它存在的意义。
    """

    code: str
    message: str


# ══════════════════════════════════════════════════════════════
# 请求体
# ══════════════════════════════════════════════════════════════
#
# ⚠️ 一条贯穿下面所有请求模型的纪律：
#
#    **业务校验一律放 service，不写进 pydantic 的 Field 约束。**
#
# 原因是一个真实的失败：`repository_layer_test.dart` 里有条用例要求
# `submitImage(prompt: '')` 返回 `INVALID_PROMPT`。如果这里写
# `prompt: str = Field(min_length=1)`，空串会**先被 pydantic 拦成
# `INVALID_REQUEST`**，那条用例就红了 —— 而且红得让人摸不着头脑：
# 服务端确实拒绝了，只是拒绝的理由码不对。
#
# 所以下面这些字段都声明成裸类型，长度/空值判断在 service 里显式做。


class RegisterIn(BaseModel):
    """§6.1：注册必须带邀请码。"""

    invite_code: str
    username: str
    password: str


class LoginIn(BaseModel):
    username: str
    password: str


class ImageGenIn(BaseModel):
    """`POST /generation/image`（文生图）。

    【注意这里的字段名是 `aspect_ratio`】而视频接口用的是 `ratio` ——
    §12.1 的表格里两个接口的字段名**就是不一样**。对外照抄契约，
    对内统一归一成 `TaskParams.ratio`（见 `services/generation.py`）。
    """

    prompt: str
    idempotency_key: str
    aspect_ratio: str | None = None


class VideoGenIn(BaseModel):
    """`POST /generation/video`（图生视频）。

    【`source_asset_id` 为什么是 int，而前端发的是字符串】
    前端 `Asset.id` 是 `String`（`requireInt(json['id']).toString()`），
    所以发过来的是 `"1001"`。pydantic 的非严格模式会把数字字符串
    收成 `1001` —— ⚠️ **千万不要给它加 `strict=True`**，加了会直接 400。
    """

    prompt: str
    idempotency_key: str
    source_asset_id: int | None = None
    duration: int = 5
    ratio: str | None = None


class GrantCreditsIn(BaseModel):
    """`POST /__test/grant`：给某个用户凭空加积分（§15.1 的管理员脚本）。"""

    username: str
    amount: int
    note: str | None = None


# ══════════════════════════════════════════════════════════════
# 影子链（方案 B）
# ══════════════════════════════════════════════════════════════


class ChainOpOut(BaseModel):
    """一条链上影子操作（mint / consume）。`tx_hash` 为空表示还没上链。"""

    id: int
    kind: str
    amount: int
    tx_hash: str | None = None
    status: str
    ref: str
    created_at: str | None = None


class ChainSummaryOut(BaseModel):
    """`GET /credits/chain`：给用户的「链上凭证」。

    字段可以和平台账本对账：`on_chain_balance` 与 `ledger_balance`
    不一致时，说明链上还有待同步的操作（worker 会重试）。
    """

    enabled: bool
    contract: str | None = None
    chain_id: int | None = None
    address: str | None = None
    on_chain_balance: int | None = None
    ledger_balance: int
    available_balance: int | None = None
    sync_status: str = "disabled"
    total_supply: int | None = None
    recent_ops: list[ChainOpOut] = Field(default_factory=list)
    error: str | None = None


class EvidenceOut(BaseModel):
    status: str
    evidence_id: str | None = None
    sha256: str | None = None
    network_id: str | None = None
    channel: str | None = None
    chaincode: str | None = None
    tx_id: str | None = None
    recorded_at: datetime | None = None
    confirmed_at: datetime | None = None
