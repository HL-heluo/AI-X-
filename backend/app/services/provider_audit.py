"""对 provider 每次调用的对账记录（§11.1）—— `provider_calls` 的写入侧。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这张表 B1 就建好了，而到 B5 为止一行都没被写过】

所以先回答「为什么非要写它」：即梦是按调用计费的，而我们的
`credit_transactions` 记的是**用户的积分**。这两本账之间隔着一次换算
（积分 → 成本），任何一次换算上的偏差（重试了却没记账、记了账却没
真的调用成功）都只能靠**调用侧**的记录去对。

【它写不进去的那一次，恰恰是最该记的那一次】

`generation.submit` 把整件事包在 `atomic()` 里：provider 拒绝时，
任务行、冻结、流水**一起回滚**（这正是「被拒的提交不留痕」那条契约）。
如果审计行也在那个事务里插，它就会跟着一起消失 —— 于是对账表里
永远不会出现「我们打了接口、对方拒了、我们没记账」的那些调用，
而它们正是对账要抓的东西。

所以这里的做法是：**先在内存里攒，等外层事务落定之后，用一条独立的
连接冲进去（`flush`）。**

【为什么必须等事务落定，而不是「同事务插 + 单独 commit」】

SQLite 只有一个写者。`submit` 在外层事务里**持着写锁**去发 HTTP；
此时任何第二条连接想写 `provider_calls`，都会在 `busy_timeout` 上
等那把锁 —— 而持锁的正是它自己，于是等成一次死锁。
所以顺序只能是「事务先结束，再冲审计」。

【best-effort 是硬要求，不是偷懒】

审计子系统出任何问题（库锁了、表被删了、字段超长了），
**都不许让一次正常的生成变成 500**。这和 `assets.delete_asset`
删文件失败只记日志是同一条纪律：附属功能的失败不能升级成主流程的失败。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.database import get_session_factory
from app.models import ProviderCall
from app.providers.base import ProviderCallMeta, ProviderFailure, ProviderResult

logger = logging.getLogger(__name__)

# 响应消息的截断长度。够装下即梦的一句报错，又不会让一行审计变成一屏。
_MAX_MESSAGE = 200

# 地址（含 query 里的签名）。provider 的报错常把**带签名的产物地址**
# 原样回显 —— 比如「download failed: https://...?X-Amz-Signature=...」。
# 落进库就等于把签名存下来了，而这张表是会被导出去对账的。
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def sanitize_message(message: str | None) -> str | None:
    """把要落库的响应消息洗一遍：**去掉地址、截断**。

    【为什么连地址都要去掉，而不是「反正它一会儿就过期了」】
    签名确实有有效期，但 ① 在有效期内它就是一次免鉴权的读取凭据；
    ② 更重要的是这条规则是**不依赖于时效**的 —— 「按签名地址进库」
    这件事本身就在 `provider_url` 那条铁律的射程里
    （那个字段被禁止出现在任何响应里，而这张表将来是可能被导出的）。
    有一条不依赖时效的规则，比一条「记得它一小时后就没事了」的规则
    可靠得多。

    【为什么要截断】对方可以回一屏 HTML 错误页。不截的话，
    一次限流风暴能在 `provider_calls` 里塞进几十 MB 的 HTML。
    """
    if message is None:
        return None
    cleaned = _URL.sub("<url>", message).strip()
    return cleaned[:_MAX_MESSAGE] or None


@dataclass(slots=True)
class PendingCall:
    """一次还没落库的调用。

    ⚠️ **这里面没有 `task_id`。** 任务 id 由 `flush(task_id=...)` 传 ——
    因为调用发生时那个 id 可能**还不存在**（任务行还没 flush），
    也可能**马上就要被回滚掉**（同步路径上的拒绝）。
    由调用方在事务落定之后回答「这次调用归谁」，是唯一能说准的时机。
    """

    action: str
        # `submit` / `query`。**自由字符串不是枚举**，理由见
        # `models.ProviderCall.action` 那段。
    provider_task_id: str | None = None
    req_key: str | None = None
    http_status: int | None = None
    resp_code: str | None = None
    resp_message: str | None = None
    latency_ms: int = 0
    error_kind: str | None = None
    attempt: int = 1


class CallAudit:
    """攒住这一轮里的调用，然后在事务之外一次冲进去。

    【为什么是一个对象，而不是模块级的全局列表】因为**它必须能被丢弃**：
    一次请求一轮 worker tick 各有一个，冲完就没了。模块级列表在
    并发请求下会互相串（A 请求的调用被 B 请求冲掉），而那种串
    在对账表里看不出来 —— 两行都是合法的记录，只是归属错了。
    """

    def __init__(self) -> None:
        self._pending: list[PendingCall] = []

    def __len__(self) -> int:
        return len(self._pending)

    def record(self, call: PendingCall) -> None:
        if not get_settings().provider_call_audit_enabled:
            return
        self._pending.append(call)

    def flush(self, *, task_id: int | None) -> None:
        """落库。**无论成败都不抛异常，也绝不重试。**

        【为什么先清空再写】写失败时把待冲队列留着，下一次 flush 会
        连同上次的一起重试 —— 而「审计写不进去」通常正是库层面的问题
        （锁、磁盘满），重试只会让同一个失败滚雪球。丢掉并记一条 error
        是更诚实的选择：**审计可以少，但不能让主流程跟着坏**。
        """
        if not self._pending:
            return
        pending, self._pending = self._pending, []
        if not get_settings().provider_call_audit_enabled:
            return

        try:
            # 【为什么开一条新会话】用调用方那条会掉进
            # 「外层事务还持着写锁」那个死锁里，见文件头的说明。
            with get_session_factory()() as session:
                for call in pending:
                    session.add(
                        ProviderCall(
                            task_id=task_id,
                            attempt=call.attempt,
                            action=call.action,
                            req_key=call.req_key,
                            provider_task_id=call.provider_task_id,
                            http_status=call.http_status,
                            resp_code=call.resp_code,
                            resp_message=call.resp_message,
                            latency_ms=call.latency_ms,
                            error_kind=call.error_kind,
                        )
                    )
                session.commit()
        except Exception:  # noqa: BLE001 —— 见文件头的「best-effort」
            logger.exception(
                "provider_calls 审计写库失败，%s 条调用没有留下对账记录"
                "（生成本身不受影响）",
                len(pending),
            )


def call_from_result(
    action: str,
    *,
    result: ProviderResult,
    latency_ms: int,
    attempt: int = 1,
) -> PendingCall:
    """一次**成功**的调用。"""
    meta = result.meta
    return PendingCall(
        action=action,
        provider_task_id=result.provider_task_id,
        req_key=meta.req_key if meta else None,
        http_status=meta.http_status if meta else None,
        resp_code=meta.resp_code if meta else None,
        resp_message=sanitize_message(meta.resp_message if meta else None),
        latency_ms=latency_ms,
        attempt=attempt,
    )


def call_from_failure(
    action: str,
    *,
    exc: ProviderFailure,
    latency_ms: int,
    attempt: int = 1,
) -> PendingCall:
    """一次**失败**的调用。

    【为什么失败的也要记，而且记的东西更多】对账的价值主要在失败上：
    一次 `50429` 限流说明「闸门开大了」，一次 `50411` 说明「入口审核
    漏了一类词」。只记成功调用的话，这两件事在对账表里**根本不存在**。

    `resp_code` 取 `exc.code`（provider 的原始码）而不是 `meta.resp_code`，
    是因为不是每个 provider 都会把码放进 meta —— 而 `ProviderFailure.code`
    按约定就该是它。meta 有值就优先用 meta（它来自响应体，更可信）。
    """
    meta: ProviderCallMeta | None = exc.meta
    return PendingCall(
        action=action,
        req_key=meta.req_key if meta else None,
        http_status=meta.http_status if meta else None,
        resp_code=(meta.resp_code if meta and meta.resp_code else exc.code),
        resp_message=sanitize_message(meta.resp_message if meta else str(exc)),
        latency_ms=latency_ms,
        error_kind=meta.error_kind if meta else None,
        attempt=attempt,
    )


__all__ = [
    "CallAudit",
    "PendingCall",
    "call_from_failure",
    "call_from_result",
    "sanitize_message",
]
