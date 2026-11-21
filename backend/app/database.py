"""数据库连接与会话。

《工程文档.md》§4.1：SQLite → PostgreSQL，SQLAlchemy 2.0 + Alembic。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件里每一行 pragma 都是为了让 SQLite 表现得像 PostgreSQL】

v1 跑 SQLite，但**代码从一开始就按 PostgreSQL 的语义写**。这不是洁癖 ——
是因为「等迁移那天再说」的代价在这几处特别高：

  · SQLite 默认**没有并发写**，也不检查外键。一边开发一边依赖
    「反正只有一个进程在写」，上线换 PostgreSQL 后就会在多 worker 下
    出现竞态，而那些竞态**只在负载高的时候出现**。
  · 更要命的是记账。§7.3 要求「冻结/结算/退回」与余额更新在**同一个事务**里
    （见 services/credits.py）。SQLite 的事务语义和 PostgreSQL 有微妙差别，
    而现在就把 `BEGIN IMMEDIATE` 显式地写出来，等于把这个假设钉在代码里。

一句话：**SQLite 是存储介质，不是语义**。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """所有表模型的基类。

    【为什么单独定义而不是直接用 `sqlalchemy.orm.DeclarativeBase`】
    因为 Alembic 的 `env.py` 要靠 `Base.metadata` 拿到全部表来生成迁移。
    如果每个模型各继承各的，`metadata` 就是散的，autogenerate 会**静默漏表**——
    它生成的迁移看起来正常，只是少了几张表。
    """


def _configure_sqlite(dbapi_conn: Any, _record: Any) -> None:  # noqa: ANN401
    """每建一条 SQLite 连接就设一次 pragma。

    【为什么是事件钩子而不是 URL 参数】`create_engine` 的 URL 里能带
    少数几个参数，但下面这些只能这样设。而它们又必须在**每条**连接上
    都生效 —— 连接池会新建连接，只在第一条上设是无效的。
    """
    assert isinstance(dbapi_conn, sqlite3.Connection)

    # ── WAL：读写不互相阻塞 ────────────────────────────────
    # 默认的 journal 模式下，一个写事务会阻塞所有读。而本项目的形态恰好是
    # **持续有读**（App 在轮询任务状态）+ **偶发有写**（worker 在记账）。
    # 不开 WAL 的话，用户轮询时会撞上「数据库被锁」，表现为随机的 500。
    dbapi_conn.execute("PRAGMA journal_mode=WAL")

    # ── 外键：SQLite 默认**不检查** ────────────────────────
    # 【这条最危险，因为它静默】不设这个 pragma，`credit_ledger.task_id`
    # 指向一个不存在的任务**完全合法**。代码在开发期看不出任何问题，
    # 直到某天有人发现流水对不上账，而且查不出是哪一条写坏的。
    dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # ── 等锁 5 秒再放弃 ────────────────────────────────────
    # 默认是 0：一撞上锁就立刻抛 `database is locked`。
    # 单 worker 下并发很低，等 5 秒几乎总能等到；不等的话就是随机 500。
    dbapi_conn.execute("PRAGMA busy_timeout=5000")

    # ── 同步落盘折中 ───────────────────────────────────────
    # NORMAL 在 WAL 模式下是安全的（断电最多丢最后一个事务，不损坏库），
    # 而 FULL 每条事务都要 fsync，写积分流水时慢得能感觉出来。
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")


def build_engine(database_url: str | None = None) -> Engine:
    """建引擎。

    [database_url] 不传就用配置里的。测试会传一个临时文件库。
    """
    url = database_url or get_settings().database_url
    is_sqlite = url.startswith("sqlite")

    kwargs: dict[str, Any] = {
        # 【为什么开 echo_pool】连接池的告警（连接泄漏、池耗尽）默认是
        # 静默的，而它们恰恰是「偶发卡住」最常见的原因。开发期开着，
        # 上线时用日志级别压下去。
        "echo_pool": False,
        # 【为什么要 pre_ping】数据库连接会被中间层悄悄掐断
        # （SQLite 不会，但 PostgreSQL 前面常有各种网关）。
        # 不 ping 的话，池里一个已经死掉的连接会以「连接被重置」
        # 的形式暴露在某个用户请求上。
        "pool_pre_ping": True,
        "future": True,
    }

    if is_sqlite:
        # 【为什么 SQLite 的默认池不能用】SQLAlchemy 对 SQLite 文件库
        # 默认用 `QueuePool`，而它按线程分发连接，每条连接都要跑一遍
        # 上面那些 pragma，且 `:memory:` 库在不同连接里是**不同的库**。
        # 用 NullPool 让每条会话拿到独立连接并显式关闭，行为最可预测。
        # （测试里如果用 `sqlite://` 内存库，还要配 StaticPool，见 conftest。）
        kwargs["poolclass"] = None
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(url, **kwargs)

    if is_sqlite:
        event.listen(engine, "connect", _configure_sqlite)

    return engine


# 进程级引擎与会话工厂。
# 【为什么这里可以用模块级全局，而 config 用 lru_cache】引擎本身是
# 线程安全的、且开销大（连接池），必须共享。测试要换库时调
# `reset_engine()`，而不是重新 import。
_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionFactory
    if _engine is None:
        _engine = build_engine()
        _SessionFactory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


def reset_engine() -> None:
    """丢掉当前引擎。

    【为什么必须提供这个】测试要在同一个进程里换库（每个用例一个干净的
    临时库）。没有它，`get_engine()` 会一直返回进程启动时建的那个引擎，
    于是测试之间互相污染 —— 而这种污染的表现通常是**随机的失败**，
    且换一个执行顺序就消失，极难定位。
    """
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：一个请求一个会话。

    【为什么不是「一个请求一个事务」由这个函数管】
    因为事务的边界是**业务**决定的，不是请求决定的。§7.3 要求
    「记账 + 更新余额 + 建任务」在同一个事务里 —— 那是一个跨越多个
    service 调用的事务，它的边界只能在 service 层划。
    这里只负责「会话在用完后一定被关掉」。
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
