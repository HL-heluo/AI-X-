"""Pillow 探针与 ffmpeg 抽帧 —— §9.4 / §11.2 的尺寸与封面。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件测的是「不可信字节 → 我们知道形状的东西」那一段】

它的两条主线：

  1. **探针只读文件头，却必须挡住炸弹。** 一张 68 字节的 PNG 可以
     声称自己 6 万 × 6 万（见 `_helpers.mini_png`）。「解不出就收」
     这条宽松口径**不能**把这种情况一起收进来，否则它就从
     「用户随手传了个非图片」变成了一个内存炸弹的入口。

  2. **封面尺寸是契约值（1280×720）。** 前端作品网格按
     `width/height` 算每格高度（`work_grid.dart:109-124`），
     封面的比例一变，列表布局就错了 —— 那不是「图不好看」。

【为什么这个文件不 skip「没有 ffmpeg」的情况】
因为 ffmpeg 是**硬依赖**：`scripts/check_deps.py` 的 15 项里有一项
就是它，B4 的 fake provider 也靠它造真产物。一台没装 ffmpeg 的机器
上，这个仓库本来就跑不起来 —— 用 skip 把它藏起来，等于让
「pytest 全绿但产物是空的」变成一种可能。所以下面直接用。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import mini_png, real_png
from app.services import transcode
from app.services.transcode import (
    COVER_HEIGHT,
    COVER_WIDTH,
    ImageProbeStatus,
    TranscodeError,
    extract_cover,
    ffmpeg_available,
    placeholder_cover,
    probe_image,
    probe_video,
    render_image,
    synthesize_video,
)


@pytest.fixture(autouse=True)
def _ffmpeg_is_there() -> None:
    """把「ffmpeg 不在」变成一句说得清的红，而不是一堆看不懂的绿。

    【为什么是断言而不是 skip】见文件头。这条断言失败时的第一句话
    就是「跑 `python scripts/check_deps.py` 看第 15 项」——
    它是**环境问题**，不该表现为某个用例里的一个 TranscodeError。
    """
    assert ffmpeg_available(), (
        "ffmpeg / ffprobe 不在 PATH 上。先跑 `python scripts/check_deps.py` —— "
        "它有一项专门盯着这件事（B4 的产物、封面都靠它）。"
    )


# ══════════════════════════════════════════════════════════════
# 图像探针：三种结论必须分得开
# ══════════════════════════════════════════════════════════════


def test_真图能读出尺寸和格式() -> None:
    """探针读的是**声明尺寸**，但它必须与真图一致 —— 否则后面全是错的。"""
    info = probe_image(real_png(1024, 1024))

    assert info.status is ImageProbeStatus.ok
    assert (info.width, info.height) == (1024, 1024)
    assert info.mime == "image/png"


def test_探针也接受一个路径(tmp_path: Path) -> None:
    """上传那条路给的是**临时文件**，不是 bytes（20MB 不进内存）。"""
    dest = tmp_path / "a.png"
    render_image(300, 200, (1, 2, 3), dest)

    assert probe_image(dest).width == 300


def test_非图片字节_解不出_但不算超限() -> None:
    """⚠️ 这就是**用户拍板的那条口径**，用一条用例钉住它。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么「不是图片」要照收，而不是拒绝】

    冻结前端的契约测试上传的参考图就是 `List<int>.filled(1024, 0)`
    —— 1024 个 NUL（`test/live_backend.dart:772`、
    `test/repository_layer_test.dart:194,297`）。严格校验会让跨仓门禁
    变红，而那个红来自**夹具**，不来自契约。

    【它的代价记在案】对非图片文件，§9.4 的「≤4096×4096」不执行 ——
    因为没有尺寸可查。见 HANDOFF 的缺口表。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    assert probe_image(b"\x00" * 1024).status is ImageProbeStatus.undecodable


def test_截断的png_解不出() -> None:
    """只有签名和前几个字节（传输断在中间）。

    【为什么它和上一条是两条用例】它们的**病因**不同（一个是
    「根本不是图」，一个是「是图但没传完」），而实现里接的是
    两组不同的异常（`UnidentifiedImageError` vs `OSError`）。
    合并成一条的话，删掉其中一个 except 分支不会有任何用例变红。
    """
    assert probe_image(b"\x89PNG\r\n\x1a\n\x00\x00").status is ImageProbeStatus.undecodable


