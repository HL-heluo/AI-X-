"""Inspect or initialize the Ganache contract for a stopped local demo backend."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.database import get_session_factory
from app.models import ChainOp, CreditAccount
from app.services import chain_credits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="预览账本和队列，不访问测试链")
    parser.add_argument("--new-deployment", action="store_true", help="显式切换测试链，并按账面余额回填")
    args = parser.parse_args()
    with get_session_factory()() as session:
        if args.dry_run:
            count, balance = session.execute(select(
                func.count(CreditAccount.user_id), func.coalesce(func.sum(CreditAccount.balance), 0)
            )).one()
            statuses = session.execute(select(ChainOp.status, func.count()).group_by(ChainOp.status))
            print(f"积分账户 {count}，账面总余额 {balance}")
            print("现有链队列:", dict(statuses.all()))
            return 0
        try:
            deployment = chain_credits.provision(session, replace=args.new_deployment)
        except chain_credits.ChainError as exc:
            parser.exit(1, f"本地 VCR 初始化失败：{exc}\n")
        except Exception as exc:
            parser.exit(1, f"本地 VCR 初始化失败（{type(exc).__name__}），请检查 Ganache 和演示配置。\n")
        print(f"Ganache {deployment.chain_id} · VCR {deployment.address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
