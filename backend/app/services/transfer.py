"""转存流水线 —— §9.2 的「provider 地址 → 我们自己的永久地址」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这一层必须是独立的一段】

`provider_url` 是**即梦的临时地址，只活 1 小时**（§9.2）。资产的真身
必须是我们存储里的一份拷贝，否则一小时后用户的作品全变裂图 ——
而他昨天明明还能看。

【这一段是**纯 IO**：不碰数据库会话、不抛 `AppError`】

它只做「拿到字节 → 落进 storage → 算出一份产物规格」。所有
「失败了怎么办」（记在任务上 / 退钱 / 重试）都在
`services/generation.py` 里，因为那需要事务。

【关于 `file://`】

真 provider 给的是 https 外网地址；**fake 给的是本地文件**
（它得真的造出字节来，否则 B4 到 B6 之间这条链路上没有任何一行
代码被执行过 —— B2b 的教训就是「从没跑过的路一定有问题」）。

于是这里必须回答一个问题：**一个 `file://` 地址是谁给的？**
答案只能是「我们自己」。所以它只允许读
`settings.provider_spool_root` 之内的东西。不设这条边界的话，
一个被污染的 `provider_url`（比如将来真 provider 的回参里带了
`file:///C:/Users/.../credentials`）就变成一次**任意文件读取** ——
后端会把它复制进 `media_root` 并公开发布出去。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from app.config import get_settings
from app.enums import AssetKind, TaskKind
from app.services import marking
from app.services import storage as storage_module
from app.services.storage import Storage
from app.services.transcode import (
    COVER_HEIGHT,
    COVER_WIDTH,
    TranscodeError,
    extract_cover,
    ffmpeg_available,
    placeholder_cover,
    probe_image,
    probe_video,
)

logger = logging.getLogger(__name__)

# 分块大小。1MB 是「一次系统调用够大」与「内存里不会同时有两份大 buffer」
# 之间的折中：64KB 会让 200MB 的产物变成 3200 次写。
_CHUNK = 1024 * 1024

# 魔数 → mime。**只认我们真的会收到的几种**；认不出就拒。
# 【为什么要有一张表】因为「provider 返回了一张叫 out.png 的 HTML」
# 是真实存在的失败形态（403 页面、签名过期页面）。不校验的话它会
# 作为一个「图片」被存进库里、被前端当图片加载 —— 而错误从此在下游。
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"BM", "image/bmp", ".bmp"),
)


class TransferFailure(Exception):
    """转存失败。**消息里绝不放 URL。**

    ─────────────────────────────────────────────────────────
    【为什么连 URL 都不许放】因为它的消息会被写进
    `tasks.error_msg`，而**那个字段是会出现在响应里的**
    （`TaskOut.error_msg`）。即梦的产物地址是带签名的 ——
    签名进响应就等于进每一个桌面客户端的缓存、进用户随手发的截图。

    要排查地址的话，去日志里看：`_describe()` 只打
    `scheme://host/…<文件名>`，**丢掉 query**（签名在 query 里）。
    ─────────────────────────────────────────────────────────
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        self.retryable = retryable
            # 【为什么默认 True】保守的方向：一个忘了标 `retryable=False`
            # 的新失败会白重试三次（几秒），而反过来会把「等一下就好」
            # 的超时直接判死。同 `ProviderFailure`。
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """一份**已经落在存储里**的产物，够用来建一行 `assets`。

    【为什么没有 `duration_sec`】因为那个字段的真相在**任务**上
    （`task.output_duration_sec`，计费依据），不在文件里。留一个
    「顺手能填」的同名字段，早晚会有人用它 —— 而 ffprobe 量出来的
    时长与 provider 回参的时长可以不一样（编码器的时间基），
    那会让 `test_tasks_assets_b2.py` 里那条 `duration_sec == 6`
    因为一个与契约无关的原因变红。
    """

    kind: AssetKind
    storage_key: str
    mime: str
    size_bytes: int
    width: int | None
    height: int | None
    sha256: str | None = None


