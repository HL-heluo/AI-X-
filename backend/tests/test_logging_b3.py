"""日志接线 —— `aivideo.*` 的日志真的有没有出口。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件守的是什么】

B3 手工验收时发现的缺陷：uvicorn 的默认日志配置**不给 root 挂 handler**，
所以 `aivideo` 这棵树上的 INFO 全部被丢掉 —— 启动横幅、`worker 启动`、
每轮 tick 摘要，在生产里一个字都打不出来。而它们在 pytest 下**看起来
完全正常**（pytest 在 root 上装了捕获 handler），所以这个洞没有任何
测试能发现，只有真跑一次进程才看得见。

所以这里补的不是「日志内容对不对」，而是**接线**：
「没人配日志时我们配」「有人配过时不抢」——两条都钉住。
──────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

import pytest

from app.logging_setup import (
    APP_LOGGER_NAME,
    attach_app_handler,
    configure_logging,
    root_is_configured,
)


@pytest.fixture
def bare_app_logger(monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    """把应用 logger 恢复成「上面什么都没有」的状态。

    ─────────────────────────────────────────────────────────
    【为什么用 `monkeypatch.setattr` 装一个空列表，而不是 `.handlers.clear()`】

    因为 `clear()` 会把列表**原地**清掉，而这个 logger 是进程级的 ——
    在同一个进程里跑的其他用例、以及 pytest 自己的捕获，都会跟着受影响，
    表现是「另一个文件里的某条用例红了」，跟这里毫无关系。

    `monkeypatch.setattr` 会在用例结束时把**原来那个列表对象**装回去，
    所以我们往临时列表里 `addHandler` 的那个 handler 自然就没了。

    ⚠️ **这个夹具只动 `aivideo`，不动 root** —— root 上那个 handler 是
      pytest 的日志插件在**每个阶段**都要重挂一次的，测试里清掉它会
      被立刻盖回来。所以「root 空着」那一半改用
      `root_is_configured` + 替身来验，见下面那条用例。
    ─────────────────────────────────────────────────────────
    """
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    monkeypatch.setattr(app_logger, "handlers", [])
    # 下面两行**只为了登记还原**（`attach_app_handler` 会改这两个属性，
    # 而它们都是进程级的，用例跑完必须还回去，否则会影响后面的用例）。
    monkeypatch.setattr(app_logger, "level", app_logger.level)
    monkeypatch.setattr(app_logger, "propagate", app_logger.propagate)
    return app_logger


class _RootStub:
    """只带 `handlers` 的替身 —— `root_is_configured` 也只读这一个属性。"""

    def __init__(self, handlers: list[logging.Handler]) -> None:
        self.handlers = handlers


def test_root空着时判定为没配过() -> None:
    """判据本身：root 上没有 handler = 没人配过 = 该我们配。

    ─────────────────────────────────────────────────────────
    【为什么这条要用替身，而不是真去清空 root】

    见 `bare_app_logger` 的说明：pytest 的插件在每个阶段往 root 重挂
    handler，所以「root 空着」这个状态在 pytest 里**构造不出来**。
    而它恰恰是**生产唯一会走的那条分支**（uvicorn 不给 root 挂东西）——
    真进程里出事、测试里测不到，这个组合是 B3 那次手工验收才发现的。
    把判据抽成函数之后，这条分支第一次可测。
    ─────────────────────────────────────────────────────────
    """
    assert root_is_configured(_RootStub([])) is False  # type: ignore[arg-type]
    assert root_is_configured(_RootStub([logging.NullHandler()])) is True  # type: ignore[arg-type]


def test_没人配过日志时_给应用挂上handler(bare_app_logger: logging.Logger) -> None:
    """挂的时候恰好挂一个 StreamHandler，并把级别设到 INFO。

    【为什么断言「恰好一个」】一个 logger 上挂两个同样的 handler，
    表现是每条日志打印两遍 —— 看起来只是「有点吵」，很容易被忽略，
    而它会让日志的体量翻倍。
    """
    attach_app_handler(logging.INFO)

    assert len(bare_app_logger.handlers) == 1
    assert isinstance(bare_app_logger.handlers[0], logging.StreamHandler)
    assert bare_app_logger.level == logging.INFO


def test_已经有人配过日志时不抢(bare_app_logger: logging.Logger) -> None:
    """pytest 这个环境本身就是「已经有人配过」→ 什么都不做。

    ─────────────────────────────────────────────────────────
    【这条守的是 pytest 自己】

    如果这里改成无脑挂一个 handler，`caplog` **仍然是绿的**，
    但每条日志会被打印一遍、又被捕获一遍，测试输出开始刷屏。
    这种回归不会让任何测试变红 —— 所以必须有这条。
    ─────────────────────────────────────────────────────────
    """
    assert root_is_configured() is True, "pytest 下 root 上应该有捕获 handler"

    assert configure_logging() is False
    assert bare_app_logger.handlers == []


def test_worker的日志会落到应用的handler上(bare_app_logger: logging.Logger) -> None:
    """`aivideo.worker` 打一条，挂在 `aivideo` 上的 handler 能收到。

    ─────────────────────────────────────────────────────────
    【这条钉的是「子 → 父」这一段传播】

    应用里有两个 logger（`aivideo` 和 `aivideo.worker`），而 handler
    只挂在**父**那一级上。所以「worker 那棵树上的日志打得出来」这件事，
    全靠子 logger 默认向上传播。B3 加的正是这个子 logger，
    以前没有它，这条接线也就没人验过。

    ⚠️ 它**不**覆盖「父 → root」那一段（改 `aivideo.propagate` 它不会红）
      —— 那一段是另一条用例守的，见下一个。
    ─────────────────────────────────────────────────────────
    """
    received: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            received.append(record)

    bare_app_logger.addHandler(_Collect())
    bare_app_logger.setLevel(logging.INFO)

    logging.getLogger("aivideo.worker").info("worker 启动")

    assert [r.getMessage() for r in received] == ["worker 启动"]


def test_应用logger仍然向上传播(bare_app_logger: logging.Logger) -> None:
    """`aivideo.propagate` 必须保持 True —— **`caplog` 就靠它**。

    ─────────────────────────────────────────────────────────
    【这条为什么值得单独占一条用例】

    因为「把父 logger 的 propagate 关掉」是一个**看起来在做好事**的改动：
    「我们已经给自己挂了 handler，再往上传不就重复打印了吗」。
    而实际上有两个后果，一个都看不见：

      · **pytest 的 `caplog` 静默失灵** —— 它在 root 上收，父级一断
        就什么都收不到。表现是「日志明明写了，测试里断言不到」；
      · 部署平台那类**在 root 上收日志**的东西也一起收不到了。

    而生产里用 stderr 看日志的人**完全看不出区别**（我们的 handler
    照常打）—— 所以这个洞只会在测试或日志平台上露头，得专门钉。
    ─────────────────────────────────────────────────────────
    """
    attach_app_handler(logging.INFO)

    assert bare_app_logger.propagate is True


def test_create_app_真的接了日志(monkeypatch: pytest.MonkeyPatch) -> None:
    """`create_app()` 必须调用 `configure_logging()`。

    ─────────────────────────────────────────────────────────
    【为什么这条不能省】因为上面三条测的都是 `logging_setup` 自己，
    而**删掉 `main.py` 里的那一行调用**不会让它们任何一条变红 ——
    缺陷会一字不差地复发，而且仍然只在真进程里才看得见。
    ─────────────────────────────────────────────────────────
    """
    calls: list[int] = []
    monkeypatch.setattr("app.main.configure_logging", lambda *a, **k: calls.append(1) or False)

    from app.main import create_app

    create_app()

    assert calls == [1], "create_app 没有接上日志配置"
