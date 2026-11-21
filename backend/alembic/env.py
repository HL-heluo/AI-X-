"""Alembic 运行环境。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件相对于模板改了三处，每一处都有理由】

1. **数据库地址从 `app.config` 读，不写进 `alembic.ini`。**
   模板生成的 `alembic.ini` 里有一行
   `sqlalchemy.url = driver://user:pass@localhost/dbname`，
   而那一行是**密钥最容易被提交进 git 的地方** ——
   它长得就像个配置项，填上真密码之后没人会想起来它也要进 .gitignore。
   所以那里现在是一句注释，真值只有一个出处：`app/config.py`（环境变量）。

2. **`target_metadata` 指向我们自己的 `Base.metadata`。**
   模板里是 `None`，那样 `--autogenerate` 会默默生成一个空迁移：
   命令成功、退出码 0、什么都没建。这是最容易骗过自己的失败方式 ——
   和前端的教训（守卫测试要故意改坏跑一遍）是同一条。

3. **导入 `app.models` 只为它的副作用（把表注册到 metadata）。**
   见下面那段说明 —— 少这一句，autogenerate 会漏表。

4. **`fileConfig(..., disable_existing_loggers=False)`。**
   默认值会把此刻已存在的、且不在 `alembic.ini` 名单里的 logger
   全部关掉 —— 包括整个 `app.*` 那棵树。理由见那一行上面的注释。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 alembic 命令在任意工作目录下都能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    # ⚠️ `disable_existing_loggers=False` 不是可选项。
    #
    # `fileConfig` 的默认值是 True，而它的行为是：**把此刻已经存在的
    # 每一个 logger 都关掉**（`logger.disabled = True`），除非它出现在
    # `alembic.ini` 的 `[loggers]` 名单里 —— 而那份名单里只有
    # root / sqlalchemy / alembic。
    #
    # 后果在测试里最刺眼：跑完迁移那条用例之后，本进程里所有
    # `app.*` 的 logger 全部变哑，于是**后面每一条断言日志的用例
    # 都静默失灵** —— `caplog` 收到的是空的，看起来像「日志没写」，
    # 而代码是好的。排查方向会完全跑偏。
    # 实测撞过：B4 那条「ffmpeg 不可用时封面降级要留痕」单独跑是绿的，
    # 跑整个套件才红。
    #
    # 真跑迁移时同理：`env.py` 会 import `app.config`，那时应用那棵树
    # 已经存在了，alembic 就顺手把它关掉。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# ⚠️ 这一行**看起来没用，其实是必需的**。
#
# `from app.database import Base` 只拿到那个空的 Base 类 ——
# 此刻 `Base.metadata` 里一张表都没有。表是在 `app/models.py` 里
# 各个类被定义时才注册进去的，而那些类只有在 `import app.models`
# 时才会被求值。
#
# 少了这一行，`alembic revision --autogenerate` 会生成一个**空迁移**：
# 命令成功、没有报错、文件里只有一个空的 upgrade/downgrade。
# 然后你以为迁移写好了，建库时才发现表根本没建。
#
# B1 会把 `app/models.py` 建出来，那时这行 import 就是活的。
# 在那之前它被 try 包着，是为了让 B0 阶段 `alembic current` 这类
# 只读命令仍然可用（否则会因为 ImportError 直接退出）。
try:
    import app.models  # noqa: F401  （只为副作用：把表注册到 Base.metadata）
except ImportError:  # pragma: no cover - B1 之前 models.py 还不存在
    pass

target_metadata = Base.metadata


def _render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """教 Alembic 怎么把我们的自定义类型写进迁移脚本。

    ─────────────────────────────────────────────────────────
    【不加这个钩子会发生什么 —— 已实测】

    autogenerate 遇到自定义类型时，默认渲染成
    **限定名 + 从对象里猜出来的参数**，而且**不生成对应的 import**。
    对我们这两个类型，两头都错：

      · `app.types.UtcDateTime(timezone=True)`
        → 迁移文件里没有 `import app`，`upgrade()` 一跑就
          `NameError: name 'app' is not defined`。

      · `app.types.EnumStr(length=16)`
        → **更糟**：`EnumStr` 的构造需要一个枚举类，渲染出来的调用
          少了这个参数（迁移里压根没提是哪个枚举）。
          就算补上 import 也是 `TypeError`。
          而且「这一列是 TaskStatus 还是 LedgerKind」这个信息
          **在迁移里彻底丢失** —— 迁移脚本是数据库结构的权威记录，
          丢了这个，看迁移的人只知道「这是个 16 长的字符串」。

    【为什么用 `autogen_context.imports.add` 而不是手改迁移文件】
    手改只修一份迁移，下一份还是错的。这个钩子把「怎么渲染」
    钉在生成阶段，于是**今后每一次** autogenerate 都是对的。
    改生成器而不是改产物 —— 手改迁移文件的习惯一旦养成，
    迟早会遇到「手改了但下次生成时被覆盖」。
    ─────────────────────────────────────────────────────────
    """
    if type_ != "type":
        return False

    from app.types import EnumStr, UtcDateTime

    if isinstance(obj, EnumStr):
        # 【为什么连 app.enums 一起 import】因为下面要按**名字**引用
        # 枚举类（`TaskStatus`），而那个名字住在 app.enums 里。
        autogen_context.imports.add("import app.enums")  # type: ignore[attr-defined]
        autogen_context.imports.add("import app.types")  # type: ignore[attr-defined]
        enum_name = obj.enum_cls.__name__
        return f"app.types.EnumStr(app.enums.{enum_name}, length={obj.length})"

    if isinstance(obj, UtcDateTime):
        autogen_context.imports.add("import app.types")  # type: ignore[attr-defined]
        return "app.types.UtcDateTime(timezone=True)"

    # 其余类型交回 Alembic 的默认渲染。
    return False


def _url() -> str:
    """数据库地址。

    【为什么在这里读配置，而不是 `config.get_main_option("sqlalchemy.url")`】
    因为没有第二个真相来源就不会不一致。`alembic.ini` 里那一行已经被
    注释掉了，地址只有一个出处 —— `app/config.py`，也就是**运行时**那个。
    「迁移和运行时连的是同一个库」这件事必须是结构性成立的，
    不能靠「记得两边都改」。
    """
    return get_settings().database_url


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连数据库。

    `alembic upgrade head --sql` 会走这里。用途是**把迁移脚本拿给人看**
    （或者给 DBA 过目），而不是让程序执行。
    """
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 【为什么渲染成批处理形式】SQLite 改表（加约束、改列）只能靠
        # 「建新表 → 拷数据 → 换名」，Alembic 把它叫 batch mode。
        # 不认这个形式的话，带约束的迁移在 SQLite 上直接报错。
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连上数据库真的改。"""
    section = config.get_section(config.config_ini_section, {})
    # 【为什么要手动塞进 section】见 `_url()` 的说明：地址不在 ini 里，
    # 而 `engine_from_config` 只认 section。
    section["sqlalchemy.url"] = _url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 见上面离线模式处的说明：SQLite 改表必须走 batch mode
            render_as_batch=True,
            # 自定义类型的渲染规则 —— 见本文件顶部 `_render_item`
            render_item=_render_item,
            # 【为什么打开这两项比较】默认 Alembic 只看「表/列在不在」，
            # 不看类型变没变、默认值变没变。于是「把 String(200) 改成
            # String(2000)」这种改动**不会被 autogenerate 发现**，
            # 生成的迁移是空的，而你会以为改完了。
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