# ══════════════════════════════════════════════════════════════
# 暂存区
# ══════════════════════════════════════════════════════════════


@contextmanager
def staging_dir() -> Iterator[Path]:
    """一个用完就删的暂存目录，**建在 spool 根之下**。

    ─────────────────────────────────────────────────────────
    【为什么不用系统临时目录】

    Windows 上系统临时目录在 `C:`，而 `media_root` 在本机是 `G:`。
    跨卷的 `os.replace` 会抛 `EXDEV`（`storage.LocalStorage` 的
    `_atomic_write` 已经把这个坑的**后果**处理掉了 —— 它在目标目录里
    建临时文件），但暂存区放在同一个盘还有第二个好处：一次 200MB 的
    转存不会在系统盘上留一份，而系统盘通常最紧。

    【为什么它属于 spool 根而不是 media_root】因为 media_root 是
    **被 StaticFiles 发布出去的**：把半个文件放在那里面，
    就意味着它可能被 /media/<key> 请求到。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    with tempfile.TemporaryDirectory(dir=settings.provider_spool_root_ready) as tmp:
        yield Path(tmp)


# ══════════════════════════════════════════════════════════════
# 取字节
# ══════════════════════════════════════════════════════════════


def _describe(url: str) -> str:
    """给日志用的地址描述：**丢掉 query**（签名在那里）。"""
    parts = urlsplit(url)
    name = Path(parts.path).name
    return f"{parts.scheme}://{parts.netloc or ''}…{name}" if name else parts.scheme


def _local_path_for_file_url(url: str) -> Path:
    """`file://` → 本地路径，**并校验它在我们自己的暂存区里**。

    ─────────────────────────────────────────────────────────
    【为什么不能只写 `url.startswith("file://")` 然后取路径】

    那是一条**任意文件读取**。几个必须处理的形态：

      · `file:///G:/x` —— `urlsplit` 给的 path 是 `/G:/x`，
        前导斜杠要剥掉，否则会拼成一个以反斜杠开头的、不存在的路径。
      · `file://evil.com/share/x` —— netloc 非空就是 UNC/SMB。
        它会让 Windows 去连一个远程共享（一次外带请求）。
      · `file:///G:/spool/../../../etc/passwd` —— 要 `resolve()`
        之后再比，字符串前缀比较挡不住。
      · 暂存区里一个指向区外的**符号链接** —— `resolve()` 会展开它。

    比较用的是**路径**（`is_relative_to`），不是字符串前缀：
    `G:/spool-evil` 也以 `G:/spool` 开头。
    ─────────────────────────────────────────────────────────
    """
    parts = urlsplit(url)
    if parts.netloc:
        raise TransferFailure("file:// 地址带了主机名（UNC/SMB 一律拒绝）", retryable=False)

    raw = unquote(parts.path)
    # Windows：`/G:/...` → `G:/...`。只在「前导斜杠 + 盘符」时剥，
    # 否则会把 POSIX 的绝对路径剥成相对路径。
    if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]

    candidate = Path(raw)
    spool = get_settings().provider_spool_root_ready.resolve()
    resolved = candidate.resolve()

    if resolved != spool and not resolved.is_relative_to(spool):
        raise TransferFailure("provider 地址指向了暂存区之外", retryable=False)
    if not resolved.is_file():
        # 【为什么这算「可重试」】它多半是「上一个进程死了、暂存文件被清了」
        # 或者一次并发的清理。真正的坏地址会连续失败，然后被重试上限收掉。
        raise TransferFailure("provider 产物在暂存区里不存在")

    size = resolved.stat().st_size
    if size > get_settings().max_artifact_bytes:
        raise TransferFailure(
            f"产物 {size} 字节超过上限 {get_settings().max_artifact_bytes}", retryable=False
        )
    return resolved


def _fetch_http(url: str, dest: Path) -> None:
    """`http(s)://` 分块下载。**边写边数字节，超限立刻中断。**"""
    settings = get_settings()
    limit = settings.max_artifact_bytes
    timeout = httpx.Timeout(connect=10.0, read=settings.ffmpeg_timeout_sec * 4, write=30.0, pool=10.0)

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    # 【为什么 4xx 不可重试、5xx 可重试】前者是「这个地址
                    # 本身不行了」（签名过期、路径错了），重试只是再撞一次；
                    # 后者是对方那边一时的问题。
                    raise TransferFailure(
                        f"provider 返回 HTTP {response.status_code}",
                        retryable=response.status_code >= 500,
                    )
                declared = response.headers.get("content-length")
                if declared is not None and declared.isdigit() and int(declared) > limit:
                    raise TransferFailure(
                        f"产物声明 {declared} 字节超过上限 {limit}", retryable=False
                    )

                written = 0
                with dest.open("wb") as fh:
                    for chunk in response.iter_bytes(_CHUNK):
                        written += len(chunk)
                        if written > limit:
                            # 【为什么读到这里就断】§9.3 的成本自保：
                            # 一个不报 content-length 的地址可以无限往下发，
                            # 不设闸门就是让对方的错误变成我们的磁盘账单。
                            raise TransferFailure(f"产物超过上限 {limit} 字节", retryable=False)
                        fh.write(chunk)
    except (httpx.HTTPError, OSError) as exc:
        raise TransferFailure(f"下载失败（{type(exc).__name__}）") from exc


def fetch(url: str, dest: Path) -> None:
    """把 `url` 的内容取到 `dest`。**只支持 file / http / https。**"""
    scheme = urlsplit(url).scheme.lower()
    if scheme == "file":
        source = _local_path_for_file_url(url)
        try:
            shutil.copyfile(source, dest)
        except OSError as exc:
            raise TransferFailure(f"复制暂存产物失败（{exc.strerror or exc}）") from exc
        return
    if scheme in ("http", "https"):
        _fetch_http(url, dest)
        return
    # 【为什么其它 scheme 一律拒】`data:` / `ftp:` / 空 scheme 都意味着
    # 地址不是我们预期的来源。放行它们只是给「将来某个被污染的
    # provider_url」多开一扇门，而我们从中得不到任何东西。
    raise TransferFailure(f"不支持的地址类型（{scheme or '空 scheme'}）", retryable=False)


# ══════════════════════════════════════════════════════════════
# 真实字节 → (mime, 扩展名)
# ══════════════════════════════════════════════════════════════


def _sniff(path: Path) -> tuple[str, str] | None:
    """按**魔数**判断这是不是图片/视频，返回 `(mime, 扩展名)`。

    【为什么不能信 URL 的后缀】`.../out.png` 后面接一个 HTML 错误页
    是最常见的失败形态（签名过期、被 CDN 拦了）。存进去之后，
    它会在用户的列表里表现为一张「加载失败」的图，而真正的病因
    （一次 403）要到那时才被发现 —— 而那时已经没有线索了。
    """
    head = path.open("rb").read(64)
    for magic, mime, ext in _MAGIC:
        if head.startswith(magic):
            return mime, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    # ── 视频容器 ──
    if len(head) >= 12 and head[4:8] == b"ftyp":
        # ISO BMFF：mp4 / mov / m4v 共用这个盒子。归到 mp4 是因为
        # 契约上视频资产就是 `video/mp4`（Mock 同款）。
        return "video/mp4", ".mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video/x-matroska", ".webm"
    if head[:1] == b"\x47":
        # MPEG-TS 以 0x47 同步字节打头。
        return "video/mp2t", ".ts"
    return None


# ══════════════════════════════════════════════════════════════
# 转存主流程
# ══════════════════════════════════════════════════════════════


def transfer_artifact(
    *,
    task_id: int,
    kind: TaskKind,
    provider_url: str,
) -> list[ArtifactSpec]:
    """转存一条任务的产物。返回**已落存储**的产物规格。

    调用方（`generation.finish_succeeded`）负责把它写进 `assets` 表、
    负责失败后的记账。

    ⚠️ 它是**幂等**的：同一个 `task_id` 重跑会写到同一批 storage_key 上
    （`generated_asset_key` 是确定性的），所以重试不会留下一堆副本。
    唯一会变的是扩展名 —— 若两次拿到的字节格式不同（第一次是 HTML
    错误页、第二次是真的 mp4），会多出一个小文件。那种文件属于
    「孤儿文件」这个已知缺口，v1 不做 GC。
    """
    storage = storage_module.build_storage()
    is_video = kind is not TaskKind.text_to_image

    with staging_dir() as work:
        raw = work / "artifact"
        fetch(provider_url, raw)

        sniffed = _sniff(raw)
        if sniffed is None:
            raise TransferFailure("产物不是可识别的图片或视频", retryable=False)
        mime, ext = sniffed
        expected = "video/" if is_video else "image/"
        if not mime.startswith(expected):
            # 【为什么这里要硬拒而不是「按 kind 存下去」】用户点的是出图，
            # 拿回来的是一段视频 —— 那说明地址配错了（或者 provider
            # 那边出错了）。存下去的话，前端会按图片去加载它，
            # 表现出来是「作品是黑的」，而库里的记录看起来完全正常。
            raise TransferFailure(f"产物类型与任务不符（拿到 {mime}）", retryable=False)

        # ── 隐式标识：在**落存储之前**就地写进字节（§10.1）──────
        # 【为什么在这个位置】① 在 `_sniff` 之后 —— 于是我们不会去标
        # 一个「其实是 HTML 错误页」的东西；② 在 `put_file` 之前 ——
        # 于是**存进去的那一份本身就是带标识的**，而不是「先存一份没标的、
        # 再改一遍」。后者的话，中间那一小段时间里存储里躺着一份没有标识的
        # AI 产物，而且改失败时留下的正是它。
        _mark(raw, mime=mime, task_id=task_id, kind=kind)

        specs: list[ArtifactSpec] = []

        if is_video:
            video_key = storage_module.generated_asset_key(task_id, f"out{ext}")
            storage.put_file(video_key, raw, content_type=mime)
            digest = None
            if get_settings().fabric_enabled:
                with raw.open("rb") as media:
                    digest = hashlib.file_digest(media, "sha256").hexdigest()
            info = probe_video(raw)
            specs.append(
                ArtifactSpec(
                    kind=AssetKind.video,
                    storage_key=video_key,
                    mime=mime,
                    size_bytes=raw.stat().st_size,
                    # 量不出来就退回契约尺寸（Mock 同款），不是 None ——
                    # 作品网格要靠它算格子高度，None 会让那一格塌掉。
                    width=(info.width if info and info.width else COVER_WIDTH),
                    height=(info.height if info and info.height else COVER_HEIGHT),
                    sha256=digest,
                )
            )
            specs.append(_make_cover(task_id, raw, work, storage, kind=kind))
            return specs

        image_key = storage_module.generated_asset_key(task_id, f"out{ext}")
        storage.put_file(image_key, raw, content_type=mime)
        info = probe_image(raw)
        specs.append(
            ArtifactSpec(
                kind=AssetKind.image,
                storage_key=image_key,
                mime=mime,
                size_bytes=raw.stat().st_size,
                width=info.width,
                height=info.height,
            )
        )
        return specs


def _mark(path: Path, *, mime: str, task_id: int, kind: TaskKind) -> None:
    """给一份即将落存储的产物写隐式标识（§10.1）。

    ─────────────────────────────────────────────────────────
    【失败为什么是「可重试的转存失败」，而不是「记一条日志照常发布」】

    因为写不上标识在合规上等于**这份产物不该发布**
    （《人工智能生成合成内容标识办法》的隐式标识要求）。
    照常发布的话，我们就是把一次法律义务上的失败降级成了一条
    没人看的 warning。所以：失败 → 转存重试 → 耗尽后任务 `failed`
    ＋**全额退款**。用户损失的是一次等待，平台不发出没有标识的 AI 内容。

    【为什么可以重试】因为这一步是**纯函数式的**：它就地改一个本地
    暂存文件，不碰存储、不碰数据库。重试没有副作用累积 ——
    真重试了也不会在文件里堆出两份标识（拼接路径会先去掉旧的同名块，
    见 `transcode._insert_png_metadata`）。

    【为什么 `marking_enabled=False` 时这里什么都不做还不报错】
    开关在 `marking.apply_marker` 里判（单一咽喉点），它会留一条
    warning。这里不管它，于是「关掉标识」和「标识写成功」在
    调用方看来是同一条路 —— 少一个会分岔的 if。
    ─────────────────────────────────────────────────────────
    """
    try:
        marking.apply_marker(
            path,
            mime=mime,
            payload=marking.payload_for(task_id=task_id, kind=kind.value),
        )
    except (TranscodeError, OSError) as exc:
        raise TransferFailure(f"给产物写隐式标识失败：{exc}", retryable=True) from exc


def _make_cover(
    task_id: int,
    video: Path,
    work: Path,
    storage: Storage,
    *,
    kind: TaskKind,
) -> ArtifactSpec:
    """给视频配一张封面（§11.2：列表读它，点开才读视频）。

    【ffmpeg 挂了为什么不失败】成片**已经拿到了**，缺的只是一张
    列表用的小图。为此把用户已经付费、也已经拿到视频的任务判失败，
    是把小问题升级成大问题。降级成纯色占位（C6 的原话），
    并在日志里留一条 —— 别让它静默过去。

    ⚠️ **但封面本身不是可选的，它也要带标识。** 它同样是 AI 生成的
       一帧（`extract_cover` 是从 AI 产出的视频里抽的），所以
       `_mark` 在这里**不许失败** —— 和上面「ffmpeg 挂了可以降级」
       不矛盾：降级改的是**封面长什么样**，而标识是合规要求，
       两条线各管各的。
    """
    cover = work / "thumb.jpg"
    if ffmpeg_available():
        try:
            extract_cover(video, cover)
        except TranscodeError as exc:
            logger.warning(
                "任务 %s 抽帧失败，改用占位封面（%s）—— 成片本身是好的", task_id, exc
            )
            placeholder_cover(cover)
    else:
        logger.warning(
            "任务 %s 没找到 ffmpeg，改用占位封面 —— 成片本身是好的"
            "（依赖闸门里 ffmpeg 那一项红了就是这件事的前兆）",
            task_id,
        )
        placeholder_cover(cover)

    cover_key = storage_module.generated_asset_key(task_id, "thumb.jpg")
    # 封面也要带标识：它同样是 AI 生成的一帧（见 docstring 末尾那段）。
    _mark(cover, mime="image/jpeg", task_id=task_id, kind=kind)
    storage.put_file(cover_key, cover, content_type="image/jpeg")
    # 封面的宽高**探出来**，不写死：契约要求它是 1280×720，
    # 而 `extract_cover` 里的 `scale=1280:720` 保证了这一点。
    # 探出来正好是对它的一次自检 —— 写死的话，抽帧参数改坏了也没人知道。
    info = probe_image(cover)
    return ArtifactSpec(
        kind=AssetKind.thumbnail,
        storage_key=cover_key,
        mime="image/jpeg",
        size_bytes=cover.stat().st_size,
        width=info.width or COVER_WIDTH,
        height=info.height or COVER_HEIGHT,
    )


__all__ = [
    "ArtifactSpec",
    "TransferFailure",
    "fetch",
    "staging_dir",
    "transfer_artifact",
]
