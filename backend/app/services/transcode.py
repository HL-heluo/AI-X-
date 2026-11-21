"""Pillow 与 ffmpeg 的**唯一落点**（B4）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这些都收在一个文件里】

因为它们是同一种东西：**一段不可信的字节要变成我们知道形状的东西**。
分散的话，「20MB 的 PNG 能声明多大尺寸」「ffmpeg 挂了要不要降级」
这类判断会在两三个文件里各写一遍，然后**各不相同** —— 而它们的
差别不会报错，只会让某一条路径悄悄绕过限制。

【两条贯穿全文件的原则】

1. **探针只读文件头，绝不整图解码。** 一张 20MB 的 PNG 可以实现
   6 万×6 万像素（压缩比极高），真解码就是一次内存炸弹。
   Pillow 是惰性的：`Image.open()` + `.size` 只读头部，
   这也正好够我们回答「多大」这个问题。

2. **ffmpeg/ffprobe 永远带超时，且不 `shell=True`。** 前者是因为
   输入是不可信字节（畸形容器让解码器长循环是已知问题），
   卡住的是 worker 线程 —— 整个平台的队列跟着停。后者见下面
   那段 Windows/GBK 的说明。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import struct
import subprocess
import warnings
import zlib
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import get_settings

logger = logging.getLogger(__name__)

# 封面的**契约尺寸**：必须与前端 Mock（`fake_api_client.dart:745-763`）
# 逐字一致。作品网格按 width/height 算每格高度（`work_grid.dart:109-124`），
# 尺寸一变，列表的比例就跟着变 —— 那不是「图片不好看」，是布局错了。
COVER_WIDTH = 1280
COVER_HEIGHT = 720

# Pillow 的格式名 → mime。**只列我们真的会遇到的**：列全了没有意义，
# 而列错一个（比如 png → image/x-png）会让前端按 mime 分支的地方认不出。
_PILLOW_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
}


class TranscodeError(Exception):
    """转码/抽帧失败。调用方决定「降级」还是「让整条转存失败」。

    【为什么不是 `AppError`】因为它发生在转存流水线里，而那个位置
    多数时候没有请求可回（worker 路径）。和 `ProviderFailure` 同款理由。
    """


class ImageProbeStatus(StrEnum):
    """探针的三种结论。**「探不出」和「太大」必须分开。**"""

    ok = "ok"
    """读出了尺寸，且在限制之内。"""

    undecodable = "undecodable"
    """不是图片 / 被截断 —— **照收**，宽高记 None。

    这是用户拍板的口径：冻结前端的契约测试上传的就是
    `List<int>.filled(1024, 0)`（1024 个 NUL）当 `ref.png`
    （`test/live_backend.dart:772` 等三处）。严格校验会让跨仓门禁变红，
    而那个红来自夹具、不来自契约。
    """

    too_large = "too_large"
    """**读出了**声明的尺寸，但它超限（或触发了炸弹保护）—— 拒收。

    ⚠️ 这一条正是「宽松」不能吞掉的东西：一个 6 万×6 万声明的 PNG
    是 20MB 以内可以做到的（压缩比），放它进来等于把「解不出就收」
    变成一句空话。**能读出尺寸的，就按尺寸管。**
    """


@dataclass(frozen=True, slots=True)
class ImageInfo:
    status: ImageProbeStatus
    width: int | None = None
    height: int | None = None
    mime: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is ImageProbeStatus.ok


@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int | None
    height: int | None
    duration_sec: float | None


# ══════════════════════════════════════════════════════════════
# 图像探针
# ══════════════════════════════════════════════════════════════


def probe_image(source: bytes | Path) -> ImageInfo:
    """读一张图的**声明尺寸**与格式。解码？一次都不做。

    ─────────────────────────────────────────────────────────
    【为什么「炸弹」要单独接住并归到 `too_large`】

    Pillow 对声明像素超过 `2 × MAX_IMAGE_PIXELS` 的图会抛
    `DecompressionBombError` —— 这正是我们要拒的那一类。如果把它和
    「不是图片」一起接住并照收，那个保护就等于关掉了：攻击者只要把
    边长声明得足够大，就能让它在任何**后续**解码处（比如将来某次
    缩略图生成）炸掉进程。

    所以结论按**原因**分，不按「有没有抛异常」分。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    # 【为什么把炸弹阈值设成 `边长上限²`】Pillow 的默认值（约 8948 万像素）
    # 是**库**的选择，不是我们的策略。我们的策略是「边长 ≤ max_upload_side」，
    # 而一张合法的最大图正好是那么多像素 —— 设成它，炸弹保护才是在替我们
    # 挡东西，而不是在挡一个我们本来就会拒的尺寸。顺带把这条策略
    # 钉在代码里：Pillow 将来改默认值不会悄悄改掉我们的判定。
    Image.MAX_IMAGE_PIXELS = settings.max_upload_side * settings.max_upload_side
    handle: bytes | io.BytesIO | Path = (
        io.BytesIO(source) if isinstance(source, bytes) else source
    )
    try:
        # 【为什么这里要 `with`】`Image.open` 持有文件句柄；
        # 传的是 Path 时，不关会攒下句柄，Windows 上还会让那个文件
        # 一直处于「被占用」状态（紧接着删它就失败）。
        #
        # 【为什么 catch_warnings】Pillow 在「像素数在 MAX 与 2×MAX 之间」时
        # 只发一条 `DecompressionBombWarning`。那一段的结论由下面那次
        # 边长比较给出，**是确定的**；而 warning 会不会被调用方的过滤器
        # 变成异常，取决于那个过滤器（`-W error` 就是一个）。一个跑在
        # worker 线程里、处理不可信字节的函数，不该有这种外部依赖。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(handle) as img:
                width, height = img.size
                fmt = img.format
    except Image.DecompressionBombError:
        return ImageInfo(ImageProbeStatus.too_large)
    except UnidentifiedImageError:
        # 非图片字节：`b"z" * 21MB`、PNG 魔数 + 一堆 0x00 都落在这里。
        return ImageInfo(ImageProbeStatus.undecodable)
    except (OSError, ValueError):
        # 截断的文件、坏头。同样是「解不出」，按用户的口径照收。
        return ImageInfo(ImageProbeStatus.undecodable)

    if not width or not height:
        return ImageInfo(ImageProbeStatus.undecodable)

    if max(width, height) > settings.max_upload_side:
        return ImageInfo(ImageProbeStatus.too_large, width=width, height=height)

    mime = _PILLOW_MIME.get(fmt or "", None)
    if mime is None:
        # 认得出能开、但不是我们要的那几种（比如 TIFF / 多帧 ICO）。
        # 【为什么这算「解不出」而不是「拒」】它不是炸弹，也不是伪装；
        # 用户拿它当参考图只是没用而已。拒它需要一条契约里没有的错误码，
        # 而那会把一次无害的上传变成一次报错。
        return ImageInfo(ImageProbeStatus.undecodable, width=width, height=height)

    return ImageInfo(ImageProbeStatus.ok, width=width, height=height, mime=mime)


