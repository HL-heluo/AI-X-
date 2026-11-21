"""注册 / 登录 / 取当前用户 —— §6.1。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import ErrorCode
from app.errors import AppError
from app.models import CreditAccount, InviteCode, User
from app.schemas import CreditAccountOut, LoginIn, MeOut, RegisterIn, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services import credits
from app.services.unit import atomic
from app.types import utcnow

USERNAME_MAX_LEN = 32
"""`users.username` 是 `String(32)`。

【为什么在应用层也挡一道】因为不挡的话，一个 100 字的用户名会一路走到
INSERT，然后被数据库拒（SQLite 的 VARCHAR 不强制长度，所以它甚至会**成功**）
—— 到 PostgreSQL 上才炸。两边的行为不一样，就该在入口处统一。
"""

SIGNUP_GRANT_NOTE = "新用户注册赠送"
"""注册赠送那笔流水的备注。§15.1 的剧本和前端 Mock 都写这四个字。"""


def canonicalize(username: str) -> str:
    """唯一性判断用的规范化形式 —— 必须和 `models.py` 的约定一致。

    【为什么是 `casefold()` 而不是 `lower()`】见 `User.username_canonical`
    的注释：`lower()` 对某些字符（德语 ß、土耳其语 İ）给出的不是大小写
    无关的等价类。用户名最终会限制成 ASCII，但规范化是最后一道。
    """
    return username.strip().casefold()


def _resolve_invite(session: Session, raw: str) -> InviteCode:
    """把邀请码字符串换成一行 `invite_codes`。查不到就 400。

    ─────────────────────────────────────────────────────────
    【为什么这里不能像 Mock 那样「非空即通过」】

    Mock 的注释写着「不做邀请码白名单校验，任何非空邀请码都通过 ——
    验收剧本里用 MOCK 即可。**真后端会去 invite_codes 表里查**」。
    这张表是 §7.5 列的「成本自保四道闸」之一：用户总量受控等于
    花销总量受控。放行任意字符串等于把这道理序闸门拆掉。

    【失败为什么全部归成同一个 `INVITE_INVALID`】
    「不存在 / 已停用 / 过期 / 用超」对用户是同一件事：换个码。
    分开报会让「这个码存在但被停用了」变成一条可探测的信息。

    ⚠️ `message` 写的是**给开发看的**原文（带上了码本身和原因）。
    前端 `ApiErrorCode.inviteInvalid.defaultMessage` 才是上屏的那一句
    （「邀请码无效，请确认后再试」），并且 `auth_flow_test` 有一条用例
    专门断言后端的 `message` **绝不上屏**。
    ─────────────────────────────────────────────────────────
    """
    code = (raw or "").strip()
    if not code:
        raise AppError(ErrorCode.INVITE_INVALID, "邀请码为空")

    invite = session.scalar(select(InviteCode).where(InviteCode.code == code))
    if invite is None:
        raise AppError(ErrorCode.INVITE_INVALID, f"邀请码 {code!r} 不存在")
    if not invite.is_active:
        raise AppError(ErrorCode.INVITE_INVALID, f"邀请码 {code!r} 已停用")
    if invite.expires_at is not None and invite.expires_at <= utcnow():
        raise AppError(ErrorCode.INVITE_INVALID, f"邀请码 {code!r} 已于 {invite.expires_at} 过期")
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        raise AppError(
            ErrorCode.INVITE_INVALID,
            f"邀请码 {code!r} 已用满（{invite.used_count}/{invite.max_uses}）",
        )
    return invite


def _ensure_username_ok(username: str) -> None:
    """用户名本身的形状。**不做唯一性判断** —— 那是另一件事。"""
    if not username:
        raise AppError(ErrorCode.INVALID_REQUEST, "用户名为空")
    if len(username) > USERNAME_MAX_LEN:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"用户名超过 {USERNAME_MAX_LEN} 字（实际 {len(username)}）",
        )


def _ensure_username_free(session: Session, username: str) -> None:
    """唯一性。**这里只是给友好错误，真正的保证是数据库约束。**

    见 `register` 里那段关于 `IntegrityError` 的说明。
    """
    existing = session.scalar(
        select(User.id).where(User.username_canonical == canonicalize(username))
    )
    if existing is not None:
        raise AppError(ErrorCode.USERNAME_TAKEN, f"用户名「{username}」已被占用")


def _session_payload(session: Session, user: User) -> tuple[str, UserOut, CreditAccountOut]:
    account = credits.account_of(session, user.id)
    return (
        create_access_token(user.id),
        UserOut.from_user(user),
        CreditAccountOut.from_account(account),
    )


def register(session: Session, payload: RegisterIn) -> tuple[str, UserOut, CreditAccountOut]:
    """注册。§6.1 + §12.1。

    ─────────────────────────────────────────────────────────
    【校验顺序为什么是「邀请码 → 用户名 → 密码」】

    邀请码**排在用户名之前**，是为了不让一个没有有效邀请码的人拿
    409/400 的差别当**用户名枚举探针**。邀请制是花钱的闸门（§7.5），
    进门之前不该能问到任何关于站内用户的信息。

    前端那两条用例在这个顺序下都是对的：
      · 占名用的 `inviteCode: 'MOCK'`（合法的种子码）→ 过邀请码 → 409；
      · 无效码那条用的是一个不冲突的用户名 → 落到 400。
    顺序不可观测，但上面是更安全的一侧。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    username = (payload.username or "").strip()

    invite = _resolve_invite(session, payload.invite_code)
    _ensure_username_ok(username)
    _ensure_username_free(session, username)
    # 哈希在事务**之外**算：bcrypt 是纯 CPU 活儿（默认 12 轮约 250ms），
    # 把它放在事务里等于凭空拉长持锁时间。它也不依赖任何数据库状态。
    password_hash = hash_password(payload.password)

    try:
        with atomic(session):
            # 再查一次：两个请求同时通过了上面的检查时，这一条会先撞上
            # 唯一约束。宁可在这里多一次 SELECT，也不要让用户看到 500。
            _ensure_username_free(session, username)
            invite.used_count += 1
            user = User(
                username=username,
                username_canonical=canonicalize(username),
                password_hash=password_hash,
                invite_code_id=invite.id,
            )
            session.add(user)
            session.flush()  # 拿 id —— 账户、流水、token 都要它
            session.add(CreditAccount(user_id=user.id, balance=0, frozen=0))
            session.flush()  # 让 credits.account_of 能取到（见下）

            # 【为什么要用 credits.grant 而不是直接写 balance】
            # 因为「改余额」和「写流水」这两件事必须永远一起发生。
            # 手写 balance += 50 的话，某天有人漏掉了流水那一行，
            # 用户就会看到「余额 50、流水是空的」。
            credits.grant(session, user.id, settings.signup_grant, SIGNUP_GRANT_NOTE)
            return _session_payload(session, user)
    except Exception as exc:  # noqa: BLE001
        # 把数据库层的唯一约束冲突翻译成业务错误。走不到是常态
        # （上面已经查过两次），但并发下它会真的发生 —— 而那时
        # 用户该看到的是「用户名已被占用」，不是一个 500。
        if _is_username_conflict(exc):
            raise AppError(ErrorCode.USERNAME_TAKEN, f"用户名「{username}」已被占用") from exc
        raise


