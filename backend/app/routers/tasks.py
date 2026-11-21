"""任务 —— `GET /tasks` / `GET /tasks/{id}` / `POST /tasks/{id}/cancel`。§8 / §12.1。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.schemas import TaskListOut, TaskOut
from app.services import generation

router = APIRouter(prefix="/tasks", tags=["任务"])


@router.get("", response_model=TaskListOut, summary="任务列表（按状态筛选）")
def list_tasks(
    user: CurrentUser,
    session: DbSession,
    status: str | None = Query(
        None,
        description="`active`（进行中）或 `done`（已完成/失败/取消）；不传 = 全部",
    ),
) -> TaskListOut:
    """`{items, page, page_size, total}` —— **不是分页接口**。

    ─────────────────────────────────────────────────────────
    【为什么没有 `page` / `page_size` 参数】

    因为 §12.1 里的 `/tasks` 没有分页参数，前端
    `RemoteTaskRepository._fetchList` 也专门写了注释解释它为什么
    不用 `Paged.fromJson`（「借 Paged 来解包会让人以为这里有翻页」）。
    一个任务列表页要的是「进行中的」和「最近完成的」两屏，
    两屏加起来也不该有几百条。

    ⚠️ 代价是明确的：任务攒到几千条时这个响应会变大。真到了那天，
    要改的是**契约**（前端得先支持翻页），不是这里偷偷加一个
    `page_size=20` —— 偷偷加会让第 21 条任务静默消失，
    因为前端拿到 `items` 就直接渲染。

    【`status` 传了别的值怎么办】当成「不筛」。理由同 `/generation/cost`
    的 `ratio`：多一个不认识的值不该让请求失败。而这里**不能**报
    400 还有一个更实际的理由 —— 前端将来可能加第三个筛选值
    （比如「已取消」），那时老后端不认它，报 400 会让整个页面
    打不开；当「不筛」则是显示得多了点，用户还能用。
    ─────────────────────────────────────────────────────────
    """
    return generation.list_tasks(session, user, status)


@router.get("/{task_id}", response_model=TaskOut, summary="任务详情（含排队位次）")
def task_detail(task_id: int, user: CurrentUser, session: DbSession) -> TaskOut:
    """单条任务。不是自己的一律 404（不是 403 —— 见 `services/assets.py`）。"""
    return generation.task_detail(session, user, task_id)


@router.post("/{task_id}/cancel", response_model=TaskOut, summary="取消任务（按 §7.4 退费）")
def cancel_task(task_id: int, user: CurrentUser, session: DbSession) -> TaskOut:
    """取消。

    【为什么是 POST 而不是 DELETE】因为取消**不删数据** ——
    任务行要留着（流水、资产、对账都指向它）。语义上是「让这个任务
    转到一个新状态」，那是一个动作，不是一个资源删除。

    【已经终态的任务取消返回 409 `TASK_NOT_CANCELABLE`】见 §7.4：
    终态不可逆。返回值里带着任务本体现在是什么状态，
    前端可以据此把它显示成对应样子，而不是干巴巴一句「操作失败」。
    """
    return generation.cancel_task(session, user, task_id)