# ══════════════════════════════════════════════════════════════
# ffmpeg / ffprobe
# ══════════════════════════════════════════════════════════════


@lru_cache(maxsize=4)
def _which(tool: str) -> str | None:
    """找可执行文件。**缓存** —— `shutil.which` 每次都扫一遍 PATH。

    【缓存会不会让「装了 ffmpeg 之后不重启也能用」失效】会。这是
    刻意的取舍：进程生命周期内 PATH 不变是本项目的既定前提，
    而每转存一个产物就扫一遍 PATH（Windows 上 PATH 很长）是纯浪费。
    """
    return shutil.which(tool)


def ffmpeg_available() -> bool:
    """ffmpeg 与 ffprobe **两个都在**才算可用。

    【为什么要求两个】抽帧用 ffmpeg、量尺寸用 ffprobe。只有一半的话，
    表现是「封面生成了，但尺寸是白填的」—— 那比直接降级更坏。
    """
    return _which("ffmpeg") is not None and _which("ffprobe") is not None


def _run(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """跑一个外部工具。**argv 列表、utf-8 解码、有超时。**

    ─────────────────────────────────────────────────────────
    【为什么这三条都是必需的，不是讲究】

    · **argv 列表而不是一个字符串**：Windows 上传参给原生程序走的是
      `CreateProcessW`（宽字符），非 ASCII 路径能原样过去；`shell=True`
      则会先经过一层 shell 的编码转换，中文路径变成乱码文件名。
      （本项目在 Git Bash 上已经踩过一次同源的坑：命令行里的中文
      发给原生程序会变成 GBK 字节。）

    · **`encoding="utf-8", errors="replace"`**：ffmpeg 的输出是 UTF-8，
      而本机的区域编码是 GBK —— 不指定的话，只要 ffmpeg 在 stderr 里
      打一个非 ASCII 字符（版本横幅、文件里的元数据），
      `subprocess` 就会在**解码阶段**抛 `UnicodeDecodeError`，
      而那个错误看起来和「抽帧失败」毫无关系。`errors="replace"`
      是因为诊断信息不该有机会让整件事失败。

    · **`timeout`**：见文件头。
    ─────────────────────────────────────────────────────────
    """
    return subprocess.run(  # noqa: S603 —— argv 列表，无 shell；工具名是常量
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _timeout() -> float:
    return get_settings().ffmpeg_timeout_sec


def probe_video(path: Path) -> VideoInfo | None:
    """量一段视频的尺寸与时长。**失败一律返回 None，绝不抛。**

    【为什么不抛】它在转存流水线里是个**加分项**：拿到了就写进
    `assets.width/height`，拿不到就退回按 kind 的默认值。
    为一条诊断信息让整个转存失败，是把「不重要的东西」放在
    「用户的作品」前面。

    ⚠️ 时长的用途同样只是信息 —— `assets.duration_sec` 取的是
    `task.output_duration_sec`（计费依据），不是这里量出来的。
    """
    exe = _which("ffprobe")
    if exe is None:
        return None
    argv = [
        exe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = _run(argv, timeout=_timeout())
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("ffprobe 没能启动或超时（%s）", type(exc).__name__)
        return None
    if proc.returncode != 0:
        logger.warning("ffprobe 返回 %s：%s", proc.returncode, proc.stderr.strip()[:200])
        return None

    # 【为什么在这里 import json 而不是文件顶部】`probe_video` 是本文件
    # 唯一需要它的地方，而顶部的 import 列表已经够长了。
    import json

    try:
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        width = int(stream["width"]) if stream.get("width") else None
        height = int(stream["height"]) if stream.get("height") else None
        raw_duration = (data.get("format") or {}).get("duration")
        duration = float(raw_duration) if raw_duration else None
    except (ValueError, TypeError, KeyError, IndexError):
        logger.warning("ffprobe 的输出解析不了（是不是容器坏了）")
        return None
    return VideoInfo(width=width, height=height, duration_sec=duration)


def extract_cover(video: Path, dest: Path, *, timeout: float | None = None) -> None:
    """抽第一帧当封面。**`scale=1280:720` 是契约，不是偏好。**

    【为什么要显式写 scale】源视频的分辨率由 provider 决定（720P 是
    我们请求的，但成片可能是别的比例）。不写的话封面就是源尺寸，
    而 `assets.thumbnail` 那行的 width/height 是契约值 —— 两者一旦
    不一致，作品网格里视频格子的高度就和图片格子对不上。

    【`-ss 0` 为什么在 `-i` 前面】放在前面是**输入侧快进**：解码器
    直接从第 0 秒开始，不用先解一段再丢。放在后面也能出图，
    但对一段 10 分钟的视频就要把整段解码一遍。
    """
    exe = _which("ffmpeg")
    if exe is None:
        raise TranscodeError("找不到 ffmpeg")
    argv = [
        exe,
        "-nostdin",  # 【为什么要它】ffmpeg 会去读 stdin；worker 没有终端，
        #              它读到 EOF 之前会一直等 —— 表现就是「卡住不返回」。
        "-y",  # 目标文件已存在时直接覆盖（重试转存会走到这里）
        "-ss",
        "0",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale={COVER_WIDTH}:{COVER_HEIGHT}",
        "-q:v",
        "3",
        str(dest),
    ]
    try:
        proc = _run(argv, timeout=timeout or _timeout())
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"ffmpeg 抽帧超时（{timeout or _timeout()} 秒）") from exc
    except OSError as exc:
        raise TranscodeError(f"ffmpeg 启动失败：{exc.strerror or exc}") from exc

    if proc.returncode != 0 or not dest.is_file():
        # 【为什么只截前 200 字 stderr】ffmpeg 的报错可以有几屏，
        # 而里面真正有用的是最后那一句「Invalid data found」之类。
        raise TranscodeError(f"ffmpeg 抽帧失败（{proc.returncode}）：{proc.stderr.strip()[-200:]}")


def placeholder_cover(dest: Path, *, width: int = COVER_WIDTH, height: int = COVER_HEIGHT) -> None:
    """纯色占位封面 —— C6 写的降级方案（「ffmpeg 不可用 → 用纯色占位」）。

    【为什么降级而不是让任务失败】成片**已经拿到了**，只有一个列表用的
    封面图没做成。为此把一个用户已经付费、也已经拿到视频的任务判失败，
    是把小问题升级成大问题。而占位封面在 UI 上完全够用：那一格本来就
    只是等用户点开。

    ⚠️ 它必须**成功**。所以它只用 Pillow（文件头都不解析，纯生成），
    而且尺寸取的是契约值。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 深灰底 + 一点点蓝，避免纯黑在暗色主题里看起来像「加载失败」。
    # 颜色写死是有意的：它出现在我们**自己的**产物里，不是一个旋钮。
    image = Image.new("RGB", (width, height), (32, 34, 40))
    image.save(dest, format="JPEG", quality=80)


def render_image(width: int, height: int, color: tuple[int, int, int], dest: Path) -> None:
    """渲一张纯色 PNG。**B4 的 fake provider 用它造「真产物」。**

    【为什么这个函数在 transcode 里，而不是在 fake.py 里】因为它是
    「Pillow 的落点」这条规则的直接结果：任何一处 Pillow 调用都应该
    能在这个文件里被找到。fake.py 自己 `import PIL` 的话，
    「图片相关的代码在哪」这个问题就有了两个答案。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), color)
    image.save(dest, format="PNG")


