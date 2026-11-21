"""记账 —— §7.3 的**唯一落点**。

积分就是钱。这个文件里的每一个函数都同时做两件事，而且**不允许分开**：

  1. 改 `credit_accounts` 的 `balance` / `frozen`；
  2. 写一条 `credit_ledger`，带上 `balance_after` / `frozen_after` 快照。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么快照必须落库，而不是靠 amount 累加还原】

用户来问「我这 5 积分去哪了」的时候，只有 `balance_after` 能证明
**每一步之后**账户到底是什么状态。靠 amount 累加去还原是不可靠的：
只要有一笔金额记错方向，整条链就全错，而且错得毫无痕迹。

【为什么 amount 恒为正、方向靠 kind 推导】

单靠一个 amount 表达不了 freeze 这种「余额不变、冻结增加」的情况 ——
它该记 +32 还是 −32？两种都能自圆其说。本项目拍板：**恒正**。
前端 `CreditLedgerKind.reducesAvailable` 写着同一条约定，两边一致。

【为什么 settle 和 refund 必须在同一个事务里】

§7.3 原文要求。拆开就可能出现「扣了钱但没记流水」，或
「任务成功了但冻结没释放」—— 两种都是对不上账的事故。
这里靠「两个 mutate + 两条流水写在一个 `atomic()` 块里」保证，
调用方（`services/generation.py`）负责开那个块。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.enums import ErrorCode, LedgerKind
from app.errors import AppError
from app.models import CreditAccount, CreditLedger
from app.services import chain_credits
from app.types import utcnow

NOTE_MAX_LEN = 200
"""`credit_ledger.note` 是 `String(200)`。截断而不是抛错 ——
备注是给人看的说明，超长该损失的是它的尾部，不是一个失败请求。"""


def _enqueue_chain(
    session: Session,
    *,
    user_id: int,
    kind: str,
    amount: int,
    entry: CreditLedger | None,
) -> None:
    """把这条账本流水登记成一条「链上影子操作」（方案 B）。

    ⚠️ **只写 `chain_ops` 表，不发交易**：真正上链由 worker 做。
    这样请求路径不会被 RPC 阻塞，链上暂时失败也不影响用户下单。
    幂等键用账本流水 id（`ledger:<id>`），重试不会重复上链。
    """
    if entry is None or amount <= 0:
        return
    session.flush()  # 拿 entry.id
    chain_credits.enqueue(
        session,
        user_id=user_id,
        kind=kind,
        amount=amount,
        ref=f"ledger:{entry.id}",
    )


def account_of(session: Session, user_id: int) -> CreditAccount:
    """取积分账户。

    【为什么账户不存在时抛错，而不是顺手建一个】
    因为 `credit_accounts` 的行是**注册流程**建的（见
    `services/accounts.py` 的 `register`）。这里默默补一个的话，
    「注册时忘了建账户」这个 bug 会被永远掩盖 —— 用户能正常下单，
    而账户是「第一次下单时凭空冒出来的」，注册赠送的那笔流水
    就成了孤儿。
    """
    account = session.get(CreditAccount, user_id)
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND, f"用户 {user_id} 没有积分账户")
    return account


def _write_ledger(
    session: Session,
    *,
    account: CreditAccount,
    user_id: int,
    kind: LedgerKind,
    amount: int,
    task_id: int | None,
    note: str | None,
    adjustment_debit: bool = False,
) -> CreditLedger | None:
    """写一条流水。`amount <= 0` 时**不写**。

    【为什么零额的流水不写】表约束就是这么定的
    （`ck_credit_ledger_amount_positive`），而且从产品上说也对：
    写一行「退回 0 积分」只会让流水页变长且让人困惑。
    所以这里静默跳过，由调用方决定要不要显示什么。
    """
    if amount <= 0:
        return None
    entry = CreditLedger(
        user_id=user_id,
        kind=kind,
        amount=amount,
        adjustment_debit=adjustment_debit,
        balance_after=account.balance,
        frozen_after=account.frozen,
        task_id=task_id,
        note=note[:NOTE_MAX_LEN] if note else None,
    )
    session.add(entry)
    return entry


def _touch(account: CreditAccount) -> None:
    """更新账户的 `updated_at`。

    【为什么要手工写】`onupdate=utcnow` 只在 SQLAlchemy 认为该行**脏**了
    的时候才触发。绝大多数路径下 `balance`/`frozen` 确实变了，但
    退款那一刻如果金额恰好是两张表的差…… 与其去推理哪些路径会漏，
    不如统一显式更新。它同时对前端有意义：积分页显示「更新于」。
    """
    account.updated_at = utcnow()


def grant(session: Session, user_id: int, amount: int, note: str, *, task_id: int | None = None) -> None:
    """赠送。注册时那 50 积分走这里。

    【为什么赠送也写流水】§7.3：每一笔都要写流水。不写的话，用户
    打开积分页会看到「余额 50，流水是空的」，第一反应是「这钱哪来的」。
    """
    account = account_of(session, user_id)
    account.balance += amount
    _touch(account)
    entry = _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.grant,
        amount=amount,
        task_id=task_id,
        note=note,
    )
    _enqueue_chain(session, user_id=user_id, kind="mint", amount=amount, entry=entry)


def adjust(session: Session, user_id: int, amount: int, note: str) -> None:
    """人工调整（客服补积分、§15.1 的管理员脚本）。

    【和 `grant` 的唯一区别就是 kind】这不是重复代码 —— 它们的语义
    不同：`grant` 是「注册赠送」这一个业务动作，`adjust` 是
    「人手工改了一笔」。流水页要分得清这两者，否则对账时
    「赠送」那一栏会把运营补贴也算进去。
    """
    if amount == 0:
        return
    account_of(session, user_id)
    statement = update(CreditAccount).where(CreditAccount.user_id == user_id)
    if amount < 0:
        statement = statement.where(CreditAccount.balance - CreditAccount.frozen >= -amount)
    account = session.scalar(
        statement.values(balance=CreditAccount.balance + amount, updated_at=utcnow())
        .returning(CreditAccount)
        .execution_options(populate_existing=True)
    )
    if account is None:
        raise AppError(ErrorCode.INSUFFICIENT_CREDITS, "可用积分不足，无法扣减")
    entry = _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.adjust,
        amount=abs(amount),
        task_id=None,
        note=note,
        adjustment_debit=amount < 0,
    )
    # 人工调账：加积分 = mint，扣积分 = consume（amount 恒正，方向看正负）
    _enqueue_chain(
        session,
        user_id=user_id,
        kind="mint" if amount > 0 else "consume",
        amount=abs(amount),
        entry=entry,
    )


def has_enough(account: CreditAccount, amount: int) -> bool:
    """可用余额 = `balance − frozen`，**现算**。

    见 `app/models.py` 的 `CreditAccount` 类注释：这个值永远不存。
    """
    return account.balance - account.frozen >= amount


def freeze(session: Session, user_id: int, amount: int, *, task_id: int, note: str) -> CreditAccount:
    """下单预扣：把钱从「可用」搬到「冻结」。**总余额不变。**

    【为什么这里还要再查一次余额】调用方（`generation.submit`）已经查过了。
    留着它是因为这个函数是**公开的记账原语** —— 将来别的调用点
    （比如 B3 的 worker）不该被要求「记得先自己查一遍」。
    重复检查的代价是一次比较，漏检查的代价是一笔负余额。
    """
    account = account_of(session, user_id)
    if not has_enough(account, amount):
        raise AppError(
            ErrorCode.INSUFFICIENT_CREDITS,
            f"需要冻结 {amount}，可用只有 {account.balance - account.frozen}",
        )
    account.frozen += amount
    _touch(account)
    _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.freeze,
        amount=amount,
        task_id=task_id,
        note=note,
    )
    return account


def settle_and_refund(
    session: Session,
    user_id: int,
    *,
    task_id: int,
    freeze_amount: int,
    settle: int,
    note_settle: str = "按成片时长结算",
    note_refund: str = "退回多冻结的积分",
) -> CreditAccount:
    """成功收尾：结算 + 退回。**这是 §7.2 三段式的后两段。**

    ─────────────────────────────────────────────────────────
    【这三行 mutate 为什么必须是这个顺序、并且挨在一起】

        account.frozen -= freeze_amount     # 冻结全额释放
        account.balance -= settle           # 真正扣走的
        （两张流水在 mutate 之后写，各自快照）

    退回额 `refund = freeze − settle` **不需要单独改账** —— 它体现为
    「`frozen` 少了 freeze，而 `balance` 只少了 settle」，于是
    `available = balance − frozen` 自动多出来 `refund`。
    这正是 §7.2 的设计：冻结只是把可用搬走，结算才是真正花钱。

    验算（§15.1，前端测试里写死的）：余额 46、冻 32 的 5 秒视频
    → `frozen` 归 0、`balance` 46−24=22、可用 22。✓

    【`settle` 为什么可能小于 `freeze`】成片时长由 provider 侧的 Agent
    决定，可能比请求的短 —— 那就按实际收，多的退回去。
    反过来的情况（实际比冻结上限还长）由调用方钳到 `freeze_amount`：
    §7.2 ④ 规定**平台自担差额**，否则余额会被扣成负数。
    ─────────────────────────────────────────────────────────
    """
    account = account_of(session, user_id)
    account.frozen -= freeze_amount
    account.balance -= settle
    _touch(account)
    settle_entry = _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.settle,
        amount=settle,
        task_id=task_id,
        note=note_settle,
    )
    _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.refund,
        amount=freeze_amount - settle,
        task_id=task_id,
        note=note_refund,
    )
    # 影子链：真正被扣掉的那部分 → 链上 consume（退款部分不动链，因为从未上链）
    _enqueue_chain(session, user_id=user_id, kind="consume", amount=settle, entry=settle_entry)
    return account


def refund_frozen_all(
    session: Session, user_id: int, *, task_id: int, freeze_amount: int, note: str
) -> CreditAccount:
    """排队中取消：**全额退回**。余额不变，钱从「冻结」搬回「可用」。

    §7.4 的退费政策：只有还没提交给 provider 的任务取消才全额退 ——
    那时 provider 一分钱都没花。已提交的走 `charge_frozen`。
    """
    account = account_of(session, user_id)
    account.frozen -= freeze_amount
    _touch(account)
    _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.refund,
        amount=freeze_amount,
        task_id=task_id,
        note=note,
    )
    return account


def charge_frozen(
    session: Session, user_id: int, *, task_id: int, freeze_amount: int, note: str
) -> CreditAccount:
    """已提交后取消：照冻结额**实扣**，不退（§7.4）。

    【为什么这条路径写的是 settle 而不是 refund】因为钱真的花出去了 ——
    provider 已经在跑，成本已经产生。记成 refund 会让账本上说
    「我们退了他一笔钱」，而实际上我们收下了。
    """
    account = account_of(session, user_id)
    account.frozen -= freeze_amount
    account.balance -= freeze_amount
    _touch(account)
    entry = _write_ledger(
        session,
        account=account,
        user_id=user_id,
        kind=LedgerKind.settle,
        amount=freeze_amount,
        task_id=task_id,
        note=note,
    )
    _enqueue_chain(session, user_id=user_id, kind="consume", amount=freeze_amount, entry=entry)
    return account


def list_ledger(
    session: Session, user_id: int, *, page: int, page_size: int
) -> tuple[list[CreditLedger], int]:
    """某用户的流水，**最新的在前**，分页。

    【为什么排序要带 `id DESC` 兜底】因为同一微秒写进来的多条
    （注册赠送 + 人工调整在同一个事务里）时间可能完全相同，
    只按时间排的话先后由排序算法决定，不稳定 —— 用户会看到
    早的一条排在新的一条前面，刷新一次顺序又变。
    `id` 是单调递增的，正好当「写入顺序」用。

    前端 Mock 在自己的注释里把这条坑拆得很细
    （`fake_api_client.dart:376-392`），说的是同一件事。
    """
    base = select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user_id)
    total = session.scalar(base) or 0

    rows = session.scalars(
        select(CreditLedger)
        .where(CreditLedger.user_id == user_id)
        .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total
