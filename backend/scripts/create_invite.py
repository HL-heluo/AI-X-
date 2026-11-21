"""运维入口：往 `invite_codes` 里种一张码 / 看一眼发出去的码 / 停用一张码。

运行（**必须带 PYTHONIOENCODING=utf-8**，本机区域设置是 GBK）：

    .venv/Scripts/python.exe scripts/create_invite.py --code AIV-2026-01 --uses 5 --note "内测第一批"
    .venv/Scripts/python.exe scripts/create_invite.py --list
    .venv/Scripts/python.exe scripts/create_invite.py --deactivate AIV-2026-01

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这个脚本必须存在：没有它，部署出来的库一个用户都注册不了】

`accounts._resolve_invite` 是**真查表**的（它会拒绝任何不在
`invite_codes` 里的字符串，理由写在那个函数的注释里：这是 §7.5
「成本自保四道闸」之一）。而 `TEST_MODE` 才是唯一会免掉邀请码的
配置 —— 也就是说：

    一个正常（非 TEST_MODE）的新库，`POST /auth/register` 必然 400。

这不是 bug，是设计。但它意味着「部署」这件事的**最后一个手工动作**
是先种一张码 —— 而在 B5 之前，这个动作**没有任何工具支持**：
唯一的办法是手写一段 Python 或者直接开 sqlite3 敲 INSERT。
B7 的真进程验收要用它，运维也要用它。

【为什么不是一段「直接敲 SQL」的说明文档】
因为 `invite_codes` 有三条**业务规则**是 SQL 表达不出来的：
`code` 的唯一性、`String(32)` 的长度上限（SQLite **不强制** VARCHAR
长度 —— 一个 40 字的码能 INSERT 成功，然后在 PostgreSQL 上炸），
以及「用满 / 过期 / 停用」这三种失效方式各自的字段。
规则散在文档里会跟代码分岔；放在这里，它和 `_resolve_invite`
读的是同一批列。

【为什么默认 `--uses 1` 而不是不限次】
因为「不限次」是**最危险的那一档**（§7.5：邀请制就是成本闸门）。
默认值应该是不小心的时候也不会敞开口的那一个；要敞口必须显式写。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

# 允许从仓库根目录跑：`python scripts/create_invite.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import get_session_factory  # noqa: E402
from app.models import InviteCode  # noqa: E402
from app.types import utcnow  # noqa: E402

CODE_MAX_LEN = 32
"""`invite_codes.code` 是 `String(32)`。

⚠️ 在 SQLite 上超长**不会**报错（它不强制 VARCHAR 长度），于是这个
检查是**唯一**会在写之前拦住它的东西。和 `accounts.USERNAME_MAX_LEN`
同一个理由。
"""

UNLIMITED = 0
"""`--uses 0` 表示不限次（落库成 NULL）。