def encode_webp(source: Path, dest: Path, *, lossless: bool = False) -> None:
    """把一张图转成 WebP。**测试与验收用。**

    ─────────────────────────────────────────────────────────
    【为什么需要一个只被测试用的编码器】

    因为 WebP 是 `_MARKABLE_IMAGE_FORMATS` 里的一员，而今天**没有任何
    一条生产路径会产出 WebP**（provider 给的是 PNG / MP4，用户上传的
    字节原样存盘）。没有这个函数的话，「WebP 的标识路径」就永远不可能
    被任何一条测试走到。

    而它恰恰是三种图片里**唯一会重编码**的那一条：PNG / JPEG 靠拼
    容器字节（像素一个都不动），WebP 只能让 Pillow 重新存一遍。所以
    它是三者中最容易退化的那一条 —— 而它的退化是**安静的**：
    默认质量会把图重压一遍（实测 32.91 dB，体积缩 36%），
    代码看起来完全正常。给它留一条测试路径，就是为了让
    `_mark_webp` 里那个 `lossless=True` 不能被顺手删掉。

    `lossless=True` 在这里只用来造「另一条路的产物」做对照，
    生产侧写标识固定用无损。
    ─────────────────────────────────────────────────────────
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img.save(dest, format="WEBP", lossless=lossless)


def synthesize_video(
    dest: Path,
    *,
    width: int,
    height: int,
    duration_sec: int,
    color: tuple[int, int, int],
    timeout: float | None = None,
) -> None:
    """用 ffmpeg 合成一段**真的 mp4**（纯色 + 时长）。

    ─────────────────────────────────────────────────────────
    【为什么 fake 要真造一段视频出来，而不是给一个假地址】

    因为否则在 B6 之前，「转存」这条链路上没有任何一行代码被执行过 ——
    从下载、到魔数校验、到 ffprobe 量尺寸、到抽封面、到落盘，
    全部是「看起来写好了、实际上从没跑过」。B2b 的教训正是这个：
    让从没跑过的 `DioApiClient` 真的连上一次后端，当场发现三个问题。

    【为什么要 `-pix_fmt yuv420p`】不加的话 lavfi 的默认像素格式是
    `yuv444p` 之类，而**那只对解出封面帧没影响** —— 它影响的是
    「这段视频在任何标准播放器里能不能播」。既然它要冒充一个真产物，
    就让它真能播：验收时要拿浏览器打开它看一眼。

    【为什么 `-r 5`】5 fps 是「有多个帧可抽」与「文件小到能进 git 的
    缓存目录」之间的折中。1 fps 的话，`-ss 0` 抽帧那条路就只有一帧，
    抽帧代码里「找第一帧」的逻辑等于没被验过。
    ─────────────────────────────────────────────────────────
    """
    exe = _which("ffmpeg")
    if exe is None:
        raise TranscodeError("找不到 ffmpeg（依赖闸门里那一项应该是红的）")

    rgb = f"0x{color[0]:02x}{color[1]:02x}{color[2]:02x}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        exe,
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={rgb}:s={width}x{height}:r=5",
        "-t",
        str(duration_sec),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    try:
        proc = _run(argv, timeout=timeout or _timeout())
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"ffmpeg 合成视频超时（{timeout or _timeout()} 秒）") from exc
    except OSError as exc:
        raise TranscodeError(f"ffmpeg 启动失败：{exc.strerror or exc}") from exc

    if proc.returncode != 0 or not dest.is_file():
        raise TranscodeError(f"ffmpeg 合成视频失败（{proc.returncode}）：{proc.stderr.strip()[-200:]}")


# ══════════════════════════════════════════════════════════════
# B5：隐式标识的**写入器**（§10.1）
# ══════════════════════════════════════════════════════════════
#
# 【为什么写入器在这一层，而“写什么”在 `services/marking.py`】
# 因为这里的规则是「Pillow 与 ffmpeg 只在这一个文件里被调用」——
# 它挡住的是「图片相关的代码散在三个文件里，各有一份自己的判断」。
# `marking.py` 决定「标识里写哪几个字符串」（这是产品/合规决定），
# 这里只管「把它塞进 PNG 的哪个块」。
#
# 【为什么 XMP 要自己拼】
# Pillow 读 XMP 可以（`img.info["xmp"]`），**写**一个通用的 XMP 包不行。
# WebP 有 `xmp=` 参数，PNG 和 JPEG 没有。所以：
#   · PNG → 自己插一个 `iTXt` 块（keyword = XML:com.adobe.xmp）
#   · JPEG → 自己插一个 APP1 段
# 两处都要自己算长度和 CRC —— 标准库的 `struct` / `zlib` 够用，
# 为一个 XMP 引第三方库（pyexiv2/piexif）不值得，而它们在 Windows
# 上还要编 C 扩展。

EXIF_IMAGE_DESCRIPTION = 0x010E
"""EXIF `ImageDescription`。几乎所有看图工具都会显示它 ——
这是「显式标识」之外最容易被看见的一处隐式标识。"""

EXIF_USER_COMMENT = 0x9286
"""EXIF `UserComment`。它比 `ImageDescription` 长，且带字符集前缀，
所以中文放这里不会变成乱码。"""

XMP_KEYWORD = "XML:com.adobe.xmp"
"""XMP 在 PNG 里的 `iTXt` 关键字。**这个字符串是 Adobe 规范定的**，
不是我们起的名字 —— 改一个字符，所有工具都读不到。"""

XMP_JPEG_APP1_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
"""JPEG 的 APP1 段里，XMP 包前面必须顶这串标识符（含结尾的 NUL）。"""

# Pillow 的 `format` 名 → 我们支持写标识的容器。
# 【为什么是一个白名单而不是「能存就存」】因为写不进去的格式
# （GIF / BMP 没有 EXIF 也没有 XMP）**必须响亮地失败** ——
# 静默放行等于发布一份没有标识的 AI 产物，那是合规问题，不是显示问题。
#
# ⚠️ `_detect_container()` 返回的**必须是这一套名字**（有测试钉着）。
#    两处各写一份字符串的下场是：白名单里有 "WEBP" 而探测那边回 "WebP"，
#    于是白名单形同虚设，而两边都不报错。
_MARKABLE_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

# ── 魔数（拼接路径按它认容器，不借 Pillow）────────────────
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8"
_WEBP_RIFF = b"RIFF"
_WEBP_TAG = b"WEBP"

# JPEG 的 APP1 里 EXIF 段的标识头。**PNG 的 `eXIf` 块没有它** ——
# 同一个 EXIF 载荷在两种容器里差这 6 个字节，是本节最容易搞错的地方。
_EXIF_PREFIX = b"Exif\x00\x00"
_EXIF_PREFIX_LEN = len(_EXIF_PREFIX)

# PNG 的 `iTXt` 里，XMP 那一条的关键字（含结尾 NUL），用来认旧块。
_PNG_XMP_KEYWORD_BYTES = XMP_KEYWORD.encode("latin-1") + b"\x00"


def _exif_user_comment(text: str) -> bytes:
    """`UserComment` 的字节形态：**8 字节字符集前缀 + 正文**。

    【为什么不能直接把字符串塞进去】EXIF 规范给 `UserComment` 留了
    前 8 个字节标明字符集（`ASCII\\0\\0\\0` / `UNICODE\\0` / `JIS\\0\\0…`）。
    不写前缀的话，读的一方会按自己的默认假设去解 —— 中文就变成乱码。
    `UNICODE\\0` 表示「后面是 UTF-16」，并且规范规定**大端**。
    """
    return b"UNICODE\x00" + text.encode("utf-16-be")


def _decode_user_comment(raw: object) -> str | None:
    """`UserComment` 的字节 → 字符串。**读不回来就返回 None。**"""
    if not isinstance(raw, bytes):
        return str(raw) if raw else None
    body = raw[8:] if raw[:8] == b"UNICODE\x00" else raw
    try:
        return body.decode("utf-16-be" if raw[:8] == b"UNICODE\x00" else "utf-8")
    except UnicodeDecodeError:
        return None


def _exif_bytes(description: str, user_comment: str) -> bytes:
    """造一份 EXIF。返回值**带 `Exif\\0\\0` 前缀**（JPEG 的 APP1 直接用）。

    ─────────────────────────────────────────────────────────
    【为什么不走 `Image.open(path).getexif()` 那条路】

    因为那要先**打开整张图**（Pillow 一 `open` 就建好 image 对象、
    读文件头、准备解码），而这里根本不需要一个像素 ——
    我们只是往文件里插几十个字节。转存里这是**每条产物都走一次**的路径，
    差别是「毫秒」和「几十毫秒」，一张 4096×4096 的图更明显。
    而标 B6 正在做的事就是把大件 IO 挪出数据库事务 ——
    在这里白花掉的时间，正是那边想省下来的。

    【`Exif.tobytes()` 到底吐不吐前缀】吐。实测开头是
    `b"Exif\\x00\\x00MM\\x00*"`（`MM` = 大端 TIFF）。
    所以 JPEG 的 APP1 **原样**用它（APP1 的头就是这 6 个字节），
    而 PNG 的 `eXIf` 块要**去掉**这 6 个（那个块装裸 TIFF）——
    同一个东西在两种容器里差 6 个字节，是这一节最容易搞错的地方。
    ─────────────────────────────────────────────────────────
    """
    exif = Image.Exif()
    exif[EXIF_IMAGE_DESCRIPTION] = description
    exif[EXIF_USER_COMMENT] = _exif_user_comment(user_comment)
    return exif.tobytes()


def _detect_container(raw: bytes) -> str | None:
    """按**魔数**认出容器，返回的名字与 `_MARKABLE_IMAGE_FORMATS` 同一套。

    【为什么不用 `Image.open` 认】因为拼接路径上根本不需要解码，
    而 `Image.open` 会为一个「只是想插几个字节」的动作付出解码准备的成本。
    另外它会**抛异常**而不是返回 None（见 `read_implicit_marker` 里踩过的那个坑）。
    """
    if raw.startswith(_PNG_MAGIC):
        return "PNG"
    if raw.startswith(_JPEG_SOI):
        return "JPEG"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    """一个完整的 PNG 块：长度 + 类型 + 数据 + **CRC（算的是类型+数据）**。

    【CRC 为什么容易写错】PNG 规范的 CRC 覆盖的是「类型 + 数据」，
    **不含长度字段**。只算数据的话，写出来的文件在自己这里读得通
    （Pillow 宽容），而在严格解码器上直接损坏 —— 而它看起来是
    「这张图在某些软件里打不开」，很难联想到 CRC。
    """
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def _split_png_chunks(raw: bytes, start: int) -> list[tuple[bytes, bytes]]:
    """把 PNG 从 `start` 起的块拆成 `[(类型, 数据)]`，**并校验每个 CRC**。

    【为什么要拆一遍，而不是插完就走】因为这里动的是**用户的成片**，
    而 PNG 的损坏有一个很难查的表现：宽容的解码器（Pillow 就是）
    会跳过 CRC 不对的块照常显示，于是「我们这边看着好好的，
    用户那边某个软件说文件损坏」。拆一遍顺带把 CRC 全验了 ——
    自己写坏的块在这一步当场露馅，而不是等交付出去。

    （校验的代价是扫一遍字节，几十 KB 的量级，可以忽略。）
    """
    chunks: list[tuple[bytes, bytes]] = []
    pos = start
    while pos + 12 <= len(raw):
        (length,) = struct.unpack(">I", raw[pos : pos + 4])
        ctype = raw[pos + 4 : pos + 8]
        data = raw[pos + 8 : pos + 8 + length]
        if len(data) != length:
            raise TranscodeError(f"PNG 的 {ctype!r} 块被截断（文件不完整）")
        (crc,) = struct.unpack(">I", raw[pos + 8 + length : pos + 12 + length])
        if crc != (zlib.crc32(ctype + data) & 0xFFFFFFFF):
            raise TranscodeError(f"PNG 的 {ctype!r} 块 CRC 对不上（源文件已损坏）")
        chunks.append((ctype, data))
        pos += 12 + length
        if ctype == b"IEND":
            break
    return chunks


def _png_itxt(keyword: str, text: bytes) -> bytes:
    """`iTXt` 块的正文：keyword + 压缩标志 + 压缩方法 + 语言 + 译名 + 正文。

    压缩标志/方法取 0 = **不压缩**：XMP 包本来就只有几百字节，
    压它省不下什么，却让「用十六进制编辑器找标识」变得不可能 ——
    而「能被人眼直接看到」本身就是隐式标识的一部分价值。
    """
    return (
        keyword.encode("latin-1")
        + b"\x00"
        + b"\x00\x00"
        + b"\x00"
        + b"\x00"
        + text
    )


def _insert_png_metadata(raw: bytes, exif_bytes: bytes, xmp: bytes) -> bytes:
    """在 IHDR **之后**插 `eXIf` + `iTXt` 两个块，并去掉**旧的**同名块。

    【为什么紧挨着 IHDR】PNG 规范要求 IHDR 必须是第一个块，其余的
    元数据块**必须在 IDAT 之前**。插在 IHDR 后面是唯一稳妥的位置。

    【为什么要去掉旧的同名块】留着就是我们写一份、原来的也还在，
    而读者只认**先出现**的那一份 —— 顺序一乱，别人读到的就是旧值。
    这不是洁癖：转存是**幂等重跑**的（同一个 task_id 可能标两次），
    不去重的话第二次就会往文件里堆第二份 XMP。
    """
    if not raw.startswith(_PNG_MAGIC):
        raise TranscodeError("要写标识的不是 PNG")
    (ihdr_len,) = struct.unpack(">I", raw[8:12])
    after_ihdr = 8 + 12 + ihdr_len

    kept: list[bytes] = []
    for ctype, data in _split_png_chunks(raw, after_ihdr):
        if ctype == b"eXIf":
            continue
        if ctype == b"iTXt" and data.startswith(_PNG_XMP_KEYWORD_BYTES):
            continue
        kept.append(_png_chunk(ctype, data))

    fresh = b"".join(
        (
            # PNG 的 `eXIf` 装**裸 TIFF**，去掉 `Exif\0\0`（见 `_exif_bytes`）。
            _png_chunk(b"eXIf", exif_bytes[_EXIF_PREFIX_LEN:]),
            _png_chunk(b"iTXt", _png_itxt(XMP_KEYWORD, xmp)),
        )
    )
    return raw[:after_ihdr] + fresh + b"".join(kept)


def _jpeg_segments(raw: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
    """拆出 SOI 之后、SOS 之前的所有段。返回 `(段列表, 从 SOS 起的原样字节)`。

    【为什么到 SOS 就停】JPEG 是「段 + 熵编码数据」两截。段都有长度字段
    可以安全地跳过，而 SOS 之后是压缩数据 —— 在那里按 0xFF 找标记
    会被数据里合法的 0xFF 骗到（必须看填充字节才知道它是不是真标记）。
    所以我们**只动 SOS 之前的部分**，后面的字节原样搬走。
    【为什么长度越界要抛】段长度是 2 字节且来自文件本身；一个越界的长度
    要么是文件被截断，要么是我们把某个无长度字段的标记当成了有长度的。
    两种情况下继续往下拆都只会拆出一个更坏的文件。
    """
    if not raw.startswith(_JPEG_SOI):
        raise TranscodeError("要写标识的不是 JPEG")
    segs: list[tuple[int, bytes]] = []
    pos = 2
    while pos + 4 <= len(raw):
        if raw[pos] != 0xFF:
            break
        marker = raw[pos + 1]
        if marker == 0xFF:  # 填充字节，跳过
            pos += 1
            continue
        if marker == 0xDA:  # SOS
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:  # 无长度字段的标记
            pos += 2
            continue
        (length,) = struct.unpack(">H", raw[pos + 2 : pos + 4])
        if length < 2 or pos + 2 + length > len(raw):
            raise TranscodeError("JPEG 的段长度越界（文件不完整或已损坏）")
        segs.append((marker, raw[pos + 4 : pos + 2 + length]))
        pos += 2 + length
    return segs, raw[pos:]


def _insert_jpeg_metadata(raw: bytes, exif_bytes: bytes, xmp: bytes) -> bytes:
    """插两个 APP1 段（EXIF 与 XMP），并去掉**旧的**同名段。

    【为什么插在 APP0 之后】JFIF 规范要求 APP0 是 SOI 之后的第一个段。
    插在它前面的话，认死规矩的解码器会判这个文件「不是 JFIF」。
    没有 APP0 的文件（Exif 直出）就贴在 SOI 后面。

    【为什么长度要判断】APP1 的长度字段是 2 字节，上限 65535（含它自己）。
    超过就得用扩展 XMP（多段），而我们写的是一个几百字节的最小包 ——
    真撞上这条说明标识内容失控了，该失败而不是写一个解析器读不了的段。
    """
    segs, tail = _jpeg_segments(raw)
    xmp_payload = XMP_JPEG_APP1_HEADER + xmp
    for payload in (exif_bytes, xmp_payload):
        if len(payload) + 2 > 0xFFFF:
            raise TranscodeError(f"JPEG 的 APP1 段放不下（{len(payload)} 字节）")

    kept: list[tuple[int, bytes]] = []
    for marker, payload in segs:
        if marker == 0xE1 and (
            payload.startswith(_EXIF_PREFIX) or payload.startswith(XMP_JPEG_APP1_HEADER)
        ):
            continue  # 旧的 EXIF / XMP，去掉（理由同 PNG 的去重）
        kept.append((marker, payload))

    insert_at = 0
    for idx, (marker, _) in enumerate(kept):
        if marker == 0xE0:  # JFIF 的 APP0
            insert_at = idx + 1
            break

    ordered = kept[:insert_at] + [(0xE1, exif_bytes), (0xE1, xmp_payload)] + kept[insert_at:]
    out = [raw[:2]]
    for marker, payload in ordered:
        out.append(b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload)
    out.append(tail)
    return b"".join(out)


def _mark_webp(path: Path, exif_bytes: bytes, xmp: bytes) -> bytes:
    """WebP：**只能**借 Pillow 重写，所以必须 `lossless=True`。

    ─────────────────────────────────────────────────────────
    【为什么要在这里写下一段「重编码」—— 和上面两个容器不一致】

    因为 WebP 是 RIFF 容器，往里加 `EXIF` / `XMP ` 块**不是插一段就算**：
    规范要求这类文件先有一个 `VP8X` 块并在它的标志位里声明「本文件含
    EXIF / XMP」。没有 VP8X 的简单 WebP 得先**合成**一个，而 VP8X 里
    要填画布尺寸等字段（得从 VP8 / VP8L 的码流里抠）。
    为 JPEG/PNG 做字节拼接是十几行；为 WebP 做同样的东西是另一个量级，
    而它服务的是一个 v1 里没有 provider 产出的格式。

    【那为什么不用 `quality=95` 之类的「高质量重编码」了事】
    因为**任何**有损重编码都是在用户花钱买的图上再压一遍。
    实测：512×512 的图按 Pillow 默认质量重存一次，
    PSNR 只有 **32.9 dB**（肉眼可见），文件还缩了 36% —— 那就是
    悄悄降质。`lossless=True` 的代价是体积（同样条件下约 3 倍），
    但换来**逐像素相同**。取舍很明确：**宁可文件大，不动用户的像素。**

    【真接上只出 WebP 的 provider 时该做什么】
    按上面说的补 VP8X 标志位 + 拼 RIFF 块，把那 3 倍体积省掉。
    这是一条记在案的缺口，不是没想到。
    ─────────────────────────────────────────────────────────
    """
    with Image.open(path) as img:
        if (img.format or "") != "WEBP":
            raise TranscodeError(f"要写标识的不是 WebP（读到的是 {img.format or '未知'}）")
        buf = io.BytesIO()
        # ⚠️ `lossless=True` 不是优化选项，是这个函数的**正确性前提**。
        #    去掉它 = 悄悄按默认质量重压用户的图（实测 32.9 dB）。
        img.save(buf, format="WEBP", exif=exif_bytes, xmp=xmp, lossless=True)
        return buf.getvalue()


def write_image_marker(
    path: Path,
    *,
    description: str,
    user_comment: str,
    xmp: bytes,
) -> None:
    """就地给一张图写隐式标识：EXIF 两条 + 一个 XMP 包。

    ─────────────────────────────────────────────────────────
    【PNG / JPEG：拼容器字节，**不重编码**】

    这是本函数唯一的设计要点，也是最容易走偏的一步。

    「打开图片 → 设 EXIF → 存回去」看起来是最省事的做法，代码也短。
    但它会**重新编码像素**，而收益是零 —— 我们要加的只是几十个字节的
    元数据，和图像数据一点关系都没有。代价实测如下（512×512 的有细节图，
    对着 provider 原图算 PSNR）：

      · JPEG，Pillow `quality="keep"`（保住原量化表）…… **35.05 dB**
      · WebP，Pillow 默认质量 …………………………… **32.91 dB**（缩了 36% 体积）
      · PNG（无损格式，重存不吃亏）…………………… **inf**（逐字节相同）

    35 dB 不是「无损」。`quality="keep"` 保住了量化表，但 Pillow 的
    IDCT→FDCT 往返**不是恒等**，系数会在舍入上漂一格。也就是说
    上面那条路在**每一张** JPEG 交付物上都掉一代画质 —— 而用户是花
    4 积分买的这张图。所以 JPEG 也必须拼字节。

    拼字节的额外好处：**provider 原本附在产物上的其它元数据全都留着**
    （只替换我们写的那两条 + XMP）。重存那条路会把它们全丢掉。

    ─────────────────────────────────────────────────────────
    【为什么要写中间文件 + `os.replace`】

    因为它是**就地**改一个已经落盘的 provider 产物。直接往上写的话，
    中途失败会留下一张**半个文件**的图 —— 而它的大小和扩展名都是对的，
    于是会被当成正常产物收下。

    【为什么格式不在白名单里就抛】
    见 `_MARKABLE_IMAGE_FORMATS` 那段：写不进去的格式必须响亮地失败，
    否则就是发布一份没有标识的 AI 产物。
    ─────────────────────────────────────────────────────────
    """
    # ⚠️⚠️ `ImageDescription` 是 **ASCII 型**的 EXIF 标签（type = 2），
    #      而 Pillow **不会为此报错** —— 它把每个非 ASCII 字符换成 `?`
    #      然后照常存盘。实测：写 "AI 生成 · smoke" 进去，读回来是
    #      "AI ?? ? smoke"。所以这道闸必须自己设。
    #
    #      这是本项目最阴的一类失败：**写成功、读成功、内容是坏的** ——
    #      没有异常、没有日志、文件大小也对，而「标识里到底写着什么」
    #      要到有人真去读的那一刻才暴露。
    #
    #      中文不是写不进去，是**不能走这个字段**：`UserComment`
    #      （UNDEFINED 型 + UTF-16-BE）和 XMP（UTF-8）都装得下中文，
    #      见 `_exif_user_comment` 与 `marking.marker_text_ascii`。
    #      同一个 EXIF 里，标签的**类型**决定了它能装什么，别搞混。
    if not description.isascii():
        raise TranscodeError(
            "EXIF ImageDescription 只接受 ASCII（非 ASCII 会被 Pillow 静默换成 '?'）；"
            "中文请走 UserComment / XMP，这个字段用 marking.marker_text_ascii() 生成"
        )

    # ── 原图尺寸：**只读文件头**，不解码 ──────────────────
    # 【为什么还要问一次 Pillow】因为收尾的自检要保证「尺寸没变」，
    # 得先有基准值。`Image.open` 不 `.load()` 就只读文件头 ——
    # 拿一张 4096×4096 的图量过：不解码是几毫秒的量级。
    with Image.open(path) as img:
        width, height = img.size

    raw = path.read_bytes()
    container = _detect_container(raw)
    if container is None:
        raise TranscodeError("不支持的文件格式：认不出这是 PNG / JPEG 还是 WebP")

    exif_bytes = _exif_bytes(description, user_comment)
    if container == "PNG":
        patched = _insert_png_metadata(raw, exif_bytes, xmp)
    elif container == "JPEG":
        patched = _insert_jpeg_metadata(raw, exif_bytes, xmp)
    else:
        patched = _mark_webp(path, exif_bytes, xmp)

    # ── 自检：尺寸与格式不许变 ────────────────────────────
    # 【为什么写完还要再看一眼】标识是**就地**改文件，而「改坏了」
    # 的表现是用户的作品打不开 —— 那是最贵的一类失败。这一步很便宜
    # （只读文件头），D4 的验收也依赖它：尺寸必须维持契约值
    # （1024×1024 / 1280×720），而作品网格按它算格子高度。
    #
    # ⚠️ 它**挡不住**「Pillow 读得通、严格解码器读不通」那一类
    #    （PNG 的 CRC 错就是这样）。所以 PNG 那条路径在拼接时
    #    已经逐块验过 CRC，见 `_split_png_chunks`。
    tmp = path.with_name(f".mark-{path.name}")
    try:
        tmp.write_bytes(patched)
        probe = probe_image(tmp)
        if not probe.ok or probe.width != width or probe.height != height:
            raise TranscodeError(
                f"写标识之后图片对不上（{probe.width}×{probe.height}，原为 {width}×{height}）"
            )
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def remux_with_tags(
    source: Path,
    dest: Path,
    tags: dict[str, str],
    *,
    timeout: float | None = None,
) -> None:
    """给一段视频写 MP4 元数据（**`-c copy`，不重编码**）。

    ─────────────────────────────────────────────────────────
    【为什么必须 `-c copy`】重编码一段 720P 视频要几十秒到几分钟，
    而我们要写的只是几个字符串。`-c copy` 只搬容器层，
    代价是「原样的码流 + 新的元数据」。

    【为什么要 `use_metadata_tags`】MOV/MP4 的原生「原子」只认少数几个
    键（title / comment / description 在列表里）。自定义键默认会被
    **静默丢掉** —— ffmpeg 不报错、退出码是 0、文件也生成了，
    只是那条元数据不在。`use_metadata_tags` 让它为陌生的键写
    `----` 原子。这一条是「标识写没写进去」最容易踩空的坑。

    【为什么 `faststart` 和它写在同一个 `-movflags` 里】
    分开写两次的话，**后一个覆盖前一个**（`-movflags` 不是累加的）——
    表现是「视频能播，但网页上要等整段下载完」。

    【为什么必须显式写 `-f mp4` —— 这一条是踩出来的】

    ffmpeg 默认**从输出文件的扩展名推断容器**。而转存流水线里的
    暂存文件名是固定的 `artifact`（**没有扩展名**，见
    `transfer.staging_dir` 的用法），我们要写的中间文件于是成了
    `.mark-artifact` —— ffmpeg 认不出它该写成什么，直接失败：

        Error opening output file ./.mark-artifact.
        Error opening output files: Invalid argument        （退出码 -22）

    这个失败只在**真实转存路径**上出现：单测里那个文件叫 `x.mp4`，
    有扩展名，所以怎么试都是绿的。所以别把 `-f mp4` 当成冗余 ——
    它是让这个函数不依赖调用方文件名的一部分。
    ─────────────────────────────────────────────────────────
    """
    exe = _which("ffmpeg")
    if exe is None:
        raise TranscodeError("找不到 ffmpeg（依赖闸门里那一项应该是红的）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        exe,
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-c",
        "copy",
        "-movflags",
        "+faststart+use_metadata_tags",
    ]
    for key, value in tags.items():
        argv += ["-metadata", f"{key}={value}"]
    # 见 docstring 里那段：**不靠扩展名**，显式钉死容器。
    argv += ["-f", "mp4", str(dest)]
    try:
        proc = _run(argv, timeout=timeout or _timeout())
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"ffmpeg 写元数据超时（{timeout or _timeout()} 秒）") from exc
    except OSError as exc:
        raise TranscodeError(f"ffmpeg 启动失败：{exc.strerror or exc}") from exc

    if proc.returncode != 0 or not dest.is_file():
        raise TranscodeError(
            f"ffmpeg 写元数据失败（{proc.returncode}）：{proc.stderr.strip()[-200:]}"
        )


def probe_video_tags(path: Path) -> dict[str, str] | None:
    """读一段视频的容器级元数据。**失败返回 None，绝不抛。**

    【为什么键要统一成小写】MP4 的原生原子是 `©cmt` / `desc` 这种，
    ffprobe 报出来的名字在各版本间不统一（`comment` / `©cmt`）。
    读的一方（测试、验收脚本）只关心「comment 写没写进去」，
    不该被原子名绊住。
    """
    exe = _which("ffprobe")
    if exe is None:
        return None
    argv = [
        exe,
        "-v",
        "error",
        "-show_entries",
        "format_tags",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = _run(argv, timeout=_timeout())
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None

    try:
        data = json.loads(proc.stdout or "{}")
        raw_tags = ((data.get("format") or {}).get("tags")) or {}
        tags: dict[str, str] = {}
        for key, value in raw_tags.items():
            # `©cmt` → `cmt`，`comment` → `comment`。两种都归到
            # 去掉前导非字母字符后的小写名。
            tags[key.lstrip("\xa9©").lower()] = str(value)
        # 常见原子名的对照。**只映射我们真的会写的那几个**：
        # 一张大表会让人以为 `probe_video_tags` 是个通用 API。
        for atom, canonical in (("cmt", "comment"), ("desc", "description")):
            if atom in tags and canonical not in tags:
                tags[canonical] = tags[atom]
        return tags
    except (ValueError, TypeError, AttributeError):
        return None


def read_implicit_marker(path: Path) -> dict[str, str | None]:
    """读回一份产物的隐式标识。**测试与验收用。**

    【为什么它住在 transcode 里】因为它要摸 EXIF（Pillow）和容器
    元数据（ffprobe），而这两个东西不许出现在这个文件之外。
    「读回来」这件事在验收里是**核心断言** —— 只写不读的话，
    「标识写进去了」永远是实现自己说的。

    【为什么不能「先试 Pillow，认不出就当视频」】
    因为 `Image.open` 对认不出的文件是**抛异常**，不是返回 None。
    一段 MP4 撞进去会得到 `UnidentifiedImageError` —— 于是这个函数
    对视频产物直接崩，而它是验收里唯一的读路径（冒烟测试里就是这么
    炸的）。所以要**显式**接住那个异常，再落到视频分支去。
    """
    try:
        with Image.open(path) as img:
            fmt = img.format or ""
            if fmt in _MARKABLE_IMAGE_FORMATS:
                exif = img.getexif()
                xmp = img.info.get("xmp")
                return {
                    "format": fmt,
                    "ImageDescription": _as_text(exif.get(EXIF_IMAGE_DESCRIPTION)),
                    "UserComment": _decode_user_comment(exif.get(EXIF_USER_COMMENT)),
                    "xmp": xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else xmp,
                }
            # 认得出是图片、但我们不标的格式（GIF / TIFF / …）。
            # 字段全 None 就是**诚实的答案**：这个容器里不会有我们的标识。
            return {
                "format": fmt or "image",
                "ImageDescription": None,
                "UserComment": None,
                "xmp": None,
            }
    except (UnidentifiedImageError, OSError):
        # `OSError` 一起接住：Pillow 对「文件头对但内容截断」会抛
        # `OSError`（不是 UnidentifiedImageError），而一段损坏的产物
        # 同样是「交给视频分支去看」比「在这里崩」有用。
        pass

    tags = probe_video_tags(path) or {}
    return {
        "format": "video",
        "title": tags.get("title"),
        "comment": tags.get("comment"),
        "description": tags.get("description"),
        "xmp": None,
    }


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


# ══════════════════════════════════════════════════════════════
# 像素 / 码流指纹 —— **测试与验收用**（同 `read_implicit_marker` 的理由）
# ══════════════════════════════════════════════════════════════


def image_digest(path: Path) -> str:
    """一张图的**像素指纹**（解码成 RGB 之后的 sha256）。

    ─────────────────────────────────────────────────────────
    【为什么需要它，而不是比对文件字节】

    因为标识是**写进容器**的 —— 文件的字节**一定**会变，那正是我们要
    的结果。所以「改动了没有」在文件层没有意义，有意义的问题是
    「**像素**改动了没有」，而它只能解码之后才回答得了。

    这个问题在 B5 是**核心**：写标识最简单的那条路（打开图片 →
    设 EXIF → 存回去）会把每一张 JPEG 掉一代画质（实测 35.05 dB），
    而用户是花积分买的这张图。所以最终实现改成了拼容器字节、
    不动像素 —— 而**一个不做任何断言的实现看起来和它一模一样**。
    这个函数就是让那句话变成可断言的。

    【为什么它能住在 `transcode.py`】因为它要解码，而 Pillow 的
    调用点只允许在这一个文件里（见文件头）。测试自己 `import PIL`
    的话，那条规矩第一个被违反的地方就是测试。
    ─────────────────────────────────────────────────────────
    """
    with Image.open(path) as img:
        # `convert("RGB")` 先统一形态：JPEG 是 YCbCr、PNG 可能是
        # 调色板或 RGBA，直接比 `tobytes()` 会拿三件不同的东西互相比。
        return hashlib.sha256(img.convert("RGB").tobytes()).hexdigest()


def video_stream_digest(path: Path) -> str | None:
    """一段视频的**码流指纹**（`-c copy` 之后算 md5）。**失败返回 None。**

    ─────────────────────────────────────────────────────────
    【为什么视频要另算一个，而不是像图片那样比像素】

    因为视频那条路写的是 `-c copy` —— **不重编码**，只搬容器。
    那段码流是 H.264/H.265，逐帧解码再比对要几十秒，而「有没有
    重新编码」在**编码后的字节**上直接就能看出来：`-c copy` 出来的
    码流和原文件**逐字节相同**，重编码出来的则一定不同。

    所以这个指纹比图片那个还硬：它不是「解码后相同」，
    而是「字节相同」。

    【为什么用 `-f md5` 而不是把码流拉进内存】一段 720P 视频的码流
    是几十 MB，而 `-f md5` 让 ffmpeg 自己边搬边算，一个字节都不用
    进 Python 进程。
    ─────────────────────────────────────────────────────────
    """
    exe = _which("ffmpeg")
    if exe is None:
        return None
    argv = [
        exe,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-c",
        "copy",
        "-f",
        "md5",
        "-",
    ]
    try:
        proc = _run(argv, timeout=_timeout())
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # ffmpeg 把结果打成一行 `MD5=<hex>`。
    return (proc.stdout or "").strip().splitlines()[-1] if proc.stdout.strip() else None
