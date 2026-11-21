"""数据模型 —— §11 的 7 张表。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【三条从冻结的前端反推出来的硬约束，改这里之前先读一遍】

1. **所有主键必须是 INTEGER。**
   前端四个模型的 `fromJson` 都走 `json.requireInt(json['id'])`，
   字符串会直接抛 `FormatException`。所以主键一律
   `Mapped[int] = mapped_column(primary_key=True)`，
   **不要**图省事用 UUID —— 那会让每一个详情接口都炸。

2. **`is_ai_generated` 必须是真布尔。**
   前端的 `boolOr` 对 `'true'`（字符串）和 `1`（数字）**都抛异常**，
   它刻意不接受「像布尔的东西」。这一列是法律义务字段（§10.1），
   静默变成 false 意味着合规标识不显示，所以那边选择了响亮地失败。

3. **`settled_amount` 未结算时是 NULL，不是 0。**
   前端把它解析成 `int?`，`null` 和 `0` 是两回事：
   `null` = 「还不知道最终扣多少」，`0` = 「确实没扣」。
   表约束里也钉了这一条（见 `tasks` 的 CheckConstraint）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import (
    ACTIVE_STATUSES,
    AssetKind,
    LedgerKind,
    TaskKind,
    TaskStatus,
    TransferState,
)
from app.types import EnumStr, UtcDateTime, utcnow


def _enum_check(column: str, enum_cls: type) -> CheckConstraint:
    """给字符串列生成一条「值必须在这个枚举里」的 CHECK 约束。

    【为什么要手工写 CHECK，而不是让应用层保证】
    因为应用层有一条路径是**绕过**的：将来某天有人为了修数据直连
    数据库跑一句 UPDATE，或者写迁移脚本时拼错一个状态名。
    CHECK 约束是唯一能在数据库层面挡住这类写入的东西，
    而它挡住的方式是**当场报错**，不是几个月后有人发现状态对不上。
    """
    allowed = ", ".join(f"'{m.value}'" for m in enum_cls)  # type: ignore[attr-defined]
    return CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{column}_is_known")


# ══════════════════════════════════════════════════════════════
# 1. users
# ══════════════════════════════════════════════════════════════


class User(Base):
    """账号。§6.1：邀请制 + 用户名/密码。"""

    __tablename__ = "users"

    evidence_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)

    id: Mapped[int] = mapped_column(primary_key=True)

    username: Mapped[str] = mapped_column(String(32), nullable=False)
    """用户看到的用户名，原样保留大小写。"""

    username_canonical: Mapped[str] = mapped_column(String(32), nullable=False)
    """用于唯一性判断的规范化形式（casefold + strip）。

    ─────────────────────────────────────────────────────────
    【为什么多存一列，而不是直接给 username 建唯一索引】

    因为「唯一」这件事必须定义**在哪个等价类上**。如果直接给
    `username` 建唯一索引，那么 `Bob` 和 `bob` 是两个不同的账号 ——
    于是：用户在手机上注册了 `Bob`，换台设备打字打成了 `bob`，
    **登录失败，而且注册也失败**（他会被告知「bob 已被占用」，
    而占用它的正是他自己）。这类工单没有技术手段能查清楚。

    多存一列规范化形式，唯一索引建在它上面，`Bob` 和 `bob` 就是同一个账号。
    规范化在写入时算一次（见 `app/services/`），读取路径上没有开销。

    ⚠️ 用 `casefold()` 而不是 `lower()`：`lower()` 对某些字符
    （如德语 ß、土耳其语 İ）给出的不是大小写无关的等价类。
    用户名最终会限制成 ASCII（B2 加校验），但这里是最后一道，
    按最严格的标准做。
    ─────────────────────────────────────────────────────────
    """

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    """bcrypt 哈希。§6.1：**绝不存明文**。

    长度给 255 是因为 bcrypt 的产出约 60 字符，而将来若换 argon2
    或加算法前缀（`$argon2id$...`）会更长 —— 换算法时不想再改表。"""

    invite_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("invite_codes.id", ondelete="SET NULL"), nullable=True
    )
    """注册时用的邀请码。§7.5 靠它控量，所以要留痕。

    `ondelete="SET NULL"`：删掉一个邀请码不该让用它注册的用户消失。
    """

    # ── 为升级预留（§6.2）──────────────────────────────────
    # 【为什么现在就把 v3 的字段建出来】因为加列要写迁移、要停机窗口，
    # 而现在建它们的成本是零。§6.2 明确要求「v3 接真支付和实名时
    # 不需要改表结构」。
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    wechat_openid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    real_name_verified_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    """实名认证通过的时刻。§6.3 的法律冲突落地在这个字段上：v1 恒为 NULL。"""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """软禁用。**不删用户** —— 他有流水和作品，删了账就对不上了。"""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    credit_account: Mapped[CreditAccount] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("username_canonical", name="uq_users_username_canonical"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


# ══════════════════════════════════════════════════════════════
# 2. invite_codes
# ══════════════════════════════════════════════════════════════


class InviteCode(Base):
    """邀请码。§6.1：注册必须带邀请码。

    邀请制不只是控量，§7.5 把它列为「成本自保的四道闸」之一 ——
    用户总量受控等于花销总量受控。所以这张表是**花钱的闸门**，
    不是普通的业务表。
    """

    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(primary_key=True)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    """邀请码本体。唯一 —— 见 __table_args__。"""

    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """备注（「发给谁的」「哪一批」）。运维排查时要靠它认人。"""

    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """可用次数上限。**NULL = 不限次**。

    【为什么可空而不是用一个大数字】「不限次」和「限 99999 次」是
    两种不同的意图，用同一个数字表达会让后来的人猜。
    """

    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    """过期时刻。NULL = 永不过期。"""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """手动停用。删掉一个已用过的邀请码会让用户的 `invite_code_id` 悬空，
    所以停用是「置 false」而不是「DELETE」。"""

    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """谁生成的。CLI 脚本生成时为 NULL（没有「操作者」这个用户）。

    ─────────────────────────────────────────────────────────
    【⚠️ 这一列**没有**外键约束，和有外键的 `users.invite_code_id` 不对称】

    原因是一个**循环外键**：`users.invite_code_id → invite_codes.id`
    和 `invite_codes.created_by → users.id` 互相指向对方，
    于是没有一张表能先建。

    SQLAlchemy 在这种情况下会打印

        SAWarning: Cannot correctly sort tables; there are unresolvable
        cycles between tables "invite_codes, users" ... Foreign key
        constraints involving these tables will not be considered

    然后**照常生成迁移**。而在 SQLite 上它确实能跑通 ——
    SQLite 建表时不校验外键指向的表是否存在。**这就是坑**：
    本地一路绿灯，等按 §4.1 的计划迁到 PostgreSQL 时，
    这套迁移会在 `CREATE TABLE invite_codes` 那句直接失败，
    报一个「被引用的表不存在」，而那时已经没人记得今天的取舍。

    所以现在就把环断掉。断在这里而不是断在 `users.invite_code_id`，
    是因为那个方向的引用更有价值：它记录「这个用户是用哪个码注册的」，
    正是 §7.5 邀请闸门的审计依据。

    代价是删用户后 `created_by` 会留一个幽灵 id。可以接受 ——
    我们**从不硬删用户**（用 `is_active` 软禁用，见 `User.is_active`），
    所以这个场景在实际运行中不会发生。
    ─────────────────────────────────────────────────────────
    """

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("code", name="uq_invite_codes_code"),
        CheckConstraint("used_count >= 0", name="ck_invite_codes_used_count_nonneg"),
        CheckConstraint(
            "max_uses IS NULL OR max_uses > 0", name="ck_invite_codes_max_uses_positive"
        ),
        CheckConstraint(
            "max_uses IS NULL OR used_count <= max_uses",
            name="ck_invite_codes_not_overused",
        ),
    )

    def __repr__(self) -> str:
        return f"<InviteCode id={self.id} code={self.code!r} used={self.used_count}>"


# ══════════════════════════════════════════════════════════════
# 3. credit_accounts
# ══════════════════════════════════════════════════════════════


class CreditAccount(Base):
    """积分账户。§7.3：`(user_id PK, balance, frozen, updated_at)`。

    ─────────────────────────────────────────────────────────
    【这个表里最关键的一条：没有 available 列，而且永远不该有】

    可用余额 = `balance − frozen`，**永远现算**。

    【为什么不存下来】因为一旦存了，就有了两个必须永远同步的真身。
    后端加一个赠送积分的场景忘了更新其中一个，就会出现
    「余额显示 100，可用显示 80」这种对不上的数字，而且**没有任何报错**。
    现算则永远不可能不一致。

    前端 `lib/models/credit_account.dart` 的 `available` 也是现算的
    getter，注释里写的是同一个理由。两边刻意一致。
    ─────────────────────────────────────────────────────────
    """

    __tablename__ = "credit_accounts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    """§7.3 原文就是 `user_id PK` —— 一个用户一个账户，不需要自己的 id。"""

    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """总余额（**含**冻结中）。"""

    frozen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """冻结中：已被进行中的任务预扣、还没结算的那部分。"""

    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="credit_account")

    __table_args__ = (
        # ── 这两条约束是「账不能为负」的数据库级防线 ──────────
        # 【为什么必须有】因为积分就是钱。代码里当然会先检查余额再扣，
        # 但那是一个 check-then-act，而并发下 check 和 act 之间
        # 有窗口（两个请求同时读到「够」，然后都扣）。
        # 约束由数据库在写入的瞬间判定，没有窗口。
        # 真撞上时抛 IntegrityError，比默默记出一笔负余额好得多。
        CheckConstraint("balance >= 0", name="ck_credit_accounts_balance_nonneg"),
        CheckConstraint("frozen >= 0", name="ck_credit_accounts_frozen_nonneg"),
        # 冻结不能超过总额 —— 也就是「可用余额不能为负」。
        # 见 §7.2：freeze 只是把可用搬到冻结，总额不变，所以这条恒成立。
        CheckConstraint(
            "frozen <= balance", name="ck_credit_accounts_frozen_le_balance"
        ),
    )

    @property
    def available(self) -> int:
        """可用余额。**现算**，见类注释。"""
        return self.balance - self.frozen

    def __repr__(self) -> str:
        return (
            f"<CreditAccount user_id={self.user_id} "
            f"balance={self.balance} frozen={self.frozen}>"
        )


# ══════════════════════════════════════════════════════════════
# 4. tasks
# ══════════════════════════════════════════════════════════════


class Task(Base):
    """生成任务（**兼队列**）。§11.2。

    §8.1 说队列是物理必需而不是优雅：一次视频生成要 10 分钟，
    HTTP 请求等不了。v1 的队列就是这张表 + 一个轮询 worker，
    **不引入 Redis/Celery**。
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[TaskKind] = mapped_column(
        EnumStr(TaskKind, length=16), nullable=False
    )

    status: Mapped[TaskStatus] = mapped_column(
        EnumStr(TaskStatus, length=16), nullable=False, default=TaskStatus.pending
    )

    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="jimeng")
    """哪个 provider 做的。写进去是为了**对账** —— fake 和 jimeng 的
    成本完全不同，混在一张表里而分不出来时，成本表就是错的。"""

    req_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """能力标识（即梦文档 §5）。`provider` 内部的细分能力。

    【为什么可空】因为 fake provider 没有这个概念；而真 provider 的
    req_key 是 B0.5 的 Spike 才能确定的（§18-2 待答）。"""

    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """即梦返回的 task_id。用于轮询。"""

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    """提示词。§11.2：≤2000 字，**提交前校验**（`MAX_PROMPT_LEN`）。

    用 Text 而不是 String(2000)：长度上限是**业务规则**（可配置、
    会变），不是存储能力。把业务规则钉在 DDL 上，改上限时就要改表。
    校验放在 schema 层（B2），这里只管装得下。"""

    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    """`ratio` / `duration` / `width` / `height` 等，存成 JSON 字符串。

    ⚠️ 序列化时**要输出成 `params` 对象**，不是这根字符串。
    前端的 `Task._parseParams` 两种都收（`params` 优先），
    但契约上正确的那种是对象 —— 见 §12 的接口示例。
    存 TEXT 是为了 SQLite/PostgreSQL 都能跑，不用 JSONB。"""

    source_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """图生视频的输入图，逻辑上指向 `assets.id`。

    ─────────────────────────────────────────────────────────
    【⚠️ 这一列**没有**外键约束，是有意的，不是漏了】

    `tasks.source_asset_id → assets.id` 和 `assets.task_id → tasks.id`
    构成**循环外键**。SQLAlchemy 对循环外键要求 `use_alter=True`，
    而 `use_alter` 在 SQLite 的 batch 模式下**不受支持** ——
    SQLAlchemy 会把它静默跳过。

    v1 跑 SQLite，所以：要么写一个在 SQLite 上根本不存在的外键
    （写给人看，编译器和数据库都不管），要么老老实实承认这一列
    由应用层保证，并**写下来**。

    选了后者，因为「写了但不生效的外键」比没有更糟：
    它会让下一个读代码的人以为数据库在保护他。

    真正被强制执行的方向是 `assets.task_id`（每份产物必须属于一个真任务），
    那个方向的外键是有的。而 `source_asset_id` 的有效性由
    B4 的上传流程保证（asset 是我们自己创建的，用户没法凭空指定 id）。
    ─────────────────────────────────────────────────────────
    """

    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """客户端生成的 UUID，防连点双扣（§7.5 的第二道闸）。

    【配 `UNIQUE(user_id, idempotency_key)`，注意作用域是**用户级**】
    全局唯一的话，两个用户碰巧生成了同一个 key（客户端实现有 bug 时
    完全可能）就会互相顶掉对方的任务。用户级唯一才是对的语义：
    「同一个用户的同一次点击只算一次」。

    【为什么可空】可空意味着「这次提交没有幂等保护」，是可以的；
    而且 SQL 里 NULL 在唯一索引中互不相等，所以多条 NULL 不会冲突 ——
    这个特性正好是我们想要的。
    """

    freeze_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """下单时冻结的积分数。§7.2：`(输入时长 + 请求时长 + 余量) × 每秒单价`。"""

    settled_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """实际结算额。**未结算时为 NULL，不是 0** —— 见文件头第 3 条。"""

    input_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """输入视频时长。即梦回参 `InputVideoDurationSum`。"""

    output_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """**成片实际时长**。即梦回参 `Duration`。

    【为什么和 `params_json.duration` 分开放】用户下单时选的是
    「期望 5 秒」，provider 侧的 Agent 可能给 6 秒。**计费按实际成片算**，
    所以才会有「多余自动退回」这回事。两个数字混在一起时，
    对账会算出错误的金额。"""

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """失败原因码。可能是即梦的原始码（`50411`），也可能是我们自己的
    （`TRANSFER_FAILED`）。

    【为什么要一路透传到日志】没有它，线上一个「生成失败」就完全无法归因。"""

    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    """失败原因（**面向开发**，不该直接上屏）。"""

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── 转存（§9.2）─────────────────────────────────────────
    provider_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    """即梦的产物地址，**只活 1 小时**，仅作转存的瞬时中转。

    ⚠️⚠️ **绝不返回给 App。** 前端的 `Task` 模型里刻意没有这个字段，
    并且有守卫测试盯着。它是「什么时候转存」用的中间变量，不是资产真身。
    """

    transfer_state: Mapped[TransferState] = mapped_column(
        EnumStr(TransferState, length=16), nullable=False, default=TransferState.none
    )
    """**内部状态，绝不作为公开状态暴露** —— 见 `app/enums.py` 的
    `TransferState` 里那段长说明。重试期间公开状态仍是 `submitted`。"""

    transfer_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── 时间线 ─────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )
    queued_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    assets: Mapped[list[Asset]] = relationship(
        back_populates="task", foreign_keys="Asset.task_id"
    )

    __table_args__ = (
        # ── 幂等键：同一次点击只算一次 ────────────────────────
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_tasks_user_idempotency_key"
        ),
        _enum_check("kind", TaskKind),
        _enum_check("status", TaskStatus),
        _enum_check("transfer_state", TransferState),
        CheckConstraint("freeze_amount >= 0", name="ck_tasks_freeze_nonneg"),
        CheckConstraint(
            "settled_amount IS NULL OR settled_amount >= 0",
            name="ck_tasks_settled_nonneg",
        ),
        CheckConstraint("retry_count >= 0", name="ck_tasks_retry_count_nonneg"),
        CheckConstraint(
            "transfer_attempts >= 0", name="ck_tasks_transfer_attempts_nonneg"
        ),
        CheckConstraint(
            "input_duration_sec IS NULL OR input_duration_sec >= 0",
            name="ck_tasks_input_duration_nonneg",
        ),
        CheckConstraint(
            "output_duration_sec IS NULL OR output_duration_sec >= 0",
            name="ck_tasks_output_duration_nonneg",
        ),
        # ── 一条真正重要的业务不变量 ──────────────────────────
        # 【为什么「成功」必须意味着「已结算」】因为 succeeded 是
        # 唯一一个用户**拿到了东西**的终态。如果它可以是
        # settled_amount IS NULL，那就意味着存在「东西给了、钱没记」
        # 的任务 —— 而对账时这种任务查不出来（NULL 不参与求和），
        # 表现为平台悄悄少收钱，或者冻结永远不释放。
        CheckConstraint(
            "status != 'succeeded' OR settled_amount IS NOT NULL",
            name="ck_tasks_succeeded_implies_settled",
        ),
        # ── 查询用的索引 ──────────────────────────────────────
        # 「我的进行中任务」是最热的查询（§8.4：App 要轮询）。
        Index("ix_tasks_user_status", "user_id", "status"),
        # 作品页/任务列表按时间倒序。
        Index("ix_tasks_user_created", "user_id", "created_at"),
        # worker 扫「该提交的」和「该轮询的」。
        Index("ix_tasks_status_queued_at", "status", "queued_at"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def __repr__(self) -> str:
        return f"<Task id={self.id} kind={self.kind.value} status={self.status.value}>"


# ══════════════════════════════════════════════════════════════
# 5. assets
# ══════════════════════════════════════════════════════════════


class Asset(Base):
    """产物资产（图/视频/缩略图）与用户上传的参考图。§11.2。"""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    """由哪个任务生成。**用户上传的参考图没有它**（§11.2）。

    `ondelete="SET NULL"`：删任务不该删掉用户已经拿到手的作品。
    """

    kind: Mapped[AssetKind] = mapped_column(
        EnumStr(AssetKind, length=16), nullable=False
    )

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    """对象存储里的路径（**不是 URL**）。

    【为什么要单独存路径】因为 URL 会变（换 CDN、换域名、加签名），
    而路径是「这个文件在我们的存储里叫什么」这个事实。
    两者混成一个字段的话，换域名要改全表的数据，
    而且是**改数据**不是改配置 —— 这类操作最容易做错。"""

    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    """**永久**可访问的地址。前端 `Asset.publicUrl` 读它。

    ⚠️ 上游（即梦）的 URL 只活 1 小时。转存到我们自己的存储后
    才有这个字段的值 —— 见 §9.2 的转存流水线。"""

    mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """视频时长（秒）。图片为 NULL。"""

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """宽高。前端作品网格靠它按真实比例排版（不裁成正方形）。"""

    is_ai_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    """§10.1 的法律义务字段。

    【为什么默认 true，以及为什么**不加** CHECK 强制它为 true】
    默认 true 是安全的：漏了字段时宁可多打「AI 生成」标，不能少打。
    但不加 CHECK 是因为 §11.2 自己说了「将来可能有用户上传的原图混进
    资产列表，那些**不该**打 AI 标」—— 那时这一列要能写 false。
    现在钉死为 true 的话，那天就要改约束。
    """

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    task: Mapped[Task | None] = relationship(
        back_populates="assets", foreign_keys="Asset.task_id"
    )

    __table_args__ = (
        _enum_check("kind", AssetKind),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_assets_size_nonneg"),
        CheckConstraint(
            "duration_sec IS NULL OR duration_sec >= 0", name="ck_assets_duration_nonneg"
        ),
        CheckConstraint("width IS NULL OR width > 0", name="ck_assets_width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="ck_assets_height_positive"),
        # 作品列表：按用户查、按时间倒序。
        Index("ix_assets_user_created", "user_id", "created_at"),
        # 一个任务的所有产物（正片 + 缩略图）。
        Index("ix_assets_task", "task_id"),
    )

    def __repr__(self) -> str:
        return f"<Asset id={self.id} kind={self.kind.value} url={self.public_url!r}>"


# ══════════════════════════════════════════════════════════════
# 6. credit_ledger
# ══════════════════════════════════════════════════════════════


class CreditLedger(Base):
    """积分流水。§7.3。

    **每一笔都要写流水**（含结算与退回），`balance_after` 落库便于对账。
    """

    __tablename__ = "credit_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[LedgerKind] = mapped_column(
        EnumStr(LedgerKind, length=16), nullable=False
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    """**恒为正数**，表示「这一笔涉及多少积分」。

    【为什么是正的，方向靠 kind 推导 —— 这是本项目拍板的契约】
    §7.3 只写了有一列 `amount`，没定义正负。而单靠一个 amount
    也表达不了 freeze 这种「余额不变、冻结增加」的情况：
    它到底该记 +32 还是 −32？两种都能自圆其说，所以必须**拍板一个**，
    否则前端显示流水时只能靠猜。

    拍板：恒正。真正的权威快照是 `balance_after` / `frozen_after`，
    界面显示余额时信它们，不要自己拿 amount 去累加。

    前端 `lib/models/credit_ledger_entry.dart` 里写着同一条约定
    （它甚至有 `reducesAvailable` 这个 getter 来推导方向）。
    两边的注释互相指向，改一边就要改另一边。
    """

    adjustment_debit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    """这一笔之后的**总余额**。权威快照。"""

    frozen_after: Mapped[int] = mapped_column(Integer, nullable=False)
    """这一笔之后的**冻结额**。权威快照。"""

    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    """关联的任务。赠送/调整类流水没有它。

    【为什么流水要能点进任务详情】用户在流水页看到「结算 −24」时，
    下一个问题必然是「哪个视频扣的」。有这个 id 才能跳过去看成品。"""

    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """给用户看的备注（如「新用户注册赠送」）。"""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        _enum_check("kind", LedgerKind),
        # 恒正 —— 见 amount 的说明。零额的流水**不写**（写一行「退了 0 积分」
        # 只会让流水页变长且让人困惑）。
        CheckConstraint("amount > 0", name="ck_credit_ledger_amount_positive"),
        # 快照不能为负：账本一旦出现负数余额，说明记账路径有 bug，
        # 这时宁可写入失败，也不要留下一笔解释不清的记录。
        CheckConstraint("balance_after >= 0", name="ck_credit_ledger_balance_nonneg"),
        CheckConstraint("frozen_after >= 0", name="ck_credit_ledger_frozen_nonneg"),
        # 流水页：某个用户的最新在前。
        # 【为什么要 DESC 进索引】因为流水的量会一直涨，而
        # 「某用户最新的 20 条」是最热的查询。升序索引要扫完再倒排。
        Index("ix_credit_ledger_user_id_desc", "user_id", "id"),
        Index("ix_credit_ledger_task", "task_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CreditLedger id={self.id} user_id={self.user_id} "
            f"kind={self.kind.value} amount={self.amount}>"
        )


# ══════════════════════════════════════════════════════════════
# 7. provider_calls
# ══════════════════════════════════════════════════════════════


class ChainWallet(Base):
    """影子链钱包（方案 B：链下积分 1:1 映射到链上 VCR）。

    ⚠️ **演示专用：私钥存在平台数据库里（`private_key`）**。
    生产环境必须换成用户自持钱包或 KMS 托管，并把这一列删掉。
    """

    __tablename__ = "chain_wallets"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    address: Mapped[str] = mapped_column(String(42), nullable=False, unique=True)
    private_key: Mapped[str] = mapped_column(String(66), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class ChainOp(Base):
    """一条待执行的链上影子操作（mint / consume），由 worker 逐条上链。

    `ref` 是幂等键（同一笔账本流水只上链一次），`video_id_hash` 用于把
    consume 绑定到具体任务，方便用户在链上按任务核对。
    """

    __tablename__ = "chain_ops"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    ref: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    video_id_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    signed_tx: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployment_id: Mapped[str | None] = mapped_column(String(66), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_chain_ops_amount_positive"),
        CheckConstraint("attempts >= 0", name="ck_chain_ops_attempts_nonneg"),
        Index("ix_chain_ops_status_id", "status", "id"),
        Index("ix_chain_ops_user_created", "user_id", "created_at"),
    )


class ChainState(Base):
    """链上部署状态的键值表（目前只存合约地址）。"""

    __tablename__ = "chain_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )


class EvidenceRecord(Base):
    """待提交的成片登记以及 Fabric 确认回执。作品删除后保留审计记录。"""

    __tablename__ = "evidence_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    network_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    chaincode: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    tx_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_evidence_records_status_due", "status", "next_attempt_at"),)


class WorkPublication(Base):
    """Fields the original author has chosen to share by evidence number."""

    __tablename__ = "work_publications"

    evidence_record_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="CASCADE"), primary_key=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    author_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)


