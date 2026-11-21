"""B1：7 张表 + 约束。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这一组测试的重点不是「表建出来了」，而是「约束真的会拦」】

建表成功是一个很弱的断言 —— 一个把 CHECK 全写错、外键全漏掉的
schema 也能建表成功。真正要验的是：**当数据违反业务规则时，
数据库会不会当场报错**。

所以下面的负向用例都是「故意写一条坏数据，确认它抛 IntegrityError」。
这类测试有个共同的失效模式：**因为错的理由通过**（比如抛了异常，
但抛的是「表不存在」而不是「约束拦住了」）。所以每条都要断言
异常本身，而不是只断言 `pytest.raises(Exception)`。

另外这里还有一条**跨仓库**的断言：8 个任务状态必须与冻结的前端
逐字一致。前端认不出状态会抛异常（它拒绝静默退化），所以
后端多一个或少一个都会让用户看到崩溃而不是「生成失败」。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import TaskStatus
from app.models import Asset, CreditAccount, CreditLedger, InviteCode, Task, User
from app.types import utcnow

# ── 建表 ──────────────────────────────────────────────────────


def test_业务表一张不少(db: Engine) -> None:
    """原有业务表、链上存证和作品交易表。"""
    from sqlalchemy import inspect

    names = set(inspect(db).get_table_names())

    expected = {
        "users",
        "invite_codes",
        "credit_accounts",
        "credit_ledger",
        "tasks",
        "assets",
        "provider_calls",
        "chain_wallets",
        "chain_ops",
        "chain_state",
        "evidence_records",
        "work_publications",
        "work_holdings",
        "work_listings",
        "work_trades",
    }
    assert names == expected, f"多了或少了：{names ^ expected}"


def test_alembic_会看到全部业务表() -> None:
    """⚠️ 守卫：`Base.metadata` 必须是**完整**的那一份。

    【为什么这条非有不可】`app/database.py` 的 `Base` 是空的，
    表是在 `app/models.py` 里被 import 时才注册进去的。
    Alembic 的 `env.py` 靠 `try: import app.models` 来触发这个副作用
    —— 而那句 import 被 try 包着（B1 之前 models.py 不存在）。

    如果哪天这个 import 失效了，`--autogenerate` 会生成一个**空迁移**：
    命令成功、退出码 0、文件里只有空的 upgrade/downgrade。
    然后你以为迁移写好了，建库时才发现表根本没建。
    """
    import app.models  # noqa: F401

    from app.database import Base

    assert len(Base.metadata.tables) == 15, sorted(Base.metadata.tables)


# ── 跨仓库：状态枚举与前端逐字一致 ─────────────────────────────


def test_八个任务状态与前端逐字一致() -> None:
    """⚠️ 契约守卫：这 8 个字符串是**冻结前端**认得的全部。

    ─────────────────────────────────────────────────────────
    来源：`flutter_application_1/lib/core/constants/task_status.dart`
    的 `TaskStatus`。它的 `fromWire` 认不出来会**抛 FormatException** ——
    也就是说，后端多加一个状态，用户看到的是**崩溃/白屏**，
    而不是「生成失败，积分已退」。

    所以这 8 个值是从那个 Dart 文件**抄过来**再对一遍，不是从
    §11.3 抄的（虽然两者一致）。改这里就必须同时改那个 Dart 文件，
    改不动它就是「后端单方面改了契约」——那时前端整个上线不了。
    ─────────────────────────────────────────────────────────
    """
    frontend_wire_values = {
        "pending",  # 待提交
        "queued",  # 排队中
        "submitted",  # 生成中
        "succeeded",  # 已完成
        "failed",  # 生成失败
        "rejected",  # 未通过审核
        "canceled",  # 已取消
        "expired",  # 已过期
    }
    assert {s.value for s in TaskStatus} == frontend_wire_values, (
        "任务状态与前端不一致。改一边就要改另一边，"
        "见 lib/core/constants/task_status.dart"
    )


def test_终态清单与前端一致() -> None:
    """前端认为终态的那 5 个，后端也必须认为它们是终态。

    【为什么这个判断错不得】它同时决定两件事：
    前端要不要继续轮询，后端要不要退积分。
    两边不一致就会出现「App 停止轮询了，但后端还没结算」，
    或者「后端已结算，App 还在转」。
    """
    frontend_terminal = {"succeeded", "failed", "rejected", "canceled", "expired"}
    backend_terminal = {s.value for s in TaskStatus if s.is_terminal}

    assert backend_terminal == frontend_terminal, (
        f"终态不一致：{backend_terminal ^ frontend_terminal}"
    )
    assert {s.value for s in TaskStatus if s.is_active} == {
        "pending",
        "queued",
        "submitted",
    }


# ── 夹具 ──────────────────────────────────────────────────────


def _user(session: Session, username: str = "alice") -> User:
    u = User(
        username=username,
        username_canonical=username.casefold(),
        password_hash="$2b$12$notarealhash",
    )
    session.add(u)
    session.flush()
    return u


def _task(session: Session, user: User, **kw: object) -> Task:
    from app.enums import TaskKind

    fields: dict[str, object] = {
        "kind": TaskKind.text_to_image,
        "status": TaskStatus.pending,
        "prompt": "一只在月球上钓鱼的猫",
    }
    fields.update(kw)
    t = Task(user_id=user.id, **fields)  # type: ignore[arg-type]
    session.add(t)
    session.flush()
    return t


# ── 幂等键 ────────────────────────────────────────────────────


def test_同一个用户的同一个幂等键只能建一个任务(session: Session) -> None:
    """⚠️ §7.5 第二道闸：防连点双扣。

    用户连点两次「生成」，客户端发的是同一个 `idempotency_key`。
    后端必须只建一个任务 —— 否则会**扣两次钱**。
    """
    u = _user(session)
    _task(session, u, idempotency_key="click-1")

    with pytest.raises(IntegrityError) as exc:
        _task(session, u, idempotency_key="click-1")

    # ⚠️ 这里断言的是**列名**，不是约束名 `uq_tasks_user_idempotency_key`。
    #
    # 【为什么不写约束名】实测发现 SQLite 对这两类约束的报错口径不一样：
    #
    #   命名 CHECK  → "CHECK constraint failed: ck_status_is_known"   有名字
    #   UNIQUE      → "UNIQUE constraint failed: tasks.user_id, ..."  只有列名
    #
    # 也就是说唯一约束**报不出名字**。硬写约束名会让这条断言在 SQLite 上
    # 永远红；而放宽成 `pytest.raises(IntegrityError)` 又会让它
    # 「因为错的理由通过」—— 比如某天 user_id 的外键出错也能满足它。
    #
    # 所以断言列名：它既排除了别的失败原因，又在两个数据库上都成立。
    assert "tasks.user_id, tasks.idempotency_key" in str(exc.value), (
        f"拦住是拦住了，但原因不是幂等键唯一约束：{exc.value}"
    )


def test_不同用户可以用同一个幂等键(session: Session) -> None:
    """⚠️ 唯一约束的作用域必须是**用户级**，不是全局。

    【为什么】客户端生成的 UUID 理论上不撞，但客户端实现有 bug
    （比如用时间戳当 key、或者写了固定值）时完全可能撞。
    全局唯一的话，用户 B 的提交会被用户 A 的任务顶掉 ——
    B 会拿到 A 的任务，看到别人的作品。这比重复扣钱严重得多。
    """
    a = _user(session, "alice")
    b = _user(session, "bob")

    _task(session, a, idempotency_key="same-key")
    _task(session, b, idempotency_key="same-key")  # 不该抛

    assert len(session.scalars(select(Task)).all()) == 2


def test_多条空幂等键互不冲突(session: Session) -> None:
    """⚠️ SQL 里 NULL 在唯一索引中互不相等 —— 这个特性正是我们要的。

    【为什么这条值得单独测】因为有人会「顺手加固」，把这一列改成
    NOT NULL，或者用空串代替 NULL。那样一来，**没有幂等键的任务
    就只能存在一个** —— 而服务端自己创建的任务（worker 重试、
    系统补单）恰恰没有幂等键。这类改动看起来更严格，
    实际是把一条合法路径堵死了。
    """
    u = _user(session)
    _task(session, u, idempotency_key=None)
    _task(session, u, idempotency_key=None)
    _task(session, u, idempotency_key=None)

    assert len(session.scalars(select(Task)).all()) == 3


# ── 账不能为负 ────────────────────────────────────────────────


def test_余额不能为负(session: Session) -> None:
    """积分就是钱。这条在数据库层面挡，因为应用层的 check-then-act 有并发窗口。"""
    u = _user(session)
    session.add(CreditAccount(user_id=u.id, balance=-1, frozen=0))

    with pytest.raises(IntegrityError) as exc:
        session.flush()
    assert "ck_credit_accounts_balance_nonneg" in str(exc.value)


def test_冻结不能超过总余额(session: Session) -> None:
    """⚠️ 这条等价于「可用余额不能为负」。

    绕过它 = 用户可以拿着没有的钱下单。
    """
    u = _user(session)
    session.add(CreditAccount(user_id=u.id, balance=10, frozen=11))

    with pytest.raises(IntegrityError) as exc:
        session.flush()
    assert "ck_credit_accounts_frozen_le_balance" in str(exc.value)


def test_可用余额是现算的(session: Session) -> None:
    """`available = balance − frozen`，且**表里没有这一列**。

    表里存下它就有了两个必须同步的真身 —— 前端
    `lib/models/credit_account.dart` 的注释解释了为什么不做。
    """
    u = _user(session)
    account = CreditAccount(user_id=u.id, balance=50, frozen=32)
    session.add(account)
    session.flush()

    assert account.available == 18
    columns = {c.name for c in CreditAccount.__table__.columns}
    assert "available" not in columns, "available 被存成列了 —— 它必须现算"


# ── 「成功必须已结算」这条业务不变量 ──────────────────────────


def test_任务标成功却没有结算额要被拦下(session: Session) -> None:
    """⚠️ 这是本项目最要紧的一条不变量。

    `succeeded` 是**唯一一个用户真的拿到了东西**的终态。
    如果它可以没有 `settled_amount`，就意味着存在「东西给了、
    钱没记」的任务 —— 对账时这种任务查不出来（NULL 不参与求和），
    表现为平台悄悄少收钱，或者冻结永远不释放。
    """
    u = _user(session)

    with pytest.raises(IntegrityError) as exc:
        _task(session, u, status=TaskStatus.succeeded, settled_amount=None)
    assert "ck_tasks_succeeded_implies_settled" in str(exc.value)


def test_失败的终态允许没有结算额(session: Session) -> None:
    """反过来也要成立：**不能**要求所有终态都有结算额。

    【为什么这条同样重要】§7.4：provider 报错、审核未通过、
    排队中取消都是**全额退回**，那些任务确实没有「实扣多少」这个数。
    如果约束写成「终态必须有 settled_amount」，这些路径全都写不进库 ——
    而它们是最常见的失败路径。
    """
    u = _user(session)
    for status in (
        TaskStatus.failed,
        TaskStatus.rejected,
        TaskStatus.canceled,
        TaskStatus.expired,
    ):
        t = _task(session, u, status=status, settled_amount=None)
        assert t.settled_amount is None


def test_成功的任务必须有结算额(session: Session) -> None:
    """正向：给了结算额就写得进去。"""
    u = _user(session)
    t = _task(session, u, status=TaskStatus.succeeded, settled_amount=24)
    assert t.settled_amount == 24


# ── 枚举写入 ──────────────────────────────────────────────────


def test_状态存的是字符串不是枚举名(session: Session) -> None:
    """⚠️ 写进库的必须是 `wire` 值，不是 Python 的成员名。

    【为什么这条要测】如果哪天有人把 `EnumStr` 换成直接存枚举对象，
    SQLite 会存下 `TaskStatus.pending` 这个表示 —— 而前端认的是
    `"pending"`。这种错在开发期完全看不出来（ORM 读回来时可能
    还能还原），只有直连数据库看数据、或者换语言读时才暴露。
    """
    u = _user(session)
    _task(session, u, status=TaskStatus.queued)

    raw = session.execute(text("SELECT status FROM tasks")).scalar_one()
    assert raw == "queued", f"库里存的是 {raw!r}，应当是 'queued'"


def test_库里写不进野状态(session: Session) -> None:
    """CHECK 约束要真的挡得住手写的字符串。

    【为什么这条要**绕开 ORM** 直接写 SQL】因为 ORM 那条路会经过
    `EnumStr` 的校验，本来就抛。真正要验的是「有人直连数据库
    跑一句 UPDATE」时数据库自己挡不挡得住 —— 那是 CHECK 存在的全部意义。
    """
    u = _user(session)
    _task(session, u, status=TaskStatus.pending)
    session.commit()

    with pytest.raises(IntegrityError) as exc:
        session.execute(text("UPDATE tasks SET status='cancelled'"))
        session.flush()
    assert "ck_status_is_known" in str(exc.value), (
        f"野状态被写进去了，或者拦住的原因不对：{exc.value}"
    )


def test_枚举读写往返(session: Session) -> None:
    """写进去的是枚举，读出来的也是枚举（不是裸字符串）。"""
    u = _user(session)
    _task(session, u, status=TaskStatus.submitted)
    session.commit()
    session.expire_all()

    t = session.scalars(select(Task)).one()
    assert t.status is TaskStatus.submitted, t.status


# ── 时间：那个会偏差 8 小时的坑 ───────────────────────────────


def test_读出来的时间带_UTC_时区(session: Session) -> None:
    """⚠️ 守卫：时间列读出来必须带 tzinfo。

    ─────────────────────────────────────────────────────────
    【这条挡的是一个静默偏差 8 小时、而且前后端测试全绿的 bug】

    SQLite 没有时间类型，它把 DATETIME 存成字符串且**不存时区**。
    如果读出来是 naive datetime，序列化就是
    `"2026-10-12T08:30:00"`（没有 Z、没有 +00:00），
    而 Dart 的 `DateTime.tryParse` 会把这种串**按本地时间**理解，
    再 `.toUtc()` 减掉 8 小时 —— 用户看到的时间比实际早 8 小时。

    两边各自的代码都没写错，错的是中间那根字符串少了个时区标记。
    所以这条断言必须钉在这里：**读出来的时间对象本身就得带时区**。
    ─────────────────────────────────────────────────────────
    """
    u = _user(session)
    t = _task(session, u)
    session.commit()
    session.expire_all()

    fresh = session.scalars(select(Task)).one()
    assert fresh.created_at.tzinfo is not None, (
        "created_at 读出来是 naive 的 —— 序列化后前端会按本地时间解析，差 8 小时"
    )
    assert fresh.created_at.utcoffset() == timedelta(0), fresh.created_at


def test_写进去的本地时间会被归一到_UTC(session: Session) -> None:
    """东八区的 16:30 和 UTC 的 08:30 是同一时刻，存下来必须是 UTC 的 08:30。"""
    u = _user(session)
    beijing = datetime(2026, 10, 12, 16, 30, tzinfo=timezone(timedelta(hours=8)))

    _task(session, u, queued_at=beijing)
    session.commit()
    session.expire_all()

    fresh = session.scalars(select(Task)).one()
    assert fresh.queued_at is not None
    assert fresh.queued_at == datetime(2026, 10, 12, 8, 30, tzinfo=UTC)
    assert fresh.queued_at.hour == 8, f"没有归一，读出来是 {fresh.queued_at}"


def test_utcnow_返回带时区的时间() -> None:
    """`datetime.utcnow()` 已被废弃，正是因为「naive 但其实是 UTC」骗了太多人。"""
    now = utcnow()
    assert now.tzinfo is UTC
    assert now.utcoffset() == timedelta(0)


def timezone_east8() -> object:  # noqa: D103 - 已由上面的用例说明
    from datetime import timezone

    return timezone(timedelta(hours=8))


# ── 合规字段 ──────────────────────────────────────────────────


def test_资产默认带_AI_生成标识(session: Session) -> None:
    """§10.1：法律义务。默认值给 true 是**安全的默认** ——
    漏了字段时宁可多打标，不能少打。"""
    u = _user(session)
    t = _task(session, u)
    session.commit()

    a = Asset(
        user_id=u.id,
        task_id=t.id,
        kind=__import__("app.enums", fromlist=["AssetKind"]).AssetKind.image,
        storage_key="u/1/a.png",
        public_url="https://cdn.example.com/u/1/a.png",
    )
    session.add(a)
    session.flush()

    assert a.is_ai_generated is True


def test_is_ai_generated_必须是真布尔(session: Session) -> None:
    """前端的 `boolOr` 对 `'true'`（字符串）和 `1`（数字）**都抛异常**。

    【为什么这里要跟着严格】这一列是合规字段，静默变成 false
    意味着「AI 生成」标识不显示。前端宁可抛异常也不接受
    「像布尔的东西」，后端存储也不能给它机会退化成别的东西。
    """
    u = _user(session)
    t = _task(session, u)
    session.commit()

    from app.enums import AssetKind

    a = Asset(
        user_id=u.id,
        task_id=t.id,
        kind=AssetKind.image,
        storage_key="u/1/a.png",
        public_url="https://cdn.example.com/a.png",
        is_ai_generated=True,
    )
    session.add(a)
    session.commit()
    session.expire_all()

    fresh = session.scalars(select(Asset)).one()
    assert fresh.is_ai_generated is True, (
        f"读回来是 {fresh.is_ai_generated!r}（{type(fresh.is_ai_generated).__name__}），"
        "不是真布尔"
    )


# ── 流水 ──────────────────────────────────────────────────────


def test_流水金额必须为正(session: Session) -> None:
    """§7.3 的拍板：`amount` 恒正，方向靠 kind 推导。

    【为什么要拦住 0 和负数】0 额的流水（「退了 0 积分」）只会让
    流水页变长且让人困惑；负数则会让「恒正」这条契约出现两种写法，
    而前端是按恒正解析的。
    """
    from app.enums import LedgerKind

    u = _user(session)
    session.add(CreditAccount(user_id=u.id, balance=50, frozen=0))
    session.flush()

    for bad in (0, -1):
        session.add(
            CreditLedger(
                user_id=u.id,
                kind=LedgerKind.grant,
                amount=bad,
                balance_after=50,
                frozen_after=0,
            )
        )
        with pytest.raises(IntegrityError) as exc:
            session.flush()
        assert "ck_credit_ledger_amount_positive" in str(exc.value)
        session.rollback()
        u = _user(session, f"u{bad}")


def test_邀请码的三种约束(session: Session) -> None:
    """邀请码是**花钱的闸门**，它的约束不是装饰。

    · 用超了要拦（否则邀请制的控量失效 → 花销失控）
    · 次数上限不能是 0 或负（一个永远不能用/无限用的码都是 bug）
    """
    session.add(InviteCode(code="X" * 8, used_count=3, max_uses=2))
    with pytest.raises(IntegrityError) as exc:
        session.flush()
    assert "ck_invite_codes_not_overused" in str(exc.value)
    session.rollback()

    session.add(InviteCode(code="Y" * 8, used_count=0, max_uses=0))
    with pytest.raises(IntegrityError) as exc:
        session.flush()
    assert "ck_invite_codes_max_uses_positive" in str(exc.value)


def test_邀请码不限次用_NULL_表示(session: Session) -> None:
    """`max_uses IS NULL` = 不限次。这条约束不能在 NULL 上误伤。"""
    session.add(InviteCode(code="Z" * 8, used_count=999, max_uses=None))
    session.flush()  # 不该抛
