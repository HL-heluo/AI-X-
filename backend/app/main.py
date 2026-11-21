"""FastAPI 入口。

启动：`uvicorn app.main:app --reload`（或 `python -m app.main`）

─────────────────────────────────────────────────────────────
【这个文件在 v1 里刻意保持很薄】

路由逻辑全部在 `routers/` 里，这里只做四件事：建 app、挂中间件、
挂路由、暴露 `/health`。理由和前端 `app.dart` 保持薄是同一个：
**入口文件一旦开始长业务逻辑，它就变成了所有人都会去改的冲突热点**，
而且测试没法单独构造它。

【关于「无信封」这条契约】
前端 `DioApiClient._decode` 假设响应体**就是对象本身**
（`{"id": 1, ...}`），不是 `{"code":0,"data":{...}}` 这种信封。
这不是随便定的 —— 136 条前端契约测试全建立在这条上。
所以这里**绝不能**加任何统一包装的中间件。
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import ProviderKind, StorageKind, get_settings
from app.errors import install_error_handlers
from app.logging_setup import configure_logging

if TYPE_CHECKING:  # pragma: no cover - 只为类型检查，运行时不导入
    from collections.abc import AsyncIterator

logger = logging.getLogger("aivideo")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> "AsyncIterator[None]":
    """启动/关闭钩子。

    【为什么要在启动时打印一整段配置摘要】
    因为「后端连的是哪个 provider」这件事**必须一眼可见**。
    最容易发生的事故是：本地调试用 fake 跑得好好的，部署时忘了改
    环境变量（或改错了方向），于是**线上在用假数据生成假作品**，
    而所有日志看起来都正常。

    把 `PROVIDER` / `STORAGE` 大声打出来，这条事故就变成了
    「部署的人扫一眼日志就能发现」。
    """
    s = get_settings()
    banner = [
        "",
        "=" * 62,
        f"  AI 视频创作平台 · 后端 v{__version__}",
        f"  环境        : {s.app_env}",
        f"  AI provider : {s.provider.value}"
        + ("   ← 假实现，不花一分钱、不发外网请求" if s.provider is ProviderKind.fake else "   ← ⚠️ 真实计费"),
        # 【为什么图片和视频要分两行打】见上面那段：这两个开关由**两条
        # 独立的配置**决定（`PROVIDER` / `VIDEO_PROVIDER`），而它们配上
        # 不一样的组合是**预期用法**，不是配错。只打一行的话，
        # 「文生图走 fake、图生视频走 MiniMax」这个正常形态看起来像漏配。
        f"  视频 provider: {s.resolved_video_provider.value}"
        + ("（跟随上面那个）" if s.video_provider is None else ""),
        f"  对象存储    : {s.storage.value}"
        + ("   ← 本地目录，重启不丢" if s.storage is StorageKind.local else "   ← ⚠️ 真实云存储"),
        f"  数据库      : {s.database_url}",
        f"  对外地址    : {s.public_base_url}",
        f"  测试接口    : {'开（/__test/*）' if s.test_mode else '关'}",
        "=" * 62,
        "",
    ]
    for line in banner:
        logger.info(line)

    if s.provider is ProviderKind.fake:
        logger.info(
            "提示：PROVIDER=fake 下「生成」是瞬间完成的，看不出排队与等待。"
            "要看真实状态机，用 MOCK 那种注入时钟的办法（见 tests/），"
            "或者把 PROVIDER 换成 jimeng。"
            "（视频那一路是另一个开关 VIDEO_PROVIDER —— 上面那行打的就是它现在解析成了谁。）"
        )

    # ── 队列 worker（§8.3）──────────────────────────────────
    worker_stop = _start_worker(s)
    chain_stop = None
    if worker_stop is not None and (s.chain_enabled or s.fabric_enabled):
        from app.chain_worker import start_background

        chain_stop = start_background(s)
    try:
        yield
    finally:
        for stop in (worker_stop, chain_stop):
            if stop is not None:
                stop.set()
        logger.info("后端已停止。")


def _start_worker(s: Any) -> Any:  # noqa: ANN401
    """按配置起后台 worker 线程，返回停止开关（没起就是 None）。

    ─────────────────────────────────────────────────────────
    【为什么 `TEST_MODE=1` 时强制不起】

    因为 `POST /__test/reset` 会 `drop_all` + `create_all`，而后台
    worker 每 2 秒就要读一次 `tasks` 表。两者撞上的表现是日志里冒出
    「no such table: tasks」—— 它**不是**任何测试的失败，但它出现在
    一次红了的验收里，就会被当成病因去查（B2b 已经因为「并行清库」
    误判过一次，见 HANDOFF §4）。

    验收自动化需要的不是「后台真的在跑」，而是「这一轮跑完」——
    那件事由测试直接调 `worker.run_once()` 来做：确定性、
    不需要 sleep、也不会有线程在背后偷偷改库。

    ⚠️ 代价要说清楚：**`TEST_MODE=1` 的实例不会自己推进队列**。
      所以跨仓门禁（它起的正是这种实例）观察不到 `queued → submitted`
      的迁移 —— 换成真 provider 之后，那一步要靠 pytest 或
      一个 `TEST_MODE=0` 的实例来验。
    ─────────────────────────────────────────────────────────
    """
    if not s.worker_enabled:
        logger.warning("WORKER_ENABLED=0：本进程不跑队列 worker，任务不会自己推进。")
        return None
    if s.test_mode:
        logger.warning("TEST_MODE=1：不启动后台 worker（清库会和它抢表）。测试自行驱动 run_once。")
        return None

    from app.worker import start_background

    return start_background()


def create_app() -> FastAPI:
    """建 app。

    【为什么是个函数而不是模块级的一个常量】因为测试要能造出
    **配置不同的** app（比如 `TEST_MODE=1` 的那个）。模块级的单例做不到。
    模块底部仍然导出一个 `app` 供 uvicorn 用，两不耽误。
    """
    # ── 日志 ────────────────────────────────────────────────
    # 【为什么放在建 app 的第一行】因为它必须在 `lifespan` 打那段启动
    # 横幅**之前**生效。uvicorn 的默认配置不给 root 挂 handler，
    # 于是 `aivideo.*` 的 INFO 会被全部丢弃 —— 横幅（以及 B3 的
    # worker 启动/每轮摘要）本来就是这个原因一直看不见的。
    # 详见 `app/logging_setup.py` 的开头。
    configure_logging()

    s = get_settings()

    app = FastAPI(
        title="AI 视频创作平台",
        version=__version__,
        description=(
            "v1 后端。接口契约见《工程文档.md》§12；"
            "响应体**没有信封**（错误码在顶层 `code`，消息在顶层 `message`）。"
        ),
        lifespan=lifespan,
        # 【文档地址为什么显式写出来】它们默认就在 `/docs` 与 `/openapi.json`，
        # 但 `/docs` 是 B0 的门禁之一，把它写在代码里，改名时就得同时改门禁。
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ────────────────────────────────────────────────
    # 【为什么 v1 就需要它】因为前端要跑在**浏览器**里
    # （`flutter build web` + 真 Chrome 验收，见 HANDOFF §9）。
    # 浏览器会对跨源的 API 请求做预检，不给 CORS 头就直接失败 ——
    # 而这跟后端逻辑一点关系都没有，排查起来会往错的方向找。
    #
    # ⚠️ `allow_origins=["*"]` 配 `allow_credentials=True` 在浏览器里**无效**
    # （规范禁止）。本项目的鉴权走 `Authorization: Bearer` 头而不是 Cookie，
    # 所以不需要 credentials，`*` 是可行的。将来若改成 Cookie 鉴权，
    # 这两行必须一起改，否则会出现「请求发了但没带 Cookie」的怪现象。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── /media 的 nosniff（B4）───────────────────────────────
    @app.middleware("http")
    async def _nosniff_media(request: Any, call_next: Any) -> Any:  # noqa: ANN401
        """给 `/media/*` 的响应加 `X-Content-Type-Options: nosniff`。

        ─────────────────────────────────────────────────────
        【为什么 B4 才需要它】

        B4 之前 `/media` 后面没有文件（B2 不写字节）；现在它真的在
        提供**不可信字节**了 —— 产物来自 provider，而我们对它的全部
        了解就是「魔数看起来像图片/视频」（`services/transfer.py`）。

        没有这个头的话，浏览器可能会**无视我们声明的 Content-Type**
        去嗅探内容：一个实际是 HTML 的「图片」会被当成页面渲染，
        于是它里面的脚本跑在**我们域名的源**上。这正是 §9.3 那类
        「provider 回参不可全信」的落点之一。

        【为什么用中间件而不是改 StaticFiles】`StaticFiles` 是 Starlette
        的实现，改它要子类化再重挂，而挂载点那行注释专门说了
        「必须在业务路由之后」—— 让它保持是一行 `mount` 更不容易出错。
        ─────────────────────────────────────────────────────
        """
        response = await call_next(request)
        if request.url.path.startswith("/media/"):
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ── 健康检查 ────────────────────────────────────────────
    @app.get("/health", tags=["运维"], summary="健康检查")
    def health() -> dict[str, Any]:
        """健康检查。

        【为什么它不只是返回 `{"status":"ok"}`】
        因为「进程还活着」几乎不是我们关心的问题 —— 真正要问的是
        **「这个进程连的是谁」**。前端接后端时第一件事就是打这个接口，
        从返回值就能确认自己连对了环境（本地 fake 还是线上 jimeng），
        不用去翻服务器日志。

        ⚠️ 它**不返回任何密钥**，也不返回数据库里有几个用户这类信息。
        健康检查通常是公开可达的，别在这里漏东西。
        """
        return {
            "status": "ok",
            "version": __version__,
            "env": s.app_env,
            # 【这三个字段是刻意暴露的】它们决定「生成出来的东西是真的还是假的」，
            # 而这是接错环境时最先要看的东西。
            "provider": s.provider.value,
            # 【B7.x：新加的一个键，不是把上面那个改掉】它们是**两个不同的
            # 事实** —— `provider` 是图片那一档、`video_provider` 是视频
            # 那一档，而这个部署形态恰恰就是「图片走 fake、视频走 MiniMax」。
            # 改掉原来那个键的话，`test_b0_smoke.py` / `test_contract_shapes_b2.py`
            # 断的 `provider == "fake"` 会红，而它们断的是对的东西。
            #
            # 报**已解析**的值（`None` 时跟随 provider），因为看这个接口的人
            # 想知道的是「视频那一路现在是谁在跑」，不是「这个开关设没设」。
            "video_provider": s.resolved_video_provider.value,
            "storage": s.storage.value,
        }

    # ── 错误形状 ────────────────────────────────────────────
    # 【为什么必须在挂路由之前】它是 `AppError` → 响应体的唯一翻译点。
    # 不挂的话，一个「积分不足」会以 500 + 一段堆栈的形式返回，
    # 前端读不到 `code`，只能显示那句什么都解释不了的通用文案。
    install_error_handlers(app)

    # ── 路由 ────────────────────────────────────────────────
    _mount_routers(app, s)

    return app


def _mount_routers(app: FastAPI, s: Any) -> None:  # noqa: ANN401
    """挂业务路由与（可能存在的）测试路由。

    ─────────────────────────────────────────────────────────
    【为什么统一在一个函数里挂，而不是在 `create_app` 里排七行
      `include_router`】

    因为这里有一件必须一眼看得见的事：**`/media` 的静态挂载必须排在
    业务路由之后**。`StaticFiles` 挂在 `/media` 上会吃掉那个前缀下的
    所有路径 —— 现在没有冲突（没有业务路由在 `/media` 下），
    但把它写在路由前面，将来某天有人加一个 `/media/xxx` 接口时，
    表现是「这个接口 404，而静态文件正常」，排查方向会反。

    【`/health` 不在这里】它挂在 `create_app` 里、紧挨着中间件 ——
    因为它是 B0 的既有端点，而 B0 的验收标准里写着「不依赖任何业务模块」。
    把它挪进来的话，`/health` 会因为一个业务 router 的 import 错误
    而整个起不来。
    ─────────────────────────────────────────────────────────
    """
    # 逐个 import：这样某个 router 的 import 出错时，报错行直接指向它，
    # 而不是指向 `create_app` 顶部那一大坨 import。
    from app.routers import assets, auth, credits, generation, marketplace, me, tasks, uploads

    for router in (
        auth.router,
        me.router,
        credits.router,
        generation.router,
        tasks.router,
        assets.router,
        uploads.router,
        marketplace.router,
    ):
        app.include_router(router)

    # ── 静态文件（`STORAGE=local` 时的产物目录）──────────────
    if s.storage is StorageKind.local:
        # 【为什么用 `media_root_ready` 而不是 `media_root`】前者会 mkdir。
        # `StaticFiles` 默认在目录不存在时**抛异常**（check_dir=True），
        # 于是「忘了建 media 目录」会让整个服务起不来 —— 一个
        # 跟静态文件毫无关系的启动失败。
        app.mount("/media", StaticFiles(directory=s.media_root_ready), name="media")

    _mount_test_router(app, s)


def _mount_test_router(app: FastAPI, s: Any) -> None:  # noqa: ANN401
    """挂 `/__test/*` —— **只在 `TEST_MODE=1` 时**。

    ─────────────────────────────────────────────────────────
    【为什么这里值得写这么长的注释】

    因为 `/__test/grant` 能**凭空造钱**（给任意用户加积分），
    `/__test/reset` 能**删掉整个数据库**。它们是验收自动化的必需品
    （§15.1 的剧本要能反复重跑），但一旦在线上可达，就是一个
    不需要鉴权的提权漏洞。

    所以门禁必须是**硬**的：不是「默认关但可以开」，而是
    「只有 TEST_MODE 为真时才注册这个路由」—— 关着的时候，
    这些路径**在路由表里根本不存在**，返回的是普通的 404，
    而且 `/docs` 上也不列出来。

    【为什么不用 `if not test_mode: raise` 在函数体内挡】
    那样路由仍然存在，只是会抛错。差别在于：路由存在的话，
    将来某次重构把那个 if 挪走了，接口就静默地打开了。
    不注册的话，要打开它必须动这一行 `if`，改动的意图一眼可见。
    ─────────────────────────────────────────────────────────
    """
    if not s.test_mode:
        return

    from app.routers import test_mode

    app.include_router(test_mode.router)
    logger.warning("⚠️  TEST_MODE=1：/__test/* 已挂载。**绝不要用这个配置对外提供服务。**")


# uvicorn 用 `app.main:app` 找的就是它。
app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    _s = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=(_s.app_env == "dev"),
        log_level="info",
    )