class WorkHolding(Base):
    __tablename__ = "work_holdings"

    evidence_record_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_records.id"), primary_key=True
    )
    holder_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkListing(Base):
    __tablename__ = "work_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_record_id: Mapped[int] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    buyer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("price > 0", name="ck_work_listings_positive_price"),
        Index("ix_work_listings_status_id", "status", "id"),
        Index(
            "uq_work_listings_active", "evidence_record_id", unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )


class WorkTrade(Base):
    """A completed payment with a durable Fabric submission task."""

    __tablename__ = "work_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("work_listings.id"), nullable=False, unique=True)
    evidence_record_id: Mapped[int] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    tx_id: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_until: Mapped[datetime | None] = mapped_column(UtcDateTime())
    next_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("evidence_record_id", "sequence", name="uq_work_trades_sequence"),
        Index("ix_work_trades_status_due", "status", "next_attempt_at"),
    )


class ProviderCall(Base):
    """对 provider 的每一次调用。§11.1：用于**成本对账**与调试。

    ─────────────────────────────────────────────────────────
    【这张表的字段文档里没给，是这里设计的 —— 但有一条铁律】

    §11.1 只说了这张表存在、用途是「调试/计量」，没列字段。
    这里按「对账要回答什么问题」来定字段。

    ⚠️⚠️ **绝不存 AK/SK、绝不存请求头。**

    这张表是最容易漏密钥的地方，因为它的用途就是「把一次调用原样记下来
    好排查」。而即梦的签名方案（Signature V4）是把 AK 放在 **HTTP 头**
    里的 —— 记录请求头的诱惑非常大，而一旦记了，密钥就进了数据库，
    再跟着备份、导出、截图一路扩散出去。

    所以这里只记**响应侧**的摘要：状态码、code、消息、耗时。
    排查时够用（即梦的 `50411` / `50429` 这些码就在响应里），
    而永不会把密钥写进表。
    ─────────────────────────────────────────────────────────
    """

    __tablename__ = "provider_calls"

    id: Mapped[int] = mapped_column(primary_key=True)

    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    """哪次任务。**可空**，因为有些调用发生在任务落库之前
    （比如 B0.5 的 Spike 直接就打了接口，没有 task 行）。"""

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """这是第几次尝试。§7.5 的重试纪律靠它审计：如果某类错误
    的重试次数总是打满 3 次，说明退避策略或错误分类有问题。"""

    action: Mapped[str] = mapped_column(String(32), nullable=False)
    """`submit` / `query` / `upload` 等。**故意是自由字符串而不是枚举** ——
    它是排查用的日志标签，加一个新的动作不该要求写一次迁移。"""

    req_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """HTTP 状态码。可空：连不上时的异常路径没有状态码。"""

    resp_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """provider 业务码。即梦的审计码（`50411` / `50413` / `50514` /
    `50429` / `50500`）落在这里 —— 它决定了任务该判 `rejected`
    还是该重试（§12.2 的错误映射表，B6 实现）。"""

    resp_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """耗时。这个是**成本与体验的原始数据**：即梦慢的时候，
    用户看到的「生成中」也就慢，而我们只能靠这个判断是不是它的问题。"""

    error_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """网络层异常的分类（`timeout` / `connect` / `decode` …）。
    与 `resp_code` 互斥：一个是「连不上」，一个是「连上了它说不」。
    两张情况的重试策略不同，所以要分开记。"""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_provider_calls_attempt_positive"),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_provider_calls_latency_nonneg",
        ),
        Index("ix_provider_calls_task", "task_id", "created_at"),
        Index("ix_provider_calls_provider_task", "provider_task_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProviderCall id={self.id} action={self.action!r} "
            f"http={self.http_status} code={self.resp_code!r}>"
        )


__all__ = [
    "Asset",
    "ChainOp",
    "ChainState",
    "ChainWallet",
    "CreditAccount",
    "CreditLedger",
    "InviteCode",
    "ProviderCall",
    "Task",
    "User",
]