def test_声称边长超限的迷你png_判超限() -> None:
    """⚠️ 本文件最重要的一条：**「解不出就收」不能吞掉炸弹。**

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这一条必须存在】

    宽松口径有一个很显然的滥用方式：**把一张 20MB 以内的
    「声明 6 万 × 6 万」的图伪装成「解不出来」**。那时如果我们照收，
    它会被存下来、发布出去，然后在**任何一次**后续解码里炸掉
    某个进程（今天是没人解它，明天「生成缩略图」这类需求一上来就有了）。

    所以结论要按**原因**分：

      · 「是图，但读不出尺寸」→ 收（数据坏了/太短）
      · 「读得出尺寸，但太大了」→ 拒（`too_large`）
      · 「不是图」        → 收（用户的锅，不是我们的内存）

    这两个 68 字节的样本分别走**两条不同的代码路径**：
    5000×5000 落在「边长比较」上，60000×60000 落在 Pillow 的
    炸弹保护（`DecompressionBombError`）上。删掉任何一条都会红。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    by_side = probe_image(mini_png(5000, 5000))
    assert by_side.status is ImageProbeStatus.too_large
    assert (by_side.width, by_side.height) == (5000, 5000), "尺寸要能报出来，好让错误信息说得清"

    by_bomb = probe_image(mini_png(60000, 60000))
    assert by_bomb.status is ImageProbeStatus.too_large


def test_正好到边长上限的图能过() -> None:
    """边界是**含**的（`> max_upload_side` 才拒），与 20MB 那条同款。"""
    info = probe_image(mini_png(4096, 4096))

    assert info.status is ImageProbeStatus.ok


def test_能开但不是我们要的格式_算解不出() -> None:
    """TIFF 这类：开得出、也有尺寸，但不是契约里的那几种 mime。

    【为什么归到「解不出」而不是「拒」】它不是炸弹、也不是伪装，
    用户拿它当参考图只是没用而已。拒它需要一条**契约里没有的错误码**，
    而那会把一次无害的上传变成一次报错。
    """
    # ⚠️ 这里是**测试目录里唯一的**一处直接 `import PIL`。
    # 规矩（「Pillow 的调用点只有 transcode.py」）管的是**产品代码**；
    # 而这条用例要测的恰恰是「一种我们不认识、也不打算支持的格式」，
    # 所以它必须自己造一个 —— 造不出来就没法测这个分支。
    # 好在这张图不会被当成产物：它只在这条用例里活一次。
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (5, 5, 5)).save(buffer, format="TIFF")

    info = probe_image(buffer.getvalue())

    assert info.status is ImageProbeStatus.undecodable
    assert (info.width, info.height) == (16, 16), "尺寸读得出就该记下来（可诊断）"


# ══════════════════════════════════════════════════════════════
# ffmpeg：抽帧、量尺寸、合成、占位
# ══════════════════════════════════════════════════════════════


def test_合成出来的视频能探出尺寸和时长(tmp_path: Path) -> None:
    """`probe_video` 是「产物规格里的宽高从哪来」的答案。"""
    video = tmp_path / "v.mp4"
    synthesize_video(video, width=1280, height=720, duration_sec=1, color=(10, 20, 30))

    info = probe_video(video)

    assert info is not None, "ffprobe 量不出自己刚合成的视频，说明调用方式有问题"
    assert (info.width, info.height) == (1280, 720)
    assert info.duration_sec is not None and 0.5 <= info.duration_sec <= 2.0


def test_抽帧出来正好是契约尺寸的jpeg(tmp_path: Path) -> None:
    """封面 = 1280×720 JPEG，**契约值**（与前端 Mock 逐字一致）。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么要抽帧而不是拿第一帧的原尺寸】

    成片的尺寸由 provider 决定。不写 `scale` 的话封面就是源尺寸，
    而 `assets.thumbnail` 的 width/height 是契约值 ——
    两者一旦不一致，作品网格里视频格子的高度就和图片格子对不上。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    video = tmp_path / "v.mp4"
    # 故意用**非**契约尺寸的源视频：这样「封面是 1280×720」只可能
    # 来自那条 `-vf scale`，不可能来自「源就是这样」。
    synthesize_video(video, width=640, height=360, duration_sec=1, color=(0, 0, 200))
    cover = tmp_path / "thumb.jpg"

    extract_cover(video, cover)

    info = probe_image(cover)
    assert info.status is ImageProbeStatus.ok
    assert (info.width, info.height) == (COVER_WIDTH, COVER_HEIGHT)
    assert info.mime == "image/jpeg"


def test_抽一个不是视频的文件会抛(tmp_path: Path) -> None:
    """抽帧失败必须抛 `TranscodeError`（调用方靠它决定降级）。"""
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video at all" * 40)

    with pytest.raises(TranscodeError):
        extract_cover(junk, tmp_path / "cover.jpg")


def test_量一个不是视频的文件返回None而不是抛(tmp_path: Path) -> None:
    """`probe_video` 是**加分项**：量不出来就退回默认值，绝不抛。

    【为什么它和 `extract_cover` 的失败策略不一样】
    因为它们的后果不一样：封面是**资产的一行**（拿不到就没有），
    而尺寸是「写进那一行的两个数」（拿不到还能填契约值）。
    为一条诊断信息让整个转存失败，是把不重要的东西放在用户作品前面。
    """
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"nope" * 100)

    assert probe_video(junk) is None


def test_占位封面是契约尺寸的jpeg(tmp_path: Path) -> None:
    """C6 写的降级方案：ffmpeg 不可用时用纯色占位。

    【它为什么必须**成功**】成片已经拿到了，缺的只是一张列表小图。
    为此把用户已付费、也已拿到视频的任务判失败，是把小问题升级成大问题。
    """
    cover = tmp_path / "placeholder.jpg"

    placeholder_cover(cover)

    info = probe_image(cover)
    assert info.status is ImageProbeStatus.ok
    assert (info.width, info.height) == (COVER_WIDTH, COVER_HEIGHT)
    assert info.mime == "image/jpeg"


def test_ffmpeg不在时_可用性判断与失败都是诚实的(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """把 `shutil.which` 换掉，模拟一台没装 ffmpeg 的机器。

    【为什么要能测这个】因为「ffmpeg 不在」这条分支在开发机上
    **永远走不到** —— 而它正是转存层要降级的那个分支
    （`transfer._make_cover`）。用 monkeypatch 把它变成可测的，
    比在一台干净的机器上试要可靠得多。

    ⚠️ 替换的是 `transcode._which`（带 `lru_cache` 的那个），
    不是 `shutil.which` —— 缓存已经装进去的话，改后者不起作用。
    """
    monkeypatch.setattr(transcode, "_which", lambda tool: None)

    assert transcode.ffmpeg_available() is False
    with pytest.raises(TranscodeError):
        extract_cover(tmp_path / "whatever.mp4", tmp_path / "c.jpg")
    with pytest.raises(TranscodeError):
        synthesize_video(
            tmp_path / "v.mp4", width=1280, height=720, duration_sec=1, color=(1, 1, 1)
        )
    assert probe_video(tmp_path / "whatever.mp4") is None
