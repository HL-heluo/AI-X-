"""自定义列类型。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件为什么存在：一个会静默偏差 8 小时的坑】

SQLite **没有时间类型**，它把 `DATETIME` 存成一个字符串，也不存时区。
于是「写进去带时区、读出来不带时区」这件事默认会发生，
而它引起的失败长这样：

    后端读出来 → datetime(2026, 10, 12, 8, 30)   ← naive，其实是 UTC
    序列化成  → "2026-10-12T08:30:00"            ← 没有 Z，也没有 +00:00
    前端解析  → DateTime.tryParse(...) 按**本地时间**理解它
                然后 .toUtc() 减掉 8 小时 → 变成 00:30

也就是说，**同一条流水，后端存 8:30，用户看到 0:30**，
而且前后端各自的测试都是绿的 —— 因为两边都没写错，错的是中间那根字符串
少了一个时区标记。

修法是在类型层强制两头都带时区：写入时归一到 UTC，
读出时贴上 `UTC` 的 tzinfo。这样 Pydantic 序列化出来一定带
`Z` 或 `+00:00`，前端的 `asDateTimeOrNull` 就能正确还原。
（前端那条路径的注释见 `lib/core/json_utils.dart` 的 `asDateTimeOrNull`
—— 它明确说了「统一落到 UTC 存着，要显示时再由 UI 层单独转」。）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, TypeDecorator


class UtcDateTime(TypeDecorator):
    """永远以 UTC 存、永远以带时区的 UTC 读的时间列。

    用法：`created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)`

    【为什么用 TypeDecorator 而不是在每处 `.replace(tzinfo=UTC)`】
    因为「记得每处都处理」这条纪律的失效率是 100%。收进类型里之后，
    任何一个用这个类型的列都**不可能**漏，包括将来新加的列。
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        """写库前：把任何时区的 datetime 归一到 UTC。"""
        if value is None:
            return None
        if value.tzinfo is None:
            # ⚠️ naive 的 datetime 被认为**就是 UTC**，而不是本地时间。
            #
            # 【为什么这么定】因为本项目的所有时间戳都由 `utcnow()` 产生，
            # 它永远是带时区的。走到这个分支说明有人手写了一个 naive
            # datetime —— 那种情况下「当成 UTC」比「当成服务器本地时间」
            # 更安全：服务器本地时间取决于部署机器的 TZ 设置，
            # 那是一份没写在代码里的隐藏配置。
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        """读出来：把 SQLite 丢掉的时区信息贴回去。

        【这一步就是整个文件存在的理由】少了它，读出来的是 naive
        datetime，序列化后不带时区标记，前端会按本地时间理解 —— 差 8 小时。
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    """当前时刻（带时区的 UTC）。

    【为什么不用 `datetime.utcnow()`】它返回的是 **naive** 的 UTC 时间
    —— 名字里写着 utc，但对象上没有时区。Python 3.12 起它已经被
    标记为 deprecated（因为「naive 但其实是 UTC」这个组合骗了太多人）。

    全项目的时间戳都从这里取，一个来源。
    """
    return datetime.now(UTC)


class EnumStr(TypeDecorator):
    """把 Python 枚举存成字符串列。

    ─────────────────────────────────────────────────────────
    【为什么不用 SQLAlchemy 原生的 `Enum` 类型】

    因为原生 `Enum` 在 PostgreSQL 上会建一个**真正的 PG ENUM 类型**，
    而改枚举值（加一个状态、改一个拼写）在 PG 上是一条
    `ALTER TYPE ... ADD VALUE`，还带着「不能在事务里加」这类限制。
    我们已知 v2 要加状态，不想在那时候做数据库类型手术。

    存成字符串 + 一条 `CHECK` 约束，得到的是同样的保护
    （数据库层面挡得住手写的野字符串），而改起来只是一次普通的迁移。
    ─────────────────────────────────────────────────────────
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type, length: int = 32) -> None:
        self.enum_cls = enum_cls
        # 【为什么把 length 也存一份】因为 Alembic 渲染迁移脚本时
        # 要重新构造这个类型（见 alembic/env.py 的 `_render_item`），
        # 而它手上只有这个对象。存在属性上比去 `self.impl.length`
        # 里翻要稳（impl 是包装过的，不是总在）。
        self.length = length
        super().__init__(length=length)

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return str(value.value)
        # 传进来的是裸字符串：交给枚举自己校验，认不出就抛。
        return str(self.enum_cls(value).value)

    def process_result_value(self, value: object, dialect: object) -> object:
        if value is None:
            return None
        return self.enum_cls(value)

    def values(self) -> list[str]:
        """这个枚举的全部合法值 —— 给建 CHECK 约束用。"""
        return [str(m.value) for m in self.enum_cls]
