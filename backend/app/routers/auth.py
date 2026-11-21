"""注册与登录 —— `POST /auth/register` / `POST /auth/login`。§6.1 / §12.1。"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import DbSession
from app.schemas import LoginIn, RegisterIn, SessionOut
from app.services import accounts

# ⚠️ 这里**不导入 `atomic`，也不开事务** —— 注册的事务在
# `accounts.register` 内部（它要在同一个事务里建用户、建账户、
# 记赠送流水）。路由里再包一层是空转；更糟的是，将来有人把
# `atomic` 挪进路由、而 service 里那份忘了删，就会出现嵌套提交，
# 而嵌套提交在外层失败时**不会**回滚（`atomic()` 不可重入，
# 理由写在 `services/unit.py` 里）。这一行注释是留给下一个人的。

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post(
    "/register",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册（需邀请码，赠 50 积分）",
)
def register(payload: RegisterIn, session: DbSession) -> SessionOut:
    """注册。

    ─────────────────────────────────────────────────────────
    【为什么返回 201 而不是 200】

    注册**创建了一个用户**，语义上是 201。响应体照样是完整的会话
    （`{token, user, credit_account}`），前端 `RemoteAuthRepository`
    只读 body、不看状态码 —— 所以这不会破坏任何东西。

    【为什么它直接把会话返回，而不是「注册完再登录一次」】
    见 `SessionOut` 的注释：注册完立刻进首页，而首页要显示积分。
    只给 token 的话，中间会闪一下空的积分胶囊。
    ─────────────────────────────────────────────────────────
    """
    token, user, account = accounts.register(session, payload)
    return SessionOut(token=token, user=user, credit_account=account)


@router.post(
    "/login",
    response_model=SessionOut,
    summary="登录",
)
def login(payload: LoginIn, session: DbSession) -> SessionOut:
    """登录。**用户名不存在与密码错误返回完全一样的 401。**"""
    token, user, account = accounts.login(session, payload)
    return SessionOut(token=token, user=user, credit_account=account)
