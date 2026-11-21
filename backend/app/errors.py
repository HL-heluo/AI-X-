"""业务错误与它的**对外形状** —— 全项目唯一定义处。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么错误响应不能走 FastAPI 的默认形状】

FastAPI 对「校验失败」默认返回 422 + `{"detail":[{...}]}`。那个形状
**破了「无信封」这条契约**：前端 `DioApiClient._toException` 从
响应体**顶层**读 `code` 和 `message`，读出来两个都是 null —— 于是
`AppException.code == null`，UI 退回到那句什么都解释不了的
「服务端返回 HTTP 422，且响应体里没有 message 字段」。

而 §12.3 那条契约的真正分量在于：**错误码打错一个字母，用户听到的
就是一句谎话**。认不出 `INVITE_INVALID` 的前端会显示
「连不上服务器，检查一下网络再试」—— 网络好得很，是邀请码打错了。

所以这个文件做两件事：
  1. `AppError`：业务错误的唯一载体，**强制带 `ErrorCode`**；
  2. 两个异常处理器：把 `AppError` 和 pydantic 的
     `RequestValidationError` 都收敛成 `{code, message, ...}`。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.enums import ErrorCode

# ── 错误码 → HTTP 状态码 ────────────────────────────────────
# 【为什么是一张表，而不是在每个 raise 处写状态码】
# 因为那样同一个错误码在两个地方可能给出两个状态码（一个 400 一个 422），
# 而前端有些分支是**按状态码**走的（登录页看 401、`isUnauthorized` 看 401）。
# 收成一张表，任何不一致都是不可能写出来的。
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INSUFFICIENT_CREDITS: 400,
    ErrorCode.INVALID_PROMPT: 400,
    ErrorCode.IMAGE_TOO_LARGE: 400,
    ErrorCode.INVITE_INVALID: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.DUPLICATE_REQUEST: 409,
    ErrorCode.USERNAME_TAKEN: 409,
    ErrorCode.TASK_NOT_CANCELABLE: 409,
    ErrorCode.CONTENT_REJECTED: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.PROVIDER_ERROR: 502,
    ErrorCode.QUEUE_SATURATED: 503,
}

# ── 错误码 → 默认 message ───────────────────────────────────
# ⚠️ 这些文案是**给开发看的**，不是给用户看的。
#
# 前端 `ApiErrorCode.defaultMessage` 才是上屏的那一份，而且前端有一条
# 用例专门断言后端的 `message` **绝不上屏**（见
# `test/auth_flow_test.dart` 里「邀请码无效」那条 —— 它同时断言
# 屏幕上**不出现** `invite code not found`）。
#
# 所以这里可以、也应该写得直白：带上参数、带上内部 id，
# 因为读它的人是拿着日志排查的我们，不是用户。
DEFAULT_MESSAGE: dict[ErrorCode, str] = {
    ErrorCode.INSUFFICIENT_CREDITS: "可用积分不足（可用 = balance − frozen）",
    ErrorCode.INVALID_PROMPT: "提示词为空或超长",
    ErrorCode.IMAGE_TOO_LARGE: "参考图超过大小上限",
    ErrorCode.DUPLICATE_REQUEST: "幂等键重复，复用已存在的任务",
    ErrorCode.RATE_LIMITED: "触发配额（每日上限或同类并发上限）",
    ErrorCode.CONTENT_REJECTED: "输入内容未通过审核",
    ErrorCode.PROVIDER_ERROR: "provider 调用失败",
    ErrorCode.QUEUE_SATURATED: "队列已满",
    ErrorCode.UNAUTHORIZED: "未登录，或 token 失效/过期",
    ErrorCode.NOT_FOUND: "资源不存在或不属于当前用户",
    ErrorCode.USERNAME_TAKEN: "用户名已被占用",
    ErrorCode.INVALID_CREDENTIALS: "用户名或密码不正确",
    ErrorCode.INVITE_INVALID: "邀请码无效",
    ErrorCode.TASK_NOT_CANCELABLE: "任务已是终态，不能再取消",
    ErrorCode.INVALID_REQUEST: "请求参数不合法",
}


class AppError(Exception):
    """一切**业务**失败的载体。路由和 service 只抛它。

    【为什么是个异常，而不是让路由返回一个错误对象】
    因为「校验 → 写库」这段代码里，失败点可能在第 3 行、也可能在第 30 行。
    用返回值传达的话，每一个调用点都要 `if err: return err` —— 漏掉一处
    就是一个「明明失败了却继续往下走」的分支。抛异常则是**默认中断**，
    漏掉的表现是请求 500（响亮），而不是静默地把钱扣了。

    [payload] 是给**特殊错误码**用的额外顶层字段。目前只有一处：
    `DUPLICATE_REQUEST` 要把已存在的 `task` 一起带回去（§12.3 的客户端
    行为是「静默复用已存在的任务」，不带回去的话客户端无从复用）。

    ⚠️ 传 `payload` 时必须是**已经序列化好的原生数据**
    （`model_dump(mode="json")` 的产物），不能直接塞 ORM 对象：
    这个异常会穿过 `session.rollback()`，而 rollback 会把所有 ORM 对象
    expire 掉，之后再访问属性会触发一次懒加载。
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGE[code]
        self.status = HTTP_STATUS[code]
        self.payload = payload or {}
        super().__init__(f"{code.value}: {self.message}")

    def body(self) -> dict[str, Any]:
        """对外响应体。**无信封** —— 顶层就是 `code` / `message`。"""
        return {"code": self.code.value, "message": self.message, **self.payload}


def install_error_handlers(app: FastAPI) -> None:
    """把上面那两种错误收敛成同一种形状。

    【为什么它是被显式调用的，而不是用装饰器在 import 时挂上去】
    因为处理器必须挂在**具体的 app 实例**上，而这个项目会造多个 app
    （测试要造 `TEST_MODE=1` 的那个，见 `tests/conftest.py`）。
    模块级的装饰器只能挂到某一个实例上。
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        # 【为什么过一遍 jsonable_encoder】因为 payload 里可能有
        # datetime / StrEnum。JSONResponse 用的是裸的 `json.dumps`，
        # 它不认识这些类型 —— 会抛 TypeError，把一个 400 变成 500。
        return JSONResponse(status_code=exc.status, content=jsonable_encoder(exc.body()))

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """pydantic 校验失败 → 400 + `{code, message}`。

        【为什么是 400 而不是 FastAPI 默认的 422】
        422 在本项目里已经被 `CONTENT_REJECTED`（内容审核未通过）占了，
        而且前端对 422 有明确的分支语义。形状错误和内容被拒是两回事，
        用同一个状态码会让排查日志的人分不清。
        """
        # 把出错字段的路径写进 message —— 它是给开发的，不是给用户的。
        # 没有它，日志里只剩一句「请求参数不合法」，看不出是哪个字段。
        locations = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(part) for part in err.get("loc", ()))
            locations.append(f"{loc}: {err.get('msg', '')}")
        detail = "；".join(locations) if locations else "（无字段信息）"
        return JSONResponse(
            status_code=HTTP_STATUS[ErrorCode.INVALID_REQUEST],
            content={
                "code": ErrorCode.INVALID_REQUEST.value,
                "message": f"请求参数不合法：{detail}",
            },
        )
