"""工作单元 —— 事务边界的**唯一划法**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么不放进 `get_db` 依赖里「一个请求一个事务」】

因为事务的边界是**业务**决定的，不是请求决定的：

  · §7.3 要求「结算 + 退回 + 更新余额」在同一个事务里 ——
    那是一个跨越多个操作的原子块，它的大小只有业务自己知道；
  · 读端点（`GET /me`）**不该**提交 —— 依赖里统一 commit 的话，
    每个查询都会多一次 `COMMIT`，而它什么也没写。

【为什么不用 `with session.begin()`】

因为鉴权依赖 `get_current_user` 已经发过一条 `SELECT`，SQLAlchemy 2.0
的 autobegin 已经为这条会话开了事务。此时再 `session.begin()` 会抛

    InvalidRequestError: A transaction is already begun on this Session.

这个坑很隐蔽：它在「不鉴权的端点」上不会出现，于是本地手测单个端点
时一切正常，接上鉴权后才炸。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def atomic(session: Session) -> Iterator[None]:
    """一个业务工作单元：成功提交，任何异常回滚并原样抛出。

    【回滚这一步为什么不能省】因为「失败不留痕」是账目正确性的底线。
    前端 `repository_layer_test` 里那条「积分不足」的用例断言被拒之后
    `balance` / `frozen` / 任务 / 流水一个都不能动 —— 如果 service 里
    先写了几行再抛错，不回滚就会留下一堆半截数据（比如一条余额没变的
    freeze 流水），而对账时那笔流水指向一个不存在的任务。

    【为什么异常要原样重抛】因为 `AppError` 要一路冒到
    `app.errors` 的处理器去变成 `{code, message}`。在这里吞掉它
    就会变成一个 200 —— 那比报错糟糕得多。

    【为什么回滚之后还能安全地读 ORM 对象】
    因为会话工厂设了 `expire_on_commit=False`（见 `app/database.py`）。
    但 **rollback 仍然会 expire 所有对象** —— 所以任何要放进响应体的
    数据，都必须在 `raise` **之前**序列化成原生类型。见
    `services/generation.py` 里幂等重复那一段。
    """
    try:
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise
