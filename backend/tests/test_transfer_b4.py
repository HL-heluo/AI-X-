"""转存流水线 —— §9.2 的「搬回自己的存储」与 §9.3 的「搬不回来怎么办」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么 B4 里这个文件最重要】

B0–B3 的产物是**一个拼出来的 URL**，背后没有文件。B4 之后它是一份
真的拷贝 —— 而「拷贝」这件事第一次让整条链路有了**会失败的 IO**。
§9.3 专门为它定了重试与退款，本文件就是那两条的实现验收。

文件分两段：

  · **上面**是流水线本身（纯 IO，不碰数据库、不经过 HTTP）。
    它测的是「哪些地址能读、什么字节算产物、规格从哪来」。
  · **下面**是三个入口上的失败处置，它们**故意各不相同**：
    同步路径 502 回滚、worker 路径留在 `submitted` 等重试、
    重试耗尽转 `failed` + 全额退回。这三条是 B4 最容易写错的地方。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from _helpers import new_user, real_png, submit_image, submit_video
from _providers import ScriptedProvider
from app import worker
from app.config import get_settings
from app.enums import AssetKind, TaskKind, TaskStatus, TransferState
from app.models import Task
from app.providers.fake import FakeProvider
from app.services.storage import generated_asset_key
from app.services.transcode import (
    COVER_HEIGHT,
    COVER_WIDTH,
    read_implicit_marker,
    render_image,
    synthesize_video,
)
from app.services.transfer import TransferFailure, fetch, transfer_artifact
from app.services.unit import atomic
from app.types import utcnow


@pytest.fixture(autouse=True)
def _clean_poll_schedule() -> None:
    """见 `test_worker_b3.py` 里同名的夹具：`_last_poll_round` 是模块级全局。

    不清的话，上一条用例留下的时间戳会让这一条的轮询被**静默跳过** ——
    表现是「断言里少了一次推进，而代码是对的」。
    """
    worker.reset_poll_schedule()


# ══════════════════════════════════════════════════════════════
# 第一段：流水线本身（不碰数据库、不经过 HTTP）
# ══════════════════════════════════════════════════════════════


class _Paths:
    """一处 `MEDIA_ROOT` 与一处 spool 根。用命名元组是为了让断言读得懂。"""

    def __init__(self, media: Path, spool: Path) -> None:
        self.media = media
        self.spool = spool


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把两个根都钉到 tmp_path 上。

    【为什么 spool 也必须钉】`staging_dir()` 建在 spool 根之下，
    而这一段的用例会往里面写文件。不钉的话它们落进仓库根目录，
    还会跨用例残留（spool 是内容寻址的缓存）。
    """
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("PROVIDER_SPOOL_ROOT", str(tmp_path / "spool"))
    get_settings.cache_clear()
    yield _Paths(tmp_path / "media", tmp_path / "spool")
    get_settings.cache_clear()


def _put(spool: Path, name: str, data: bytes) -> Path:
    dest = spool / "generated" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


# ── 能读哪些地址 ──────────────────────────────────────────────


def test_暂存区里的_file_地址能取出来(paths: _Paths) -> None:
    """fake provider 给的就是这种地址（B4 起它真的造字节）。"""
    source = _put(paths.spool, "a.png", real_png(64, 64))
    dest = paths.spool / "download.bin"

    fetch(source.as_uri(), dest)

    assert dest.read_bytes() == source.read_bytes()


def test_暂存区之外的_file_地址一律拒(paths: _Paths) -> None:
    """⚠️ 安全性质：这是一个**任意文件读取**的入口。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么它比它看起来更严重】

    `provider_url` 将来是由**外部的即梦回参**决定的。一个被污染
    或者被配错的地址，会让后端把服务器上的任意一个文件复制进
    `media_root` 并**公开发布**出去 —— 一份 `credentials`、
    一份 `.env`、一份别人的作品，都会变成一个可以随便下载的 URL。

    所以 `file://` 只允许指向**我们自己**造的那个暂存区。三种形状
    都要挡：兄弟目录（不含 `..`，字符串检查挡不住）、`..` 穿越、
    以及盘符路径。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    secret = paths.spool.parent / "credentials.txt"
    secret.write_bytes(b"AK=... SK=...")
    # ⚠️ 这个兄弟目录的名字**以 spool 的名字打头**（`spool-evil` vs `spool`）。
    # 用 `str(path).startswith(str(spool))` 做检查的实现会把它放行 ——
    # 字符串前缀比较在这件事上是错的，必须按**路径**比。
    evil = paths.spool.parent / f"{paths.spool.name}-evil"
    evil.mkdir()
    (evil / "secret.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"leak" * 4)

    for url in (
        secret.as_uri(),
        (paths.spool / ".." / secret.name).as_uri(),
        (evil / "secret.png").as_uri(),
    ):
        with pytest.raises(TransferFailure) as err:
            fetch(url, paths.spool / "download.bin")
        assert err.value.retryable is False, "地址错不是抖动，重试只是再撞一次"
        assert secret.name not in str(err.value), "错误信息不许把地址带出去"
        assert not (paths.spool / "download.bin").exists()

    assert secret.is_file(), "被拒的读取不该动到源文件"


def test_UNC_地址被拒(paths: _Paths) -> None:
    """`file://server/share/x` 在 Windows 上是一次**外带**：会去连远程共享。

    【为什么 netloc 非空就一律拒】我们没有合法的 UNC 用途 ——
    我们的暂存区永远在本机。放行它只是给「被污染的地址」多开一扇门。
    """
    with pytest.raises(TransferFailure, match="主机名") as err:
        fetch("file://fileserver/share/out.png", paths.spool / "download.bin")

    assert err.value.retryable is False


def test_暂存区里不存在的文件算可重试(paths: _Paths) -> None:
    """文件不在 ≠ 地址坏。

    它多半是「上一个进程死了、暂存文件被清了」或者一次并发清理 ——
    那属于**等一下会好**。判成不可重试的话，一次抖动就把任务钉死；
    而真正的坏地址会连续失败，最后被重试上限收掉。
    """
    with pytest.raises(TransferFailure) as err:
        fetch((paths.spool / "generated" / "gone.png").as_uri(), paths.spool / "d.bin")

    assert err.value.retryable is True


def test_其它地址类型一律拒(paths: _Paths) -> None:
    """`data:` / `ftp:` / 空 scheme 都不是我们预期的来源。

    【为什么连 `data:` 也拒】它看起来无害（一个内联的字节串），
    但它意味着「地址不是来自我们认识的 provider」。放行它只会让
    「这个字段可能是什么」多一种可能，而我们从中得不到任何东西。
    """
    for url in ("data:image/png;base64,AAAA", "ftp://host/x.png", "not-a-url", ""):
        with pytest.raises(TransferFailure) as err:
            fetch(url, paths.spool / "d.bin")
        assert err.value.retryable is False, url


# ── 字节与规格 ────────────────────────────────────────────────


def test_不是图片也不是视频的产物被拒(paths: _Paths) -> None:
    """⚠️ 魔数校验：provider 可能返回一张叫 `out.png` 的 HTML。

    【为什么必须按**字节**判，不能信后缀】`.../out.png` 后面接一个
    403/签名过期页面是最常见的失败形态。存进去之后，它会在用户的
    作品页里表现为一张「加载失败」的图，而真正的病因（一次 403）
    要到那时才被发现 —— 那时已经没有线索了。
    """
    html = _put(paths.spool, "out.png", b"<html>403 Forbidden</html>")

    with pytest.raises(TransferFailure, match="不是可识别的") as err:
        transfer_artifact(task_id=1, kind=TaskKind.text_to_image, provider_url=html.as_uri())

    assert err.value.retryable is False


def test_产物类型与任务不符被拒(paths: _Paths) -> None:
    """用户点的是出视频，拿回来的是一张图 —— 那说明地址配错了。

    【为什么不能「按 kind 存下去」】存下去的话，前端会按视频去加载它，
    表现出来是「作品是黑的」，而库里的记录看起来完全正常。
    """
    image = _put(paths.spool, "out.png", real_png(64, 64))

    with pytest.raises(TransferFailure, match="与任务不符"):
        transfer_artifact(task_id=2, kind=TaskKind.image_to_video, provider_url=image.as_uri())


def test_图片产物落进media_root_规格来自真实字节(paths: _Paths) -> None:
    """`size_bytes` / `width` / `height` 不再是写死的常量。"""
    payload = real_png(1024, 1024)
    source = _put(paths.spool, "out.png", payload)

    specs = transfer_artifact(
        task_id=42, kind=TaskKind.text_to_image, provider_url=source.as_uri()
    )

    assert len(specs) == 1, "出图只有一个产物（Mock 也不给图片配缩略图）"
    spec = specs[0]
    assert spec.kind is AssetKind.image
    assert spec.storage_key == generated_asset_key(42, "out.png")
    assert spec.mime == "image/png"
    assert (spec.width, spec.height) == (1024, 1024)

    landed = paths.media / spec.storage_key

    # ── B5 起：`size_bytes` 是**落盘那一份**的字节数，不再是源字节数 ──
    # 【为什么这个字段的定义变了】因为隐式标识是在 `put_file` **之前**
    # 就拼进字节里的（§10.1），于是存储里那一份比 provider 给的多了
    # 几百字节的元数据。断言直接对着落盘的文件量 —— 这才贴近这个字段
    # 的定义（前端拿它算下载进度，它必须说「你会下到多少字节」）。
    assert spec.size_bytes == landed.stat().st_size
    # 下面这条防「断言退化成恒等式」：哪天标识被关掉或漏掉，
    # `size_bytes == 源大小` 同样会让上面那条通过，而它什么都没证明。
    assert spec.size_bytes > len(payload), "标识必须真的加进字节里"

    marker = read_implicit_marker(landed)
    assert "task=42" in (marker["UserComment"] or ""), (
        "落盘的那一份必须带隐式标识（§10.1）—— 这不是可选项"
    )


def test_视频产物带一张契约尺寸的封面(paths: _Paths) -> None:
    """§11.2：视频落两份 —— 正片 + 封面，封面是**独立**的一个文件。"""
    video = paths.spool / "source.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    synthesize_video(video, width=640, height=360, duration_sec=1, color=(9, 40, 90))

    specs = transfer_artifact(
        task_id=7, kind=TaskKind.image_to_video, provider_url=video.as_uri()
    )

    by_kind = {spec.kind: spec for spec in specs}
    assert set(by_kind) == {AssetKind.video, AssetKind.thumbnail}

    assert by_kind[AssetKind.video].mime == "video/mp4"
    assert by_kind[AssetKind.video].storage_key == generated_asset_key(7, "out.mp4")
    assert (
        by_kind[AssetKind.video].width,
        by_kind[AssetKind.video].height,
    ) == (640, 360), "正片的宽高来自**文件本身**（探针量的），不是契约值"

    # 同上一条：`size_bytes` 量的是**落盘那一份**（标识已经拼进去了）。
    video_landed = paths.media / by_kind[AssetKind.video].storage_key
    assert by_kind[AssetKind.video].size_bytes == video_landed.stat().st_size
    assert by_kind[AssetKind.video].size_bytes > video.stat().st_size, "正片要带标识"

    cover = by_kind[AssetKind.thumbnail]
    assert cover.mime == "image/jpeg"
    assert cover.storage_key == generated_asset_key(7, "thumb.jpg")
    assert (cover.width, cover.height) == (COVER_WIDTH, COVER_HEIGHT)
    cover_landed = paths.media / cover.storage_key
    assert cover_landed.is_file()

    # ── 两个产物**都要**带标识，封面不能漏 ──────────────────
    # 【为什么封面也要】它同样是 AI 生成的一帧（从 AI 产出的视频里抽的）。
    # 「正片标了、封面没标」是很容易漏的一处 —— 因为封面是另一条代码路径
    # （`_make_cover`）产出的，而列表页展示的恰恰是它。
    video_marker = read_implicit_marker(video_landed)
    assert video_marker["format"] == "video"
    assert "task=7" in (video_marker["comment"] or ""), "正片必须带标识"
    assert "task=7" in (read_implicit_marker(cover_landed)["UserComment"] or ""), (
        "封面也必须带标识（它是另一条代码路径，最容易漏）"
    )


def test_ffmpeg不在时_封面降级成占位图_但任务照样成功(
    paths: _Paths, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """C6 的降级方案：**成片已经拿到了**，缺的只是一张列表小图。

    【为什么必须记一条 warning】降级本身是对的，静默的降级不是 ——
    否则「所有封面都是纯灰块」这件事没有任何地方会说。
    """
    video = paths.spool / "source.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    synthesize_video(video, width=640, height=360, duration_sec=1, color=(1, 2, 3))

    monkeypatch.setattr("app.services.transfer.ffmpeg_available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="app.services.transfer"):
        specs = transfer_artifact(
            task_id=8, kind=TaskKind.image_to_video, provider_url=video.as_uri()
        )

    cover = next(spec for spec in specs if spec.kind is AssetKind.thumbnail)
    assert (cover.width, cover.height) == (COVER_WIDTH, COVER_HEIGHT)
    assert (paths.media / cover.storage_key).is_file()
    assert "占位封面" in caplog.text, (
        "降级必须留痕。⚠️ 如果这里收到的是空字符串，先确认没有别的东西"
        "把 `app.*` 的 logger 关掉了 —— `fileConfig` 的默认行为就会"
        "（见 `alembic/env.py` 里那条 `disable_existing_loggers=False`）。"
    )


def test_超过产物上限的文件被拒(
    paths: _Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9.3 的成本自保：一个不报大小的地址可以无限往下发。

    【为什么它和用户的 20MB 上传是两个数】那个管用户上传（§9.4），
    这个管 provider 给我们的成品 —— 一段 720P 视频本来就大得多。
    用一个数的话，要么视频被卡死，要么上传口子开成 200MB。
    """
    monkeypatch.setenv("MAX_ARTIFACT_BYTES", "1024")
    get_settings.cache_clear()
    big = _put(paths.spool, "big.mp4", b"\x00" * 4096)

    with pytest.raises(TransferFailure, match="超过上限") as err:
        transfer_artifact(task_id=9, kind=TaskKind.image_to_video, provider_url=big.as_uri())

    assert err.value.retryable is False, "超大是地址的性质，不是抖动"
    assert not (paths.media / generated_asset_key(9, "out.mp4")).exists()


# ══════════════════════════════════════════════════════════════
# 第二段：转存失败的三条去向
# ══════════════════════════════════════════════════════════════


class _OutsideSpoolProvider(FakeProvider):
    """产物地址指向暂存区之外。

    它造出的**是**一份真产物（`super().submit` 照做），只是把地址
    换成了一个我们不认的 —— 这正是「将来某个被污染的 provider 回参」
    的形状，而它同时也是**同步路径**上最干净的一次转存失败。
    """

    name = "outside-spool"

    def submit(self, request):  # type: ignore[no-untyped-def]
        result = super().submit(request)
        outside = Path(tempfile.gettempdir()) / "not-ours.mp4"
        return replace(result, provider_url=outside.as_uri())


class _MissingArtifactProvider(ScriptedProvider):
    """第一次问就出结果，但那个地址指向暂存区里**不存在**的文件。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这个形状最像真 provider 的那次抖动】

    §9.2 说得很清楚：产物地址**只活 1 小时**。所以
    「拿到了地址」和「下载到它」之间出现一次失效是完全正常的 ——
    那正是重试能救回来的那一类。

    文件由用例在「该好了」的时候补上。也就是说这条用例真的走完了
    「失败 → 留在 submitted → 下一轮搬回来 → 结算 → 落资产」。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    def __init__(self, *, missing: Path) -> None:
        super().__init__(polls_before_done=0)
        self.missing = missing

    def poll(self, provider_task_id: str):  # type: ignore[no-untyped-def]
        result = super().poll(provider_task_id)
        if result is None:
            # ⚠️ 回执只给一次（基类的 `_pending.pop`）。于是下一轮 ② 这条
            # 路什么都问不出来 —— 能把任务救回来的**只有** ②.5。
            return None
        return replace(result, provider_url=self.missing.as_uri())


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider) -> None:  # type: ignore[no-untyped-def]
    """两处都要打补丁（字符串目标），理由见 `conftest.py` 的 `scripted` 夹具。

    `lambda kind: ...` 的 `kind` 必须收下（B7.x 起 `build_provider` 有它），
    但**每个 kind 都给同一个替身** —— 理由同样在 `scripted` 夹具那段。
    """
    monkeypatch.setattr("app.services.generation.build_provider", lambda kind: provider)
    monkeypatch.setattr("app.worker.build_provider", lambda kind: provider)


@pytest.fixture
def outside_spool(monkeypatch: pytest.MonkeyPatch):
    provider = _OutsideSpoolProvider()
    _patch_provider(monkeypatch, provider)
    return provider


class _SyncRetryableProvider(FakeProvider):
    """产物地址**在暂存区里**，但那个文件不存在 —— 一次**可重试**的失败。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么必须单独有这一个「可重试」的味道】

    因为 `sync` 那面开关真正要挡的形状就是这个：其它两个条件
    （`not exc.retryable` / 重试次数耗尽）都不成立 —— 所以
    **只有**「这是一条同步请求」能让它立刻判死。

    少了那一半的话，用户拿到的是一次 200 + `status:"submitted"`，
    而 `TEST_MODE=1` 的实例**不起 worker**（跨仓门禁用的就是它）:
    那条任务永远停在生成中、积分冻到一小时超时。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    name = "sync-retryable"

    def submit(self, request):  # type: ignore[no-untyped-def]
        result = super().submit(request)
        gone = get_settings().provider_spool_root_ready / "generated" / "gone-forever.png"
        return replace(result, provider_url=gone.as_uri())


@pytest.fixture
def sync_retryable(monkeypatch: pytest.MonkeyPatch):
    provider = _SyncRetryableProvider()
    _patch_provider(monkeypatch, provider)
    return provider


@pytest.fixture
def missing_provider(api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """依赖 `api` 是为了让配置已经钉好 —— 地址必须在 tmp 的 spool 里。"""
    missing = get_settings().provider_spool_root_ready / "generated" / "later.png"
    provider = _MissingArtifactProvider(missing=missing)
    _patch_provider(monkeypatch, provider)
    return provider


def _task_row(session: Session, task_id: int) -> Task:
    """**另开一个会话的视角**读任务当前的样子（见 `test_worker_b3.py`）。"""
    session.expire_all()
    task = session.get(Task, task_id)
    assert task is not None, f"任务 {task_id} 不见了"
    return task


async def _account(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    return (await api.get("/me", headers=headers)).json()["credit_account"]


async def _assert_什么痕迹都没留(api: httpx.AsyncClient, headers: dict[str, str]) -> None:
    """被拒的提交不留痕：任务、资产、钱、字节，一样都不许剩。"""
    assert (await api.get("/tasks", headers=headers)).json()["items"] == []
    assert (await api.get("/assets", headers=headers)).json()["items"] == []

    account = await _account(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 0)

    landed = [p for p in get_settings().media_root_ready.rglob("*") if p.is_file()]
    assert landed == [], f"失败了还留下了文件：{landed}"


async def test_同步路径的转存失败_502_而且一整笔都不留(
    api: httpx.AsyncClient, outside_spool: object
) -> None:
    """⚠️ 本批最重要的一条回归（评审的 C1）。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【如果这条不成立，会发生什么】

    用户点「生成」，请求几秒后返回 **200 + `status:"submitted"`**
    —— 看起来一切正常。但转存已经失败了，而 `TEST_MODE=1` 的实例
    **根本不启动 worker**（`app/main.py`，跨仓门禁用的就是这种配置）：
    那条任务会永远停在 `submitted`，积分冻到一小时超时。

    前端看到的是一个「一直在生成中」的作品 —— 而它永远不会有结果。

    所以同步路径上转存失败 = **终态失败**：走已经存在的那条升级路
    （`_terminate(failed)` → `submit` 里抛 → `atomic()` 回滚），
    与 B2 以来「被拒的提交不留痕」完全一致。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "地址被配错的人")

    res = await submit_image(api, headers)

    assert res.status_code == 502, res.text
    assert res.json()["code"] == "PROVIDER_ERROR"
    await _assert_什么痕迹都没留(api, headers)


async def test_同步路径上可重试的转存失败_也是502(
    api: httpx.AsyncClient, sync_retryable: object
) -> None:
    """**可重试**的转存失败在同步路径上也必须立刻判死。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这条比上一条更锋利】

    上一条的失败是「不可重试」的，而那半个条件在 B4 之前就存在 ——
    也就是说，它**区分不出** `sync` 那面开关有没有被接上。

    这一条的失败是**可重试**的：`not exc.retryable` 不成立、
    重试次数也没耗尽，唯一能让它判死的就是「这是一条同步请求」。
    拿掉 `sync` 那一半，这里就会变成 200 + `submitted` ——
    而那时没有任何人会在等它（那种实例不起 worker）。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "产物还没生成好的人")

    res = await submit_image(api, headers)

    assert res.status_code == 502, res.text
    assert res.json()["code"] == "PROVIDER_ERROR"
    await _assert_什么痕迹都没留(api, headers)


async def test_转存失败先留在submitted_下一轮搬回来就结算(
    api: httpx.AsyncClient, api_session: Session, missing_provider
) -> None:
    """**worker 路径**上转存失败不判死：§9.3 的重试。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么它和上一条的处置**故意不同**】

    上一条有一个**活着的请求**在等（用户手里攥着没返回的 HTTP），
    而这条没有：任务已经存在、钱已经冻了。把这条任务回滚掉等于
    把证据删掉 —— 用户会看到「我明明提交过，怎么什么都没有」。

    所以这条记在任务上等重试，而**公开状态仍是 `submitted`**
    （§3.6 的决定：不自造第 9 个状态，前端照旧显示「生成中」）。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "转存抖了一下的人")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()
    assert task["status"] == "submitted"

    t0 = utcnow()
    first = worker.run_once(api_session, now=t0)

    assert first.advanced == [task["id"]]
    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.submitted, "转存失败不该让公开状态变"
    assert row.transfer_state is TransferState.failed
    assert row.transfer_attempts == 1
    assert row.error_code == "TRANSFER_FAILED"
    assert row.provider_url, "地址要留着 —— 重试就是靠它"

    account = await _account(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 4), "重试中的任务不退钱"
    assert (await api.get("/assets", headers=headers)).json()["items"] == []

    # 「签名」恢复了：产物文件出现了（真 provider 那边就是这一次抖动过去了）。
    #
    # ⚠️ 尺寸故意**不是** fake 那两个契约值（1024 / 1280×720）。
    # 因为「宽高写死」这个改法在 fake 下**看起来完全正常** ——
    # fake 产的正好就是那两个数。只有拿一个别的尺寸的产物，
    # 才能把「从真实字节里探出来的」和「写死的常量」分开。
    render_image(333, 777, (7, 8, 9), missing_provider.missing)

    later = worker.run_once(api_session, now=t0 + timedelta(seconds=5))

    assert later.advanced == [], "② 那条路问不出东西了（回执只给一次）"
    assert later.retried == [task["id"]], "救命的是 ②.5 那个补转存相位"

    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.succeeded
    assert row.transfer_state is TransferState.done
    assert row.provider_url is None, "用完就清掉（它只活 1 小时）"

    account = await _account(api, headers)
    assert (account["balance"], account["frozen"]) == (46, 0)

    items = (await api.get("/assets", headers=headers)).json()["items"]
    assert len(items) == 1
    # `size_bytes` 是**落盘那一份**的字节数（B5 起标识拼在里面），
    # 不是 provider 源文件的字节数。所以对着 media 里那份量。
    landed = get_settings().media_root_ready / generated_asset_key(task["id"], "out.png")
    assert items[0]["size_bytes"] == landed.stat().st_size
    assert items[0]["size_bytes"] > len((missing_provider.missing).read_bytes()), (
        "标识必须真的加进字节里（否则上面那条会在标识失效时照样通过）"
    )
    assert (items[0]["width"], items[0]["height"]) == (333, 777), (
        "资产的宽高必须来自真实字节（探针），不是写死的常量"
    )


async def test_重试耗尽_判failed_全退_而且不泄漏地址(
    api: httpx.AsyncClient, api_session: Session, missing_provider
) -> None:
    """§9.3 的下半段：重试预算用完之后。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么是**全额**退回，而不是「按已生成的成片扣」】

    成片在 provider 那边确实做出来了，但我们**没交付**。
    §7.6 的退款纪律只有一条：没交付就全退。按内部状态扣钱的话，
    用户会为一份他永远看不到、也永远不会出现在他作品页里的文件付钱。

    【为什么这条顺带断言「不泄漏地址」】`error_msg` **会出现在响应里**。
    即梦的产物地址是带签名的 —— 进了响应就等于进每一个客户端的
    缓存、进用户随手发的截图。所以要连原始响应文本一起看。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "转存一直失败的人")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()

    t0 = utcnow()
    worker.run_once(api_session, now=t0)                        # 第 1 次
    worker.run_once(api_session, now=t0 + timedelta(seconds=5))  # 第 2 次
    final = worker.run_once(api_session, now=t0 + timedelta(seconds=10))  # 第 3 次

    assert final.retried == [task["id"]], "最后一次要真的把状态推下去"
    row = _task_row(api_session, task["id"])
    assert row.transfer_attempts == 3
    assert row.status is TaskStatus.failed
    assert row.error_code == "TRANSFER_FAILED"
    assert row.transfer_state is TransferState.failed
    assert row.provider_url is None
    assert row.settled_amount is None, "失败不是「结算了 0 积分」"
    assert row.finished_at is not None

    account = await _account(api, headers)
    assert (account["balance"], account["frozen"]) == (50, 0), "全额退回"
    assert (await api.get("/assets", headers=headers)).json()["items"] == []

    detail = await api.get(f"/tasks/{task['id']}", headers=headers)
    assert detail.status_code == 200
    assert "file://" not in detail.text
    assert "provider_url" not in detail.text
    raw_assets = (await api.get("/assets", headers=headers)).text
    assert "file://" not in raw_assets


