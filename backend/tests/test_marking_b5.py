"""隐式标识 —— §10.1 的**字节侧**（《人工智能生成合成内容标识办法》）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件要证的不是「写得进去」，而是「没写坏」】

「标识写进去了」这件事，一个**把图重存一遍**的实现也能做到 ——
而那种实现会让每一张 JPEG 掉一代画质（实测 35.05 dB，见
`transcode.write_image_marker` 里那张表），用户是花积分买的这张图。
两种实现在**所有**「字段读得到吗」的断言下都是绿的。

所以本文件里最要紧的一组是「**像素/码流一个字节都没变**」：

  · 图片 —— `transcode.image_digest`（解码成 RGB 后的 sha256）；
  · 视频 —— `transcode.video_stream_digest`（`-c copy` 后的码流 md5）。

第二个比第一个还硬：视频那条路要的是「字节相同」，不是「解码后相同」。

【另一半是「接上了没有」】

`marking.py` 自己全绿、而 `transfer.py` 里那一行被挪走或删掉，
用户拿到的东西**一模一样**（都是没标的产物）。所以最后几条打
真请求，从 `public_url` 把文件捞回来读 —— 只有那一条路能证明
「**存进存储里的那一份**本身带标识」。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from _helpers import new_user, real_png, submit_image
from app.config import get_settings
from app.enums import TaskKind
from app.services import marking
from app.services.transcode import (
    TranscodeError,
    encode_webp,
    image_digest,
    placeholder_cover,
    read_implicit_marker,
    render_image,
    synthesize_video,
    video_stream_digest,
    write_image_marker,
)
from app.services.transfer import TransferFailure, transfer_artifact

# 三种可标记的图片格式。**从实现里读出来**，不在这里手抄
# （同 `test_moderation_b5._SENTINEL` 的理由：手抄的清单会悄悄失真）。
_IMAGE_FORMATS = ("PNG", "JPEG", "WEBP")

_TASK_ID = 4242
"""断言里到处在找的那个数字。写成一个常量，免得某个字符串里的
`task=42` 拼错成 `task= 42` 而没人发现。"""


def _payload(*, kind: str = "text_to_image") -> marking.MarkerPayload:
    return marking.payload_for(task_id=_TASK_ID, kind=kind)


@pytest.fixture
def image_file(tmp_path: Path):
    """按格式造一张**真的**图，返回它的路径。

    【为什么每种格式走不同的生产函数】因为要测的是「标识写进这个
    容器的方式」，而不是「Pillow 能不能存这种格式」。用哪条生产
    路径造它不重要，重要的是它**真的是**这个格式 —— 所以 JPEG
    走 `placeholder_cover`（它固定存 JPEG），WebP 走 `encode_webp`
    （生产里没有 WebP 产物，见那个函数的说明）。
    """

    def _make(fmt: str) -> Path:
        dest = tmp_path / f"src-{fmt.lower()}"
        if fmt == "PNG":
            render_image(64, 48, (11, 22, 33), dest)
        elif fmt == "JPEG":
            placeholder_cover(dest, width=64, height=48)
        elif fmt == "WEBP":
            png = tmp_path / "for-webp"
            render_image(64, 48, (11, 22, 33), png)
            encode_webp(png, dest)
        else:  # pragma: no cover - 参数化里写错格式时立刻炸
            raise AssertionError(f"没有造 {fmt} 的办法")
        assert read_implicit_marker(dest)["format"] == fmt, f"造出来的不是 {fmt}"
        return dest

    return _make


# ══════════════════════════════════════════════════════════════
# 一、像素与码流：标识**不许**碰它们
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("fmt", _IMAGE_FORMATS)
def test_写标识之后像素一个都没变(image_file, fmt: str) -> None:
    """⚠️ B5 最要紧的一条断言。

    ─────────────────────────────────────────────────────────
    【为什么它必须参数化到三种格式】

    因为三种格式的写法**故意不同**：PNG 和 JPEG 拼容器字节（不重编码），
    WebP 让 Pillow 无损重存。少测一种，那一种就可以被人「统一」
    成最省事的那条路（打开 → 设 EXIF → 存回去）而没有任何东西会响。

    【WebP 为什么是唯一会重编码的】拼 RIFF 字节要在 VP8X 里标
    「有 EXIF / 有 XMP」，还要处理三种子块（VP8 / VP8L / VP8X）
    的不同布局 —— 那是 B6 之后可以补的优化，今天用 `lossless=True`
    达到同样的效果（无损）。
    ─────────────────────────────────────────────────────────
    """
    path = image_file(fmt)
    before_pixels = image_digest(path)
    before_size = path.stat().st_size

    marking.apply_marker(path, mime=f"image/{fmt.lower()}", payload=_payload())

    assert image_digest(path) == before_pixels, "标识改到像素了 —— 这一步必须是纯元数据"
    assert path.stat().st_size != before_size, "字节没变说明标识根本没写进去"


def test_视频的码流逐字节没变(tmp_path: Path) -> None:
    """`-c copy` 的验收：**重编码过的码流一定和原来不同**。

    【为什么视频只断言码流、不像图片那样断言解码像素】因为
    视频那条路写的本来就是「原样的码流 + 新的元数据」——
    `-c copy` 让这件事变成可验的（字节相同），
    而逐帧解码再比对要几十秒，换来的是一个**更弱**的结论。
    """
    path = tmp_path / "v.mp4"
    synthesize_video(path, width=320, height=240, duration_sec=2, color=(1, 2, 3))
    before = video_stream_digest(path)
    assert before is not None, "ffmpeg 不可用 —— 依赖闸门那一项应该是红的"

    marking.apply_marker(path, mime="video/mp4", payload=_payload(kind="image_to_video"))

    assert video_stream_digest(path) == before, "写了标识就重编码 = 用户白等几十秒还掉画质"


# ══════════════════════════════════════════════════════════════
# 二、读得回来
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("fmt", _IMAGE_FORMATS)
def test_三种图片格式都读得到那句标识(image_file, fmt: str) -> None:
    path = image_file(fmt)
    marking.apply_marker(path, mime=f"image/{fmt.lower()}", payload=_payload())

    marker = read_implicit_marker(path)

    assert marker["format"] == fmt
    # 完整版（含中文）在 UserComment / XMP 里。
    assert marking.AI_LABEL in (marker["UserComment"] or "")
    assert f"task={_TASK_ID}" in (marker["UserComment"] or "")
    # ASCII 版在最通用的那个 EXIF 字段里。
    assert marking.AI_LABEL_EN in (marker["ImageDescription"] or "")
    assert f"task={_TASK_ID}" in (marker["xmp"] or "")


def test_视频的三个元数据键都写进去了(tmp_path: Path) -> None:
    """`title` / `comment` / `description` 三个都写。

    【为什么要冗余三份】因为 MP4 的原生原子名在各家工具里读法不一
    （`©cmt` / `comment` / `desc`），多一条就多一个读得到的地方 ——
    而「读不到」和「没写」在验收时是同一种表现。
    """
    path = tmp_path / "v.mp4"
    synthesize_video(path, width=320, height=240, duration_sec=2, color=(1, 2, 3))

    marking.apply_marker(path, mime="video/mp4", payload=_payload(kind="image_to_video"))

    marker = read_implicit_marker(path)
    for key in ("title", "comment", "description"):
        assert f"task={_TASK_ID}" in (marker[key] or ""), f"{key} 没写进去"


def test_XMP_是一个合法的_XML_包() -> None:
    """手写的 XML 必须是**良构**的，否则所有工具都读不到它。

    【为什么这值得一条测试】`xmp_packet` 是字符串拼出来的，而它拼的
    内容里有一个来自**配置**的字段（`creator`）。一个 `&` 就能让
    整个包变成非法 XML —— 而症状是「标识读不到」，看起来像没写。
    """
    payload = marking.MarkerPayload(
        task_id=_TASK_ID,
        kind="text_to_image",
        created_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        creator='A & B <"工具">',
    )
    packet = marking.xmp_packet(payload)

    assert packet.startswith(b'<?xpacket begin="\xef\xbb\xbf"'), "少了 xpacket 封装，Adobe 系工具认不出它"
    body = packet.split(b"?>", 1)[1].rsplit(b"<?", 1)[0]
    ET.fromstring(body)  # 不是良构就在这里炸
    assert b"A &amp; B" in packet, "配置里一个 & 就能让整包变非法 XML"


# ══════════════════════════════════════════════════════════════
# 三、那个坑：EXIF 的 ASCII 型字段
# ══════════════════════════════════════════════════════════════


def test_ASCII_字段里绝不出问号(image_file) -> None:
    """⚠️ `ImageDescription` 是 ASCII 型标签，而 Pillow **不报错**。

    实测：写 "AI 生成" 进去，读回来是 "AI ?? "。写成功、读成功、
    文件大小也对 —— 这是本项目最阴的一类失败。

    所以这一条断言的是**那个问号不在**。它比「字段里有 AI-generated」
    更严格：后者在一个被静默替换过的值上**照样成立**（英文那一段
    是 ASCII，替换掉的是中文那一段）。
    """
    path = image_file("PNG")
    marking.apply_marker(path, mime="image/png", payload=_payload())

    description = read_implicit_marker(path)["ImageDescription"]

    assert description, "这个字段必须被写上 —— 它是最通用的那个"
    assert "?" not in description, f"Pillow 把非 ASCII 换成问号了：{description!r}"


def test_写非_ASCII_的_ImageDescription_会响亮地失败(image_file) -> None:
    """把上面那个坑的**守卫**本身钉住。

    `write_image_marker` 在 description 不是纯 ASCII 时抛
    `TranscodeError`。没有这道闸，中文会被静默换成 `?` ——
    所以它是「一个必须存在的失败」。
    """
    path = image_file("PNG")
    with pytest.raises(TranscodeError):
        write_image_marker(path, description="AI 生成", user_comment="x", xmp=b"<x/>")


def test_中文的_creator_在_ASCII_字段里是可逆转义而不是问号() -> None:
    """`marking_creator` 配成中文时，ASCII 字段里的写法。

    【为什么是转义而不是缩写或丢弃】`\\u5373` 是**可逆**的 ——
    看到它的人（或者一段 `decode('unicode_escape')`）能拿回原文。
    换成 `?` 或换成 "provider" 就是不可逆的：信息没了，而且
    看不出来曾经有过。
    """
    payload = marking.MarkerPayload(
        task_id=_TASK_ID,
        kind="text_to_image",
        created_at="2026-01-01T00:00:00+00:00",
        creator="即梦",
    )

    text = marking.marker_text_ascii(payload)

    assert text.isascii()
    assert "\\u5373\\u68a6" in text
    # 完整版必须仍然是中文 —— 转义只发生在 ASCII 那一个字段里。
    assert "即梦" in marking.marker_text(payload)


# ══════════════════════════════════════════════════════════════
# 四、重复标记、探测一致性、不支持的东西
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_重复标记不会叠加(image_file, fmt: str) -> None:
    """拼接路径会先去掉旧的同名块，所以标两次和标一次**字节相同**。

    【为什么这条要紧】转存是**会重试**的（§9.3）。如果每次标记都往里
    追加一份 EXIF/XMP，一条重试三次的任务会得到一个体积膨胀、
    而且带三份标识的文件 —— 而那看起来完全正常。
    """
    path = image_file(fmt)
    # ⚠️ **同一个 payload 用两次**。`payload_for()` 每次都取当下时间，
    # 重新造一个的话两次的 `created_at` 不同 —— 那测的就不是「会不会
    # 叠加」，而是「两次时间戳一样吗」（答案是不会，而那不是 bug）。
    payload = _payload()
    marking.apply_marker(path, mime=f"image/{fmt.lower()}", payload=payload)
    once = path.read_bytes()

    marking.apply_marker(path, mime=f"image/{fmt.lower()}", payload=payload)

    assert path.read_bytes() == once


def test_能标记的格式和探测得到的容器是同一批(image_file) -> None:
    """`_MARKABLE_IMAGE_FORMATS` 与 `_detect_container` **必须一一对应**。

    ─────────────────────────────────────────────────────────
    【为什么这是一条跨模块的一致性断言，而不是两条单元测试】

    这两个集合分住在两个函数里，它们的**失配方式是不报错的**：

      · 往清单里加一个格式、没加探测分支 → `write_image_marker`
        会走到最后那个 `else`（WebP 分支）并对着一张不是 WebP 的图
        调 `_mark_webp` —— 它自己会抛（那里有格式断言），所以要等到
        真碰上那种产物时才炸。
      · 加了探测分支、没加清单 → 那张图能探出来，但永远标不上。

    也就是说，失配的代价是「某个格式在某一天悄悄没被标」——
    而标识是法律义务。一条集合相等的断言把这件事变成一次即刻的红。
    ─────────────────────────────────────────────────────────
    """
    from app.services import transcode

    probed = {transcode._detect_container(image_file(fmt).read_bytes()) for fmt in _IMAGE_FORMATS}

    assert probed == set(transcode._MARKABLE_IMAGE_FORMATS)


def test_不支持的容器会响亮地失败(tmp_path: Path) -> None:
    """写不进去的格式必须抛，不能「尽力而为」。

    【为什么不能静默跳过】跳过 = 发布一份没有标识的 AI 产物。
    这条路的代价是用户看到一次失败，另一条路的代价是一次合规事故。
    """
    path = tmp_path / "x.bin"
    path.write_bytes(b"not a container we know")

    with pytest.raises(TranscodeError):
        marking.apply_marker(path, mime="video/webm", payload=_payload())


# ══════════════════════════════════════════════════════════════
# 五、逃生门
# ══════════════════════════════════════════════════════════════


def test_默认是开着标识的() -> None:
    """⚠️ 默认必须是开的。**这一条比它看起来重要。**

    一个默认关闭的合规开关，在照文档部署起来的环境里等于没做 ——
    而它从外表上看完全正常。同 `DEFAULT_BLOCKLIST` 非要有一份内置
    词表的理由。
    """
    assert get_settings().marking_enabled is True


def test_关掉开关之后字节完全不变而且留下一条_warning(
    image_file, settings_env, caplog
) -> None:
    """逃生门：元数据工具坏了的机器上先让交付继续。

    【为什么要求一条 warning】关掉标识是**合规上的例外**，不该安静地
    发生。要能在日志里翻到「这台机器不发标识」，而不是等出事之后
    去读 `git log`。
    """
    path = image_file("PNG")
    before = path.read_bytes()
    settings_env(MARKING_ENABLED="0")

    with caplog.at_level(logging.WARNING):
        marking.apply_marker(path, mime="image/png", payload=_payload())

    assert path.read_bytes() == before
    assert "隐式标识" in caplog.text, "关掉合规开关却不留痕"


# ══════════════════════════════════════════════════════════════
# 六、接上了没有
# ══════════════════════════════════════════════════════════════


def _spooled_artifact() -> Path:
    """造一份「provider 刚给的产物」，返回它的路径。

    ⚠️ **必须落在 `provider_spool_root` 之内**，不能图省事放到
    `tmp_path` 里。`transfer._local_path_for_file_url` 有一道
    **包含性检查**（`file://` 只能指向暂存区之内）—— 那是防
    「构造一个 `file:///C:/...` 把服务器上的任意文件读出来」的。
    放宽它去迁就一条测试，等于把那道闸拆了。
    """
    dest = get_settings().provider_spool_root_ready / "generated" / "test-artifact"
    render_image(32, 32, (1, 2, 3), dest)
    return dest


def test_落进存储的那一份本身就带标识(api_app) -> None:
    """转存流水线的验收：`put_file` 存的是**已经标好的**字节。

    【为什么断言的是「存储里的那一份」而不是「暂存文件」】
    因为「先存一份没标的、再改一遍」也能让暂存文件带标识 ——
    而那样中间有一小段时间，存储里躺着一份没有标识的 AI 产物，
    且改失败时留下的正是它。
    """
    src = _spooled_artifact()

    specs = transfer_artifact(
        task_id=_TASK_ID, kind=TaskKind.text_to_image, provider_url=src.as_uri()
    )

    landed = get_settings().media_root_ready / specs[0].storage_key
    marker = read_implicit_marker(landed)
    assert f"task={_TASK_ID}" in (marker["UserComment"] or ""), "存进去的那一份没带标识"
    assert specs[0].size_bytes == landed.stat().st_size, "size_bytes 必须反映落盘的那一份"


def test_写标识失败会变成可重试的转存失败(api_app, monkeypatch) -> None:
    """合规优先：宁可不出，也不出一份没有标识的产物。

    【为什么是 `retryable=True`】因为这一步是纯本地 IO，失败多半是
    一次抖动（磁盘忙、临时文件被占）。重试没有副作用累积 ——
    真重试了也不会堆出两份标识（见 `test_重复标记不会叠加`）。
    """
    src = _spooled_artifact()

    def _boom(*args: object, **kwargs: object) -> None:
        raise TranscodeError("假设这个环境的 EXIF 工具坏了")

    monkeypatch.setattr("app.services.transfer.marking.apply_marker", _boom)

    with pytest.raises(TransferFailure) as excinfo:
        transfer_artifact(
            task_id=_TASK_ID, kind=TaskKind.text_to_image, provider_url=src.as_uri()
        )

    assert excinfo.value.retryable is True, "写不上标识失败一次就判死 = 一次抖动赔掉一个任务"
    assert "标识" in str(excinfo.value), "错误消息要说清是标识那一步失败的"


async def test_生成出来的作品在库里带标识(api: httpx.AsyncClient) -> None:
    """端到端：`POST /generation/image` 出来的东西，从 `public_url` 取回来看。

    【为什么还要这一条 —— 上面 `transfer_artifact` 那条不是够了吗】
    不够。它证的是**流水线**带标识，这一条证的是**请求路径真的走到了
    流水线**。把 `finish_succeeded` 里那次转存换成「不落盘只写库」，
    上面那条照样绿，而用户拿到的是一个 404 的作品。
    """
    headers, _ = await new_user(api, "出图的人")
    task = (await submit_image(api, headers)).json()
    assert task["status"] == "succeeded", task

    items = (await api.get("/assets", headers=headers)).json()["items"]
    assert len(items) == 1
    asset = items[0]
    # 显式标识（前端那个角标）与隐式标识**同时**成立，缺一不可。
    assert asset["is_ai_generated"] is True

    key = asset["public_url"].split("/media/", 1)[1]
    landed = get_settings().media_root_ready / key
    marker = read_implicit_marker(landed)

    assert f"task={task['id']}" in (marker["UserComment"] or "")
    assert marking.AI_LABEL in (marker["UserComment"] or "")


async def test_上传的参考图不带标识(api: httpx.AsyncClient) -> None:
    """⚠️ 守卫：上传路径**结构上**不经过 `transfer_artifact`。

    ─────────────────────────────────────────────────────────
    【为什么这条是「守卫」而不是「功能」】

    用户的参考图不是 AI 生成的 —— 给它们打上「AI 生成」标识就是
    一次**错误标注**，而错误标注比不标更坏（它会让审查工具把一张
    真人拍的照片归到 AI 那一类）。

    今天它是**结构上**成立的（上传走 `assets.store_reference_image`，
    不经过转存流水线），所以这一条测试不是在验一个 if，而是在钉住
    「将来有人把标识挪到更上游（比如挪进 `storage.put_file`）时，
    这件事会被发现」。

    最硬的验法是**字节相同**：上传接口存的就是收到的那些字节，
    一个 bit 都不许多。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "传参考图的人")
    payload = real_png(64, 48)

    body = (
        await api.post(
            "/uploads/image",
            files={"file": ("ref.png", payload, "image/png")},
            headers=headers,
        )
    ).json()

    key = body["public_url"].split("/media/", 1)[1]
    landed = get_settings().media_root_ready / key

    assert landed.read_bytes() == payload, "上传的字节被改过了 —— 参考图不该被标"
    marker = read_implicit_marker(landed)
    assert marker["UserComment"] is None
    assert marker["xmp"] is None
    assert marker["ImageDescription"] is None