【为什么用户写 0，库里存 NULL】见 `InviteCode.max_uses` 的注释：
「不限次」和「限 99999 次」是两种意图，不该用同一个数字表达。
这里把 0 当作「不限」的**输入写法**，是因为在命令行里写 `--uses`
后面跟一个空值很难看；而库里仍然存 NULL，两者不冲突。
"""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="create_invite.py",
        description="往 invite_codes 里种码 / 列码 / 停用码（§6.1 邀请制）。",
        # 【为什么关掉它自动加的那几个缩写】`-h` 留着，但 `--u`/`--c`
        # 这种前缀匹配会让 `--use` 这种写错的参数**静默生效**成
        # `--uses`。这个脚本要改的是**能花钱的闸门**，宁可不方便。
        allow_abbrev=False,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--code", help=f"邀请码本体（最长 {CODE_MAX_LEN} 字符）")
    group.add_argument(
        "--list",
        action="store_true",
        help="列出库里所有的码（含用量与状态）",
    )
    group.add_argument(
        "--deactivate",
        metavar="CODE",
        help="停用一张码（置 is_active=false，**不删行** —— 删了会让老用户的 invite_code_id 悬空）",
    )

    parser.add_argument(
        "--uses",
        type=int,
        default=1,
        help=f"可用次数上限，默认 1；写 {UNLIMITED} 表示不限次（落库为 NULL）",
    )
    parser.add_argument("--note", default=None, help="备注（发给谁 / 哪一批），运维排查靠它认人")
    parser.add_argument(
        "--expires-in-days",
        type=int,
        default=None,
        help="多少天后过期，不写=永不过期",
    )
    return parser.parse_args(argv)


def _new_code(args: argparse.Namespace) -> int:
    """种一张新的码。已存在同名码 ⇒ 报错，**不**悄悄改现有的那张。

    【为什么不「已存在就更新」】因为「种码」和「改码」是两件事，
    合成一件的后果是：手滑重跑一次相同的命令，会把一张已经发出去了
    的、用了 3 次的码的 `max_uses` 改掉。而那是**发出去的承诺**。
    要改就显式停用再种一张新的。
    """
    code = args.code.strip()
    if not code:
        print("  [!!] 邀请码不能为空。")
        return 1
    if len(code) > CODE_MAX_LEN:
        print(f"  [!!] 邀请码 {len(code)} 字符，超过 {CODE_MAX_LEN}（列宽 String(32)）。")
        return 1
    # 【为什么要挡空白字符】`_resolve_invite` 会 `strip()` 之后精确匹配，
    # 于是中间带空格的码在注册页面上要用户原样敲出来 —— 而它看起来
    # 和普通码一模一样。挡住比事后排查便宜。
    if any(ch.isspace() for ch in code):
        print("  [!!] 邀请码里不能有空白字符（用户没法从小抄上照抄）。")
        return 1

    if args.uses < 0:
        print("  [!!] --uses 不能是负数。")
        return 1

    max_uses = None if args.uses == UNLIMITED else args.uses
    expires_at = (
        None if args.expires_in_days is None else utcnow() + timedelta(days=args.expires_in_days)
    )

    with get_session_factory()() as session:
        existing = session.scalar(select(InviteCode).where(InviteCode.code == code))
        if existing is not None:
            state = _describe(existing)
            print(f"  [!!] 邀请码 {code!r} 已经存在（{state}）。")
            print("       要改口径：先 `--deactivate` 停掉它，再种一张新的。")
            return 1

        invite = InviteCode(
            code=code,
            note=args.note,
            max_uses=max_uses,
            used_count=0,
            expires_at=expires_at,
            is_active=True,
            # 【为什么是 NULL】见 `InviteCode.created_by` 的注释：CLI 脚本
            # 没有「操作者」这个用户。填一个假的 user id 会让这张表
            # 将来无法回答「这行到底是谁建的」。
            created_by=None,
        )
        session.add(invite)
        session.commit()

    settings = get_settings()
    print(f"  [ok] 已种下邀请码 {code!r}")
    print(f"       可用次数：{'不限次' if max_uses is None else max_uses}")
    print(f"       过期时刻：{'永不过期' if expires_at is None else expires_at.isoformat()}")
    print(f"       备注    ：{args.note or '（无）'}")
    print(f"       数据库  ：{settings.database_url}")
    return 0


def _describe(invite: InviteCode) -> str:
    """一行说清一张码的状态。**给人看的**，所以照直翻译字段。"""
    if not invite.is_active:
        state = "已停用"
    elif invite.expires_at is not None and invite.expires_at <= utcnow():
        state = f"已过期（{invite.expires_at.isoformat()}）"
    elif invite.max_uses is not None and invite.used_count >= invite.max_uses:
        state = "已用满"
    else:
        state = "可用"

    # 【为什么把「不限次」整段替掉而不是写「已用 不限次」】后者在列表里
    # 读起来像一句病句，而这一行是运维要**一眼扫过**的东西。
    if invite.max_uses is None:
        return f"{state}，不限次"
    return f"{state}，已用 {invite.used_count}/{invite.max_uses}"


def _list_codes() -> int:
    """列出所有码。

    【为什么按 id 倒序】最新种的排在最前面 —— 运维要看的总是
    「我刚发出去的那一张现在用了几个」。
    """
    with get_session_factory()() as session:
        invites = session.scalars(select(InviteCode).order_by(InviteCode.id.desc())).all()

    if not invites:
        print("  [--] 库里一张邀请码都没有。")
        print("       非 TEST_MODE 的库在这个状态下注册不了任何用户 —— 用 --code 种一张。")
        return 0

    print(f"  共 {len(invites)} 张：")
    for invite in invites:
        print(f"    #{invite.id:<4} {invite.code:<24} {_describe(invite)}")
        if invite.note:
            print(f"           └─ {invite.note}")
    return 0


def _deactivate(code: str) -> int:
    """停用一张码。**不删行**（见 `InviteCode.is_active` 的注释）。"""
    with get_session_factory()() as session:
        invite = session.scalar(select(InviteCode).where(InviteCode.code == code.strip()))
        if invite is None:
            print(f"  [!!] 没有 {code!r} 这张码。")
            return 1
        if not invite.is_active:
            print(f"  [--] {code!r} 本来就是停用状态，没有改动。")
            return 0
        invite.is_active = False
        session.commit()

    print(f"  [ok] 已停用 {code!r}")
    print("       已经用这张码注册进来的用户不受影响 ——")
    print("       invite_code_id 仍然指着这一行（这正是停用优于删除的原因）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        if args.list:
            return _list_codes()
        if args.deactivate:
            return _deactivate(args.deactivate)
        return _new_code(args)
    except OperationalError as exc:
        # 【为什么单独接这一种】「表不存在」是第一次部署时最常见的一次
        # 失败，而 SQLAlchemy 会给出一大段带 SQL 的堆栈 —— 里面**没有**
        # 一个字提到「你还没跑迁移」。这一条把它翻译成人话。
        if "no such table" in str(exc).lower():
            print("  [!!] 库里没有 invite_codes 表 —— 迁移还没跑过。")
            print("       先执行：PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m alembic upgrade head")
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
