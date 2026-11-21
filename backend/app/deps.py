"""FastAPI 依赖 —— 鉴权与数据库会话。

【为什么鉴权只有一个入口】因为「谁在请求」这件事**每一个受保护的端点
都要知道**，而 12 个端点各写一遍解析 `Authorization` 头，
就是 12 处可能写错的地方（少个空格、写成 `bearer`、忘了处理过期）。
收成一个依赖，加一个受保护端点就只是多写一个参数。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import ErrorCode
from app.errors import AppError
from app.models import User
from app.security import decode_access_token

# 【为什么 `auto_error=False`】默认的 `HTTPBearer()` 在**缺少**认证头时
# 会自己抛一个 403 + `{"detail":"Not authenticated"}` —— 那又是默认信封，
# 前端读不到 `code`。而且 403 是错的语义：用户不是「没权限」，是「没登录」，
# 前端要靠 401 去走登出分支（`AppException.isUnauthorized` 判的就是 401）。
# 关掉它，由下面自己抛 `UNAUTHORIZED`（401），形状和状态码就都是对的了。
_bearer = HTTPBearer(
    auto_error=False,
    description="登录后拿到的 JWT，放在 `Authorization: Bearer <token>` 里。",
)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    """解析 Bearer token，返回当前用户。失败一律 401。

    【为什么这里能安全地直接用会话，而不是等 service 去开事务】
    因为这是一次**只读**查询。SQLAlchemy 2.0 会为它自动开一个事务，
    而这个事务的归属就是本请求的会话 —— 后面 service 里的
    `atomic()` 复用同一个会话、提交同一个事务。这没问题，
    但**正因为如此，service 里绝不能用 `with session.begin()`**：
    事务已经开了，`session.begin()` 会抛
    `InvalidRequestError: a transaction is already begun`。
    见 `app/services/unit.py` 里的 `atomic()`。

    【被软禁用的用户为什么也返回 401 而不是 403】见上面 `auto_error`
    那段：前端只对 401 有正确的分支。而且「账号被停用」在 v1 里
    本来就不会出现（`is_active` 是为将来留的）。
    """
    if credentials is None or not credentials.credentials:
        raise AppError(ErrorCode.UNAUTHORIZED, "缺少 Authorization: Bearer 头")

    user_id = decode_access_token(credentials.credentials)
    user = session.get(User, user_id)
    if user is None:
        # token 签名合法，但用户没了（被删、或换库后用了旧 token）。
        raise AppError(ErrorCode.UNAUTHORIZED, f"token 对应的用户 {user_id} 不存在")
    if not user.is_active:
        raise AppError(ErrorCode.UNAUTHORIZED, f"用户 {user_id} 已被停用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
"""受保护端点的写法：`user: CurrentUser`。

做成别名是为了**让「这个端点需要登录」在签名里一眼可见** ——
写成 `user: Annotated[User, Depends(get_current_user)]` 也对，
但排成一列时那个区别会被淹掉。
"""

DbSession = Annotated[Session, Depends(get_db)]
"""请求级会话。**它不负责提交** —— 事务边界在 service 层，见 `get_db` 的注释。"""
