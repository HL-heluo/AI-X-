"""`/__test/*` —— **只在 `TEST_MODE=1` 时存在的**测试辅助端点。§15.1。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这批端点为什么能有「删库」和「凭空造钱」的权力】

因为 §15.1 的验收剧本要能**反复重跑**：注册 → 出图 → 转视频 → 对账。
没有重置，第二次跑就会撞上「用户名已被占用」；没有发积分，就测不了
「余额不足」那条分支。

而它们之所以不危险，靠的是**门禁是硬的**（不是「默认关但能开」）：
`app/main.py` 只在 `TEST_MODE` 为真时**注册**这个 router。
关着的时候，这些路径在路由表里根本不存在，返回普通的 404，
而且 `/docs` 上也不会列出来。

⚠️ 这两个端点**完全不鉴权** —— 一个没有 token 的请求也能删掉整个库。
这是刻意的（验收脚本要能从一个空库开始），也正因如此，
`TEST_MODE=1` 的进程**绝不可**对外提供服务。启动横幅和挂载日志里
都有一条显式警告。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.database import Base
from app.deps import DbSession
from app.enums import ErrorCode
from app.errors import AppError
from app.models import InviteCode, User
from app.schemas import GrantCreditsIn, MeOut
from app.services import accounts, credits
from app.services.unit import atomic

SEED_INVITE_CODE = "MOCK"
"""种给测试用的不限次邀请码。

【为什么是 `MOCK` 这个字符串】因为前端**全部**测试和浏览器剧本用的
就是它（`repository_layer_test` / `auth_flow_test` / `me_credits_test`
里都是 `inviteCode: 'MOCK'`）。换一个名字的话，那边每一条注册用例
都要改 —— 而那些用例是**冻结**的。
"""


class ResetOut(BaseModel):
    """重置结果。

    【为什么这个模型定义在这里，而不是 `schemas.py`】因为 `schemas.py`
    是**契约**的定义处（前端 `fromJson` 逐字段对着它）。这个响应只有
    测试脚本会读，而且它永远不该出现在线上 —— 放进契约文件里，
    等于给一个不该存在的东西发了一张通行证。
    """

    ok: bool = True
    invite_code: str


router = APIRouter(prefix="/__test", tags=["测试专用（TEST_MODE）"])


@router.get("/ping", summary="确认测试接口确实开着")
def ping() -> dict[str, str]:
    """`/health` 会说 `TEST_MODE` 开着，但它**不会**告诉你
    `/__test/*` 真的挂上了。这一条才是那个确认。"""
    return {"status": "ok", "note": "TEST_MODE=1；这些接口能造数据，绝不可对公网开放"}


@router.post("/reset", response_model=ResetOut, summary="清空数据库并种下邀请码 MOCK")
def reset(session: DbSession) -> ResetOut:
    """`drop_all` + `create_all` + 种一个不限次的邀请码。

    ─────────────────────────────────────────────────────────
    【几条让它真的可用的细节】

    · 用的是**进程级引擎**（`session.get_bind()`），不是另建一个 ——
      另建的那个会指向另一个文件（或另一个内存库），于是
      「重置成功了」但后续请求仍然看得见老数据。

    · DDL 之前先 `rollback()`：如果这个会话因为某种原因已经开了事务
      （换 `get_db` 实现、或将来有人给这里加了个依赖），drop 会在
      另一条连接上撞上 SQLite 的写锁。回滚是免费的，
      而「莫名其妙 database is locked」不是。

    · `drop_all` 按依赖倒序删表、`create_all` 按正序建 ——
      所以外键（含那对循环的 `users.invite_code_id` ↔
      `invite_codes.created_by`）不用我们操心顺序。

    ⚠️ **它不会重跑 Alembic 迁移**：这里建出来的是 `Base.metadata`
      里的模型，也就是**当前代码**的形状。迁移有漂移的话，
      测试库和 `alembic upgrade head` 出来的库会不一样 ——
      所以门禁里那一步 `alembic check` 不能省。
    ─────────────────────────────────────────────────────────
    """
    session.rollback()
    engine = session.get_bind()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with atomic(session):
        session.add(
            InviteCode(
                code=SEED_INVITE_CODE,
                note="TEST_MODE 种子邀请码（不限次）",
                # 【为什么 `max_uses=None` 而不是一个大数字】见 models.py 的
                # `InviteCode.max_uses`：NULL 就是「不限次」这个语义本身。
                max_uses=None,
                used_count=0,
                is_active=True,
            )
        )
    return ResetOut(invite_code=SEED_INVITE_CODE)


@router.post("/grant", response_model=MeOut, summary="给某个用户加积分（写 adjust 流水）")
def grant(session: DbSession, payload: GrantCreditsIn) -> MeOut:
    """给某个用户凭空加积分。**返回 `{user, credit_account}`**（就是 `/me` 的形状）。

    【为什么返回整个账户而不是一个 `{"ok": true}`】因为调用它的那条
    curl/脚本下一步十有八九是「看看够不够下单」—— 顺手带回来，
    验收脚本就少一次往返，而少一次往返就少一个可能写错的中间步骤。

    ─────────────────────────────────────────────────────────
    【为什么走 `credits.adjust` 而不是直接改 `account.balance`】

    这就是 §15.1 里「管理员脚本发积分」那个动作，它和客服手工补积分
    是同一件事 —— 于是它**必须写一条 `adjust` 流水**。直接改余额的话，
    用户的积分页会显示「余额 100，流水加起来只有 50」，
    而那种账在排查时是最难解释的。

    【为什么 `note` 有默认值】§15.1 的脚本只传用户名和金额。没有默认值
    的话那条脚本会 400，而原因是「你没给备注」—— 它是辅助端点的
    辅助字段，不该成为一次验收失败的理由。
    ─────────────────────────────────────────────────────────
    """
    username = payload.username.strip()
    note = payload.note or "测试脚本发放（TEST_MODE）"

    user = session.scalar(
        select(User).where(User.username_canonical == accounts.canonicalize(username))
    )
    if user is None:
        raise AppError(ErrorCode.NOT_FOUND, f"用户「{username}」不存在")

    with atomic(session):
        credits.adjust(session, user.id, payload.amount, note)

    return accounts.me(session, user)