def _is_username_conflict(exc: Exception) -> bool:
    """判断一个异常是不是 `users.username_canonical` 的唯一约束冲突。

    【为什么要看异常文本】因为 SQLite 和 PostgreSQL 抛出来的
    `IntegrityError.orig` 类型不同，而这个项目要**同时**能在两者上跑。
    匹配约束名是两种数据库都稳的做法（我们给约束起了明确的名字，
    就是为了这一刻）。
    """
    text = str(getattr(exc, "orig", exc))
    return "uq_users_username_canonical" in text or (
        "users.username_canonical" in text and "UNIQUE" in text.upper()
    )


def login(session: Session, payload: LoginIn) -> tuple[str, UserOut, CreditAccountOut]:
    """登录。

    【用户名不存在和密码错误为什么返回**同一句**】§6.1 的安全纪律：
    分开写等于给攻击者一个「这个用户名存不存在」的探测器。
    这里连 `message` 都共用 `DEFAULT_MESSAGE` 里那一条，不留任何差别。
    """
    username = (payload.username or "").strip()
    user = session.scalar(
        select(User).where(User.username_canonical == canonicalize(username))
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    if not user.is_active:
        # 【为什么被停用的账号也说「用户名或密码不正确」】说「你的账号被停用了」
        # 等于确认了「这组用户名+密码是对的」—— 那正是上面要藏起来的信息。
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    return _session_payload(session, user)


def me(session: Session, user: User) -> MeOut:
    """`GET /me`。"""
    account = credits.account_of(session, user.id)
    return MeOut(
        user=UserOut.from_user(user),
        credit_account=CreditAccountOut.from_account(account),
    )
