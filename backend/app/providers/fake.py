"""假 provider —— **永久测试夹具，不是脚手架**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么它不是一个「等真接口写好后删掉」的临时实现】

§12.2 把它和真 provider 并列成两个 Protocol 实现。原因很实在：
前端的契约测试里，**冻结 32 / 结算 24 / 退回 8 / 余额 22** 这几个数字
是写死的（`repository_layer_test.dart` 的端到端那条）。
假实现复现不出这几个数，跨仓契约门禁就永远过不了。

所以它是**必须一直存在、并且必须算得对**的一等公民。
这也意味着：改了这里的算术，等于改了契约，前后端要一起动。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path

from app.config import get_settings
from app.enums import ErrorCode, TaskKind
from app.providers import pricing
from app.providers.base import GenerationRequest, ProviderFailure, ProviderResult
from app.services.transcode import (
    COVER_HEIGHT,
    COVER_WIDTH,
    TranscodeError,
    render_image,
    synthesize_video,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 失败触发词（B5）—— 让「失败」这条路在**没有 AK/SK** 时也能被走通
# ══════════════════════════════════════════════════════════════
#
# ──────────────────────────────────────────────────────────────
# 【为什么需要它：没有它，最要紧的那条路一行都没被执行过】
#
# 「冻结 → 失败 → 全额退款」是 §7.5/§7.6 里最要紧的一条路 ——
# 它是用户唯一会**投诉**的路（钱被扣了、东西没出来）。
# 但在 B5 之前，要触发它只能靠在真即梦上撞一次真失败：等限流、
# 等审核拒、或者等网络断。于是这条路在跨仓门禁里**从来没有被走过**，
# 而「从没跑过的路一定有问题」是这个项目已经吃过两次亏的教训
# （B2b 的 DioApiClient、B3 的真排队）。
#
# 【为什么是两个词而不是一个】
#
# 因为失败有两种**去向完全不同**的分岔，用同一个词触发的话，
# 总有一条分支永远走不到：
#
#   `__FAIL__`  → **不可重试** → 任务 `failed` + **全额退款**。
#                 同步路径上还会升级成 502 `PROVIDER_ERROR`。
#                 这是前端 live 门禁要用它验的那一条（用户看得见的那条）。
#   `__RETRY__` → **可重试** → 退回队列、退避后再来；
#                 次数耗尽后才落到 `failed` + 全额退款。
#                 它验的是 `handle_failure` 的第二条去向 ——
#                 「重试预算」这件事只有在它上面才看得见。
#
# 【为什么是纯 ASCII 的哨兵词】
# 因为前端的 Dart live 门禁要在源码里把它写死。中文在那里会因为
# 命令行/环境变量的编码往返变成另一串字节 —— 本项目在 GBK 上
# 已经踩过一次同源的坑（见 `moderation.DEFAULT_BLOCKLIST` 那段）。
FAIL_SENTINEL = "__FAIL__"
RETRY_SENTINEL = "__RETRY__"

# 产物的「几何」—— **契约值，不是随手挑的**。
#
# 前端的作品网格按 width/height 算每一格的高度（`work_grid.dart:109-124`），
# 而 Mock（`fake_api_client.dart:745-763`）给的就是这两个尺寸。
# 所以 fake 的产物必须**真的**是这个尺寸：B4 起 `assets.width/height`
# 是从真实字节里探出来的，尺寸一旦不同，前端布局就跟着变。
_IMAGE_SIDE = 1024
_VIDEO_WIDTH = COVER_WIDTH
_VIDEO_HEIGHT = COVER_HEIGHT


def _raise_if_sentinel(prompt: str) -> None:
    """提示词里带触发词就失败。**这是本模块唯一的失败入口。**

    【为什么不看 `kind`】因为「失败」和「出图还是出视频」无关 ——
    两条路都要能被触发，否则 live 门禁只能验一半。

    【为什么 `rejected=False`】
    因为这两个触发词代表的是「**我们**坏了 / 对方限流了」，
    不是「你的提示词违规」。搞混的话，一条本该 `failed` 的任务会被
    记成 `rejected`，用户看到的是「换个词试试」—— 而换什么词都没用。
    `rejected=True` 那条路归 `moderation`（第①层）与
    `moderation.failure_from_code`（第②层），这里有测试钉着分界。
    """
    if FAIL_SENTINEL in (prompt or ""):
        raise ProviderFailure(
            f"命中了 fake 的失败触发词 {FAIL_SENTINEL}（不可重试，用于端到端验失败路径）",
            code=ErrorCode.PROVIDER_ERROR.value,
            retryable=False,
        )
    if RETRY_SENTINEL in (prompt or ""):
        raise ProviderFailure(
            f"命中了 fake 的重试触发词 {RETRY_SENTINEL}（可重试，用于端到端验重试预算）",
            code=ErrorCode.PROVIDER_ERROR.value,
            retryable=True,
        )


class FakeProvider:
    """不花一分钱、不发一个外网请求的 provider。

    【它的「极简」体现在哪】`submit` 立刻返回成功的结果，没有
    `queued → submitted` 的等待。所以走 fake 时，`POST /generation/*`
    在**同一个事务里**就能走完整个状态机并把 task 以 `succeeded` 返回。

    这不是偷懒：跨时间的真实排队（worker、可观察的 `queue_position`）
    是 B3 的活，而它的形态取决于即梦的能力（B0.5 卡在 AK/SK 未填）。
    在这一批里，前端的层二契约测试要的正是「提交完余额就是 46 / 22」。

    【`poll` 永远返回 None 意味着什么】意味着「还没有结果可拿」。
    但走 fake 时根本没有任务会停在 `submitted`（提交就完成了），
    所以这个分支在 B2 里不会被走到 —— 它存在只是为了满足 Protocol，
    并给 B3 一个现成的落点。

    ─────────────────────────────────────────────────────────
    【B4 起它真的造字节了】

    `submit` 会把产物**真的做出来**（Pillow 渲一张 PNG / ffmpeg 合成
    一段 mp4），放进 `settings.provider_spool_root/generated/`，
    并返回一个 `file://` 地址当作 `provider_url`。

    【为什么非做不可】否则在 B6（真即梦）之前，「转存 → 魔数校验 →
    ffprobe 量尺寸 → 抽封面 → 落盘」这条链路上没有任何一行代码被执行过，
    而 B2b 的教训就是「从没跑过的路一定有问题」。这么做的另一个好处：
    `ScriptedProvider` 继承它，于是 B3 的队列/worker 测试也顺带
    把整条转存跑了一遍。

    【产物按内容缓存】同 prompt 的图、同 (尺寸, 时长) 的视频只生成一次，
    之后是复制。否则一轮队列测试要跑十几次 ffmpeg，
    而每次半秒的合成会把测试从「秒级」拖成「分钟级」。
    ─────────────────────────────────────────────────────────
    """

    name = "fake"

    # ── 计价：这几个数字就是契约值 ─────────────────────────

    def freeze_amount(self, request: GenerationRequest) -> int:
        """§7.2：`(输入时长 + 请求时长 + 余量) × 每秒单价`。

        【图为什么是固定值】文生图没有时长概念，成本固定 4 积分，
        所以冻结额 = 结算额（前端 `credit_format.isFixed` 靠
        `min == max` 判断，显示成「本次冻结 4 积分」而不是「4~4 积分」）。

        【视频为什么要加 `duration_slack_sec`】因为成片时长由 provider
        侧的 Agent 自主决定，可能比请求的长。冻结要**保证扣得起**，
        所以按「请求时长 + 3 秒余量」冻，多冻的部分事后退回。
        这个 3 是**占位值**，真值要等 B0.5 的即梦 Spike 实测（§18-2）——
        改它必须前后端一起改（前端 `_durationSlackSec`）。

        ⚠️ **B6 起算式不在这里了**（`pricing.py`），这个方法只转手。
        留着一个同名方法是因为 Protocol 要求它存在；它必须
        **只剩一行**，否则「两个 provider 各写一份算式」的分岔就回来了。
        """
        return pricing.freeze_amount(request)

    def settle_amount(self, request: GenerationRequest, result: ProviderResult) -> int:
        """按**成片实际时长**结算。§7.2。**算式在 `pricing.py`，这里只是转手。**"""
        return pricing.settle_amount(request, result)

    # ── 调用 ───────────────────────────────────────────────

    def submit(self, request: GenerationRequest) -> ProviderResult:
        """提交即完成。

        【成片时长为什么是「请求时长 + 1」】真实情况下由 provider 回参的
        `Duration` 决定，而官方文档自己说「可能与目标值存在偏差」。
        这个 +1 秒就是用来模拟那个偏差的 —— **必须有**，否则
        「退回差额」这条路径永远是零，前端那条断言
        （冻结 32 / 结算 24 / 退回 8）就永远验不到真东西。

        `done=True` 是 B3 加的，也是这个 provider 的**全部特点**：
        它当场就做完了，所以 worker 不需要把它放进 `submitted` 去等。
        前端契约（「提交完余额就是 46 / 22」）正是靠这一条成立的 ——
        不是靠 `generation.submit` 里有个「if fake 就走捷径」的分支。
        """
        if request.kind is TaskKind.text_to_image:
            # 文生图没有时长概念，成本固定，所以这边是 0。
            output = 0
        else:
            output = request.requested_duration_sec + 1

        # ── 触发词：在**造产物之前**判，而且要抛 ──────────────
        # 【为什么在造产物之前】因为一个失败的提交不该在 spool 里
        # 留下任何字节 —— 留下的话，「一次失败的生成」看起来像是
        # 产出过东西，而排查的人会去追一个根本不存在的产物。
        #
        # 【为什么是抛而不是返回一个 done=False 的结果】因为
        # Protocol 就是这么定的：`ProviderResult` 是**成功了什么**，
        # `ProviderFailure` 是**失败**。用一个「表示失败的结果」
        # 去表达失败，等于让每个调用方都得记得去查它。
        _raise_if_sentinel(request.prompt)

        return ProviderResult(
            output_duration_sec=output,
            provider_task_id=f"fake-{request.kind.value}-{abs(hash(request.prompt)) % 10**8}",
            provider_url=self._materialize(request, output),
            done=True,
        )

    # ── B4：真的把产物做出来 ───────────────────────────────

    def _spool(self) -> Path:
        """产物目录（`provider_spool_root/generated`）。

        【为什么单独一层】转存层只允许读 `provider_spool_root` **之内**
        的东西，而临时目录（`transcode`/`transfer` 用的 staging）
        也在这个根下面。分一层能让「我们自己造的产物」和
        「正在搬运的中间文件」在目录树里分得开。
        """
        return get_settings().provider_spool_root_ready / "generated"

    def _materialize(self, request: GenerationRequest, output_sec: int) -> str:
        """造出产物文件并返回 `file://` 地址。

        【颜色为什么用 sha256 而不是内置 `hash()`】Python 对字符串的
        `hash()` **每个进程都不一样**（哈希随机化）。用它来定颜色的话，
        「同 prompt 同图」只在同一个进程内成立 —— 而那正好会让
        「产物缓存」在下一次运行里全部失效，并且让两个并行进程
        写出两张不同颜色的同名图。sha256 是稳定的。
        """
        digest = hashlib.sha256(request.prompt.encode("utf-8")).digest()
        color = (digest[0], digest[1], digest[2])

        if request.kind is TaskKind.text_to_image:
            name = f"img-{_IMAGE_SIDE}-{color[0]:02x}{color[1]:02x}{color[2]:02x}.png"
            dest = self._spool() / name
            if not dest.is_file():
                self._render_atomically(
                    dest,
                    lambda tmp: render_image(_IMAGE_SIDE, _IMAGE_SIDE, color, tmp),
                    what="图片",
                )
        else:
            name = f"vid-{_VIDEO_WIDTH}x{_VIDEO_HEIGHT}-{output_sec}-{color[0]:02x}.mp4"
            dest = self._spool() / name
            if not dest.is_file():
                self._render_atomically(
                    dest,
                    lambda tmp: synthesize_video(
                        tmp,
                        width=_VIDEO_WIDTH,
                        height=_VIDEO_HEIGHT,
                        duration_sec=output_sec,
                        color=color,
                    ),
                    what="视频",
                )

        # 【为什么是 `as_uri()` 而不是手拼 `f"file:///{dest}"`】Windows 的
        # 盘符路径手拼出来是 `file:///G:/...`（三斜杠），POSIX 是
        # `file:///home/...`，而反斜杠、空格、中文都要转义。`as_uri()`
        # 是标准库对这件事的唯一正确答案，转存层再按同一套规则解回去。
        return dest.as_uri()

    def _render_atomically(
        self, dest: Path, render: Callable[[Path], None], *, what: str
    ) -> None:
        """渲染到临时名再 `os.replace`，然后让字节出现。

        【为什么不能让 ffmpeg/Pillow 直接写目标文件】因为产物是**按内容
        缓存**的：并发的两个请求（或两次 worker 轮询）会同时发现
        「这个文件不存在」，然后同时往里写。直接写的话，两个写者会
        交错出一段谁也播不了的 mp4 —— 而文件名是对的，
        所以它会被当成一个正常的缓存在之后一直用下去。

        【ffmpeg 不可用为什么要抛，而不是退回「不产字节」】
        那会变成最难查的一种情况：测试全绿、任务成功、库里的记录
        看起来完全正常，只是产物是空的。/health 和依赖闸门
        （`check_deps.py`，它把 ffmpeg 当硬依赖）都已经在盯着这件事，
        所以这里**响亮地失败**是对的。
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".tmp-{dest.name}")
        tmp.unlink(missing_ok=True)  # 上一次崩在中间的残留
        try:
            render(tmp)  # type: ignore[operator] —— 见下面那段说明
        except TranscodeError as exc:
            tmp.unlink(missing_ok=True)
            raise ProviderFailure(
                f"fake provider 造不出一段{what}：{exc}",
                code="FAKE_RENDER_FAILED",
                # 【为什么不可重试】它是环境问题（ffmpeg 不在），
                # 重试三次只是把同一句错误刷三遍。
                retryable=False,
            ) from exc
        os.replace(tmp, dest)

    def poll(self, provider_task_id: str) -> ProviderResult | None:  # noqa: ARG002
        """fake 没有「过程中的任务」，所以永远没有新结果。

        【为什么 B3 之后它还是 None，而不是「把结果还回去」】
        因为能走到 `poll` 的任务，都是 `submit` 时 `done=False` 的 ——
        而 fake 从来不给 `done=False`。也就是说这个分支在 fake 下
        **构造上不可达**，它存在只是为了满足 Protocol。

        真要说的话，它同时也是对调用方的一句提醒：如果你发现自己
        正在 `poll` 一个 fake 提交的任务，那说明 `done` 那个字段被
        弄丢了 —— 见 `tests/test_worker_b3.py` 里那条「fake 的任务
        绝不进 submitted」的用例。
        """
        return None


__all__ = ["FakeProvider"]
