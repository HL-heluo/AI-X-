"""运维入口：人工给某个用户加积分（客服补偿 / 内测补贴）。

运行（服务器上）：

    sudo -u aivideo env HOME=/opt/aivideo/backend PYTHONIOENCODING=utf-8 \
        .venv/bin/python scripts/add_credits.py --username 123 --amount 100 --note "内测补贴"
    sudo -u aivideo env HOME=/opt/aivideo/backend PYTHONIOENCODING=utf-8 \
        .venv/bin/python scripts/add_credits.py --username 123 --show

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么走 `credits.adjust`，而不是直接 UPDATE balance】

积分就是钱，`credit_accounts.balance` 和 `credit_ledger` 必须在**同一个
事务里**一起动（见 `app/services/credits.py` 顶部）。直接改余额会留下
「账户里多了 100，流水里查无此笔」—— 用户来问「这钱哪来的」时，
没有人能回答，对账也断了。

`adjust` 的 kind 是 `adjust` 而不是 `grant`：前者是「人手工改的」，
后者专指注册赠送。流水页会把它们分开显示，混用会让运营补贴
在「赠送」栏里出现。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从仓库根目录跑：`python scripts/add_credits.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import get_session_factory  # noqa: E402
from app.models import User  # noqa: E402
from app.services import accounts, credits  # noqa: E402


def _resolve_user(session, username: str | None, user_id: int | None) -> User:
    if (username is None) == (user_id is None):
        raise SystemExit("❌ --username 和 --user-id 必须二选一。")

    if user_id is not None:
        user = session.get(User, user_id)
    else:
        user = session.scalar(
            select(User).where(
                User.username_canonical == accounts.canonicalize(username)
            )
        )

    if user is None:
        raise SystemExit("❌ 找不到这个用户。用 --show 之前先确认用户名拼对了。")
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="人工调整用户积分（写 adjust 流水）")
    parser.add_argument("--username", help="用户名（大小写不敏感）")
    parser.add_argument("--user-id", type=int, help="用户 id（与 --username 二选一）")
    parser.add_argument("--amount", type=int, help="正数=加，负数=扣；不能把余额扣成负数")
    parser.add_argument("--note", default="人工调整", help="流水备注（会显示在积分页）")
    parser.add_argument("--show", action="store_true", help="只查看余额与冻结，不做修改")
    args = parser.parse_args()

    if not args.show and args.amount is None:
        parser.error("要么给 --amount，要么加 --show 只看余额。")
    if args.amount == 0:
        parser.error("--amount 不能是 0（零额流水不会写，只会白跑一趟）。")

    session_factory = get_session_factory()
    with session_factory() as session:
        user = _resolve_user(session, args.username, args.user_id)
        account = credits.account_of(session, user.id)

        before = account.balance
        before_available = account.balance - account.frozen

        if args.show:
            print(
                f"用户 {user.username}（id={user.id}）："
                f"总余额 {account.balance}，冻结 {account.frozen}，"
                f"可用 {before_available}"
            )
            return 0

        credits.adjust(session, user.id, args.amount, args.note)
        session.commit()

        print(
            f"✅ 用户 {user.username}（id={user.id}）"
            f"积分 {before} → {account.balance}"
            f"（本次 {args.amount:+d}，冻结 {account.frozen}，备注：{args.note}）"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
