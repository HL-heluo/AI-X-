"""当前用户 —— `GET /me`。§12.1。

【为什么它单独一个文件、而不是塞进 `auth.py`】因为它的前缀是空的
（路径就是 `/me`，不带资源段），而 `auth.py` 的 router 带着
`/auth` 前缀。硬塞进去要么得为它单开一个不带前缀的 router，
要么得把路径写成绝对路径 —— 两种都比单开一个文件难读。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUser, DbSession
from app.schemas import MeOut
from app.services import accounts

router = APIRouter(tags=["用户"])


@router.get("/me", response_model=MeOut, summary="当前用户 + 积分总览")
def me(user: CurrentUser, session: DbSession) -> MeOut:
    """返回 `{user, credit_account}`。

    【为什么返回体里**没有** `available`】它是 `balance − frozen`，
    前端 `CreditAccount.available` 自己算。服务端也算一份的话，
    两个数字迟早会在某个分支上对不上 —— 而对不上的积分数字
    是用户最不可能容忍的那类 bug。
    """
    return accounts.me(session, user)
