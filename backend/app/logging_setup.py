"""日志配置 —— 让 `aivideo.*` 的日志在**真实部署**里真的打得出来。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件为什么必须有：uvicorn 的默认日志配置里**没有 root logger】**

uvicorn 的 `LOGGING_CONFIG` 只给 `uvicorn` / `uvicorn.error` /
`uvicorn.access` 三个 logger 挂了 handler，**root 上什么都没有**。
而应用自己的 logger（`aivideo`、`aivideo.worker`）是独立的一棵树 ——
它们把记录一路 propagate 到 root，root 没有 handler，于是
**除了 WARNING 以上会被 `logging.lastResort` 兜到 stderr（无格式、
无时间戳）之外，全部丢弃**。

这个缺陷是**实测出来的**，不是读文档想出来的：

  · 用 `TEST_MODE=0` 起一个真实例，手工摆一条 `queued` 任务，
    它在 0.4 秒后被后台 worker 推进到 `succeeded` ——
    也就是说 `run_forever` 确实在跑、确实打了 `logger.info("worker 启动…")`；
  · 而那个进程的日志文件里**一个字都没有**。
  · 同样消失的还有 `lifespan` 里那段启动横幅 —— 它存在的全部意义
    就是让你「扫一眼就知道连的是 fake 还是 jimeng」（见 `main.py`
    的 lifespan），结果它从来没被打印出来过。

【为什么 test 里看不出这个问题】pytest 的 logging 插件会在 root 上
装捕获 handler，所以 `caplog` 一切正常、日志也就"看着没问题"。
**只有真跑一次进程才看得见**。这正是 HANDOFF §9.1「人工跑一次」
那条约定存在的理由。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
import sys

APP_LOGGER_NAME = "aivideo"
"""应用所有 logger 的公共前缀（`aivideo`、`aivideo.worker` 都挂在它下面）。"""

_LOG_FORMAT = "%(levelname)s:     %(message)s"
"""刻意抄 uvicorn 的格式。

【为什么不带时间戳】因为 uvicorn 自己的行（`INFO:  127.0.0.1 - "GET ..."`）
就不带，两种风格混在一起反而更难扫。需要时间戳的部署形态是
「交给 journald / 云平台的日志服务」，那时它们会自己加。
"""


def root_is_configured(root: logging.Logger | None = None) -> bool:
    """root 上是不是已经有 handler 了（也就是**别人已经配过日志**）。

    ─────────────────────────────────────────────────────────
    【为什么要判断这个，而不是无脑挂一个 handler】

    「已经有人配过日志」是一个非常常见的状态，而那种情况下我们再挂
    一个是**有害**的：

      · **pytest** 在 root 上装了捕获 handler。无脑挂一个的话，
        每条日志会被打印一遍、又被 caplog 收一遍 —— 测试输出开始
        刷屏，而 caplog 的断言仍然是对的，于是没人会去修它。
      · **部署平台**（systemd / 容器运行时 / 云日志 agent）通常也
        自己配 root。抢着配的话，日志格式变成我们说了算，
        平台那边的结构化解析就断了。

    【为什么这是个单独的函数，而不是 `configure_logging` 里的一行 if】

    因为 root 上「有没有 handler」这件事**在 pytest 里测不出来**：
    pytest 的 logging 插件在 setup / call / teardown **每个阶段**
    都重新往 root 上挂一个捕获 handler，所以测试里清空 root 会被它
    立刻盖回去（实测撞过）。判据抽出来之后，两种取值都能用替身验。
    ─────────────────────────────────────────────────────────
    """
    return bool((root or logging.getLogger()).handlers)


def attach_app_handler(level: int = logging.INFO) -> None:
    """真正挂 handler 的那一步。**不做任何判断。**

    【为什么要和判断分开】这样「该不该配」和「配成什么样」各自能被
    单独验 —— 合在一起的话，只有「不该配」那一半是可达的
    （见 `root_is_configured` 里那段）。
    """
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    app_logger.addHandler(handler)


def configure_logging(level: int = logging.INFO) -> bool:
    """给 `aivideo` 这棵树挂一个 handler。返回**这次到底装了没有**。

    ─────────────────────────────────────────────────────────
    【为什么只挂 `aivideo`，不碰 root】
    `logging.basicConfig` 的思路一样，但它动的是 root ——
    而 uvicorn 的 `uvicorn` logger 会 propagate 到 root，
    于是 uvicorn 自己的访问日志会被打印两遍（这个坑很有名）。
    我们只挂 `aivideo`，就绕开了它。

    【为什么挂着 `propagate=True` 不动它】
    因为要让 `caplog`（它在 root 上收）和我们自己的 handler 都能拿到
    记录。`propagate=False` 会让 caplog 静默失灵 ——
    表现是「日志写了，测试里断言不到，而生产里看得见」，
    排查方向会完全跑偏。

    ⚠️ **不会重复打印**：`logging` 找到第一个有 handler 的祖先
      就停止往上找 `lastResort`。`aivideo` 上有 handler 之后，
       同一条 WARNING 不会被 stderr 再兜一遍。
    ─────────────────────────────────────────────────────────
    """
    if root_is_configured():
        # 〔为什么不顺手记一句 "skipping logging setup"〕
        # 因为这句话本身就得打日志，而我们现在正站在「日志能不能打出来」
        # 这个问题的答案上 —— 用它去报告自己没被配置，是循环的。
        # pytest 下它还会给每条用例的 setup 都刷一行噪音。
        return False

    attach_app_handler(level)
    return True
