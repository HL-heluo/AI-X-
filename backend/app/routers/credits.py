"""积分流水 —— `GET /credits/ledger`。§7.3 / §12.1。

⚠️ 路径里的 `credits` 是**复数**：它是网络上的字符串，照抄 §12.1。
代码里的标识符一律单数（§2 术语锁定）—— 所以文件名叫 `credits.py`
（对应路径段），而函数名叫 `list_ledger`。这个分界写在
`lib/core/constants/api_paths.dart` 里，前端侧也是同一套写法。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.schemas import ChainSummaryOut, LedgerEntryOut, PageOut
from app.services import chain_credits, credits

DEFAULT_PAGE_SIZE = 20
"""与前端 `Paged.pageSize` 的默认值一致。

【为什么分页参数要带上限】`page_size=100000` 会让一次请求把整张流水表
读进内存。上限 100 是「比任何真实屏幕能显示的都大」的一个数 ——
它不限制任何正常用法，只堵住手打的离谱值。
"""

MAX_PAGE_SIZE = 100

router = APIRouter(prefix="/credits", tags=["积分"])


@router.get(
    "/ledger",
    response_model=PageOut[LedgerEntryOut],
    summary="积分流水（分页，最新在前）",
)
def list_ledger(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1, description="页码，**从 1 起**"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"
    ),
) -> PageOut[LedgerEntryOut]:
    """`{items, page, page_size, total}`。

    【为什么 page 从 1 起】见 `lib/models/paged.dart` 的 `page` 注释：
    传 0 的话，用户看到的是「第一页空的、第二页才有东西」。
    这条约定在前端被反复强调，所以这里用 `ge=1` 把它钉在契约里
    —— 传 0 是**调用方的错**，该当场 400，而不是悄悄纠正成 1：
    悄悄纠正会让一个写错了页码的客户端一直拿不到它以为的那一页。

    【排序】最新的在前，`created_at DESC` 之后带 `id DESC` 兜底
    —— 同一微秒写进来的多条（赠送 + 调整）时间可能完全相同。
    理由写在 `services/credits.list_ledger` 里。
    """
    rows, total = credits.list_ledger(session, user.id, page=page, page_size=page_size)
    return PageOut[LedgerEntryOut](
        items=[LedgerEntryOut.from_entry(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/chain",
    response_model=ChainSummaryOut,
    summary="链上凭证（影子链：地址 / 合约 / 链上余额 / 最近上链记录）",
)
def chain_summary(user: CurrentUser, session: DbSession) -> ChainSummaryOut:
    """只读展示账本余额、VCR 余额和同步状态。"""
    return ChainSummaryOut(**chain_credits.chain_summary(session, user.id))
