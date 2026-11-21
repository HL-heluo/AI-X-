"""密码哈希与 JWT —— **密钥与口令的唯一经手处**。

《工程文档.md》§6.1：用户名/密码 + 邀请码，**绝不存明文密码**。
无 refresh token，过期即 401（前端已经会处理，见 HANDOFF §5 第 1 条）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么直接用 bcrypt / pyjwt，不套 passlib 那一层】

passlib 一年多没发版，而它和 bcrypt 4.x 的兼容问题在社区里反复出现
（最典型的是启动时打印一行 "error reading bcrypt version" 然后照常工作
—— 那种「看起来没事」的告警最消耗排查时间）。本项目只有这两件事要
做哈希和签名，直接调底层库，出问题时栈也短得多。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import timedelta

import bcrypt
import jwt

from app.config import get_settings
from app.enums import ErrorCode
from app.errors import AppError
from app.types import utcnow

JWT_ALGORITHM = "HS256"
"""对称签名。§6.1 的会话方案只有一个签发方（我们）和一个验证方（我们），
不需要 RS256 的非对称开销与密钥轮转复杂度。"""

MAX_PASSWORD_BYTES = 72
"""bcrypt 的**硬上限**。

【为什么必须显式挡住，而不是「反正它会截断」】
bcrypt 内部只取前 72 字节。不挡的话，一个 200 字节的密码会被静默截到 72 ——
于是「前 72 字节相同的两个不同密码」互相能登录。用户以为自己设了个长密码，
实际强度只有 72 字节，而且他永远不知道。

这里选择**拒绝**而不是截断：这是客户端一厢情愿发过来的输入，
明确报错比悄悄改变语义好。
"""


def _encode_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if not raw:
        raise AppError(ErrorCode.INVALID_REQUEST, "密码不能为空")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"密码超过 {MAX_PASSWORD_BYTES} 字节（bcrypt 的上限）",
        )
    return raw


def hash_password(password: str) -> str:
    """算出可以直接落库的哈希串。

    【为什么强度从配置读（`bcrypt_rounds`）】因为测试要把它调到 4。
    默认 12 下每个用例多付 ~250ms，前端那 100 多条契约测试
    里凡是要注册的都会各付一次。
    """
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """核对密码。**任何异常都算失败**。

    【为什么这里要把异常吞成 False】登录路径上「密码密文格式不对」
    （比如库里被谁手工改坏了）不该变成 500 —— 那会把「这次登录失败」
    升级成「接口坏了」。返回 False 让调用方统一走
    `INVALID_CREDENTIALS` 那条路，同时也**不泄漏**「这个账号的
    哈希存在问题」这个信息。

    【为什么超长密码也返回 False 而不是抛】因为它本来就不可能匹配上
    任何一条已存的哈希，直接判失败才是正确的语义。
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def create_access_token(user_id: int) -> str:
    """签发 JWT。

    【`sub` 为什么是字符串】RFC 7519 要求 `sub` 是 StringOrURI，
    而 pyjwt 2.10 起会**校验**这一点 —— 传 int 进去会直接抛
    `InvalidSubjectError`。所以这里 `str(user_id)`，解码时再转回来。
    """
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """验签 + 检查过期，返回 user_id。

    【为什么所有失败都归成同一个 `UNAUTHORIZED`】因为对客户端来说
    「签名不对」「过期了」「格式不对」的处理**完全一样**：重新登录。
    分开报只会给攻击者更多信息，而不会帮到任何正常用户。
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, f"token 校验失败：{exc}") from exc

    subject = payload.get("sub")
    try:
        return int(subject)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, f"token 的 sub 不是合法用户 id：{subject!r}") from exc