async def test_死在转存中途的孤儿任务_会被兜底捡回来(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """⚠️ 评审 H1：`transfer_state = running` 也必须被捡。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【这条防的是什么】

    状态是在 IO **之前**写成 `running` 的。进程如果在那一刻死了
    （部署重启、容器被杀），库里就留下一条 `running` 的任务 ——
    而它**不被任何相位匹配**：公开状态是 `submitted` 但 provider
    那边早给过结果了（`poll` 问不出新东西），而重试相位如果只看
    `failed` 就会漏掉它。结果是积分冻到一小时超时。

    所以筛选条件里必须有 `running`。这条用例把 `running` 从条件里
    拿掉就变红 —— 那正是「兜底」这个词该有的验收方式。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    scripted.polls_before_done = 99   # ② 永远问不出结果 → 只有 ②.5 能救
    headers, _ = await new_user(api, "进程挂过的人")
    task = (await submit_image(api, headers, idempotency_key="k1")).json()
    assert task["status"] == "submitted"

    product = get_settings().provider_spool_root_ready / "generated" / "orphan.png"
    render_image(1024, 1024, (3, 4, 5), product)
    with atomic(api_session):
        row = api_session.get(Task, task["id"])
        assert row is not None
        row.transfer_state = TransferState.running
        row.provider_url = product.as_uri()

    report = worker.run_once(api_session, now=utcnow() + timedelta(seconds=5))

    assert report.advanced == [], "② 那条路拿不到东西（替身的回执还没好）"
    assert report.retried == [task["id"]]

    row = _task_row(api_session, task["id"])
    assert row.status is TaskStatus.succeeded
    assert row.transfer_state is TransferState.done

    account = await _account(api, headers)
    assert (account["balance"], account["frozen"]) == (46, 0)
    assert len((await api.get("/assets", headers=headers)).json()["items"]) == 1


async def test_出图产出的字节真的落在media_root_而且取得到(
    api: httpx.AsyncClient, api_session: Session
) -> None:
    """C6 的第一条验收：**产物真的是磁盘上的字节**（不是拼出来的 URL）。

    【为什么这条必须走完整条 HTTP 路】因为「文件在盘上」和
    「用户能通过 URL 拿到它」之间还有两件事：`StaticFiles` 挂没挂对、
    `public_url` 拼得对不对。只测前者的用例在后者坏掉时照样是绿的。
    """
    headers, _ = await new_user(api, "拿真作品的人")
    await submit_image(api, headers)

    items = (await api.get("/assets", headers=headers)).json()["items"]
    assert len(items) == 1
    asset = items[0]

    assert isinstance(asset["size_bytes"], int) and asset["size_bytes"] > 0
    assert (asset["width"], asset["height"]) == (1024, 1024)

    key = asset["public_url"].split("/media/", 1)[1]
    on_disk = get_settings().media_root_ready / key
    assert on_disk.is_file()
    assert on_disk.stat().st_size == asset["size_bytes"]

    served = await api.get(f"/media/{key}")
    assert served.status_code == 200, "点击作品打开是 404 —— public_url 与 StaticFiles 漂移了"
    assert served.content == on_disk.read_bytes()
    assert served.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_视频的封面是独立的一张_1280x720_的图(
    api: httpx.AsyncClient, api_session: Session
) -> None:
    """§11.2：作品列表读封面、点开才读正片。两张都要真的存在。"""
    headers, _ = await new_user(api, "看视频的人")
    upload_id = (await api.post(
        "/uploads/image",
        files={"file": ("ref.png", real_png(64, 64), "image/png")},
        headers=headers,
    )).json()["asset_id"]

    await submit_video(api, headers, source_asset_id=upload_id, idempotency_key="v1")

    items = (await api.get("/assets?page_size=50", headers=headers)).json()["items"]
    by_kind = {item["kind"]: item for item in items}
    cover = by_kind["thumbnail"]

    assert (cover["width"], cover["height"]) == (COVER_WIDTH, COVER_HEIGHT)
    assert cover["mime"] == "image/jpeg"
    assert cover["duration_sec"] is None, "封面是图，没有时长"
    assert by_kind["video"]["duration_sec"] == 6

    served = await api.get(f"/media/{cover['public_url'].split('/media/', 1)[1]}")
    assert served.status_code == 200
    assert served.content[:3] == b"\xff\xd8\xff", "封面得是 JPEG 字节"


def test_重跑转存不会留下一堆副本(paths: _Paths) -> None:
    """⚠️ 转存是**幂等**的：key 是确定性的，重跑等于重写。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这条重要】

    转存会重试（§9.3），而「重试」最自然的写法就是「再搬一次」。
    key 如果不是确定性的（比如带时间戳、带随机数），每重试一次
    就在存储里留一份几十 MB 的副本，而**资产表里只有一行** ——
    也就是说这些副本没有任何记录指向它们，永远不会被清理。
    一次部署重启就能让存储涨一倍。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    source = _put(paths.spool, "out.png", real_png(64, 64))

    first = transfer_artifact(
        task_id=5, kind=TaskKind.text_to_image, provider_url=source.as_uri()
    )
    second = transfer_artifact(
        task_id=5, kind=TaskKind.text_to_image, provider_url=source.as_uri()
    )

    assert [spec.storage_key for spec in first] == [spec.storage_key for spec in second]

    landed = sorted(
        p.relative_to(paths.media).as_posix() for p in paths.media.rglob("*") if p.is_file()
    )
    assert landed == ["t/5/out.png"], f"重跑留下了多余的文件：{landed}"
