"""`LocalStorage` —— 字节怎么落、key 逃不出去。§12.2 / §9.2。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【B2 测的是「名字怎么算」，这个文件测的是「字节怎么落」】

`reference_image_key` / `generated_asset_key` / `public_url_for` 是策略，
B2 已经用 URL 形状钉住了。B4 加进来的是一个**实现**：

  `media_root` ← `_safe_path()` ← `key` ← `_atomic_write()` → 磁盘

这个文件只碰这一层，不经过 HTTP —— 于是红了的时候，「是存储坏了」
和「是路由/业务坏了」不会混在一条报错里。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.services.storage import build_storage, public_url_for


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """一个把 `MEDIA_ROOT` 钉在临时目录上的存储。

    【为什么必须清配置缓存】`get_settings()` 带 `lru_cache`，不清的话
    拿到的是**上一个用例**那份配置 —— 于是字节会写进别人的目录，
    而断言看起来只是「文件没找到」。conftest 里 `api_app` 那段
    说的是同一件事。
    """
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    get_settings.cache_clear()
    yield build_storage(), tmp_path / "media"
    get_settings.cache_clear()


# ── 写与读 ────────────────────────────────────────────────────


def test_写进去再读出来_字节一模一样(store) -> None:
    storage, root = store

    storage.put_bytes("t/7/out.png", b"\x89PNG\r\n\x1a\nhello")

    assert storage.exists("t/7/out.png")
    assert storage.read_bytes("t/7/out.png") == b"\x89PNG\r\n\x1a\nhello"
    assert (root / "t/7/out.png").read_bytes() == b"\x89PNG\r\n\x1a\nhello"


def test_key_里的分层目录会被自动建出来(store) -> None:
    """`t/{task_id}/...` 这种 key 的中间层目录**不预先存在**。

    【为什么这条要单独测】`config.py` 只建了 `media_root` 本身
    （`media_root_ready`）。不建中间层的话，第一次写产物会报
    `FileNotFoundError` —— 而那个错误长得像「磁盘满了」或「权限不对」，
    排查方向完全错。
    """
    storage, root = store

    storage.put_bytes("u/1/2/deep/deeper/file.png", b"x")

    assert (root / "u/1/2/deep/deeper/file.png").is_file()


def test_put_file_搬一份已经存在的文件(store, tmp_path: Path) -> None:
    """`put_file` 是转存与上传共用的那条路（几十 MB 的产物不能经过内存）。"""
    storage, root = store
    source = tmp_path / "artifact.mp4"
    source.write_bytes(b"fake-mp4-bytes" * 100)

    storage.put_file("t/3/out.mp4", source)

    assert (root / "t/3/out.mp4").read_bytes() == source.read_bytes()
    assert source.is_file(), "搬走不等于删掉源文件"


def test_重复写同一个_key_是覆盖而不是追加(store) -> None:
    """重试转存会写到同一个 key 上（key 是确定性的）。

    追加的话，第二次的产物是一段「前半截是旧图、后半截是新图」的垃圾，
    而它的文件名和记录都完全正常 —— 用户看到的是一张坏图，
    查起来要一路查到文件内容才看得出来。
    """
    storage, _ = store

    storage.put_bytes("t/1/out.png", b"first-and-longer")
    storage.put_bytes("t/1/out.png", b"second")

    assert storage.read_bytes("t/1/out.png") == b"second"


def test_写完不留临时文件(store) -> None:
    """`_atomic_write` 的临时名不能留下来。

    【为什么值得断言】临时文件落在**目标目录里**（那是跨卷
    `os.replace` 会抛 EXDEV 换来的必然结果），而目标目录就是
    被 `StaticFiles` 发布出去的 `media_root`。残留物会表现为
    「作品页里多出几个打不开的同名文件」，而没人会想到那是
    「写的时候的中间产物」。
    """
    storage, root = store

    storage.put_bytes("t/9/out.png", b"bytes")

    leftovers = [p.name for p in root.rglob("*") if p.is_file() and p.name != "out.png"]
    assert leftovers == [], f"留下了中间产物：{leftovers}"


def test_delete_不存在的对象不报错(store) -> None:
    """`delete` 要幂等 —— 作者说「对象不存在不算错」（见 Protocol 里的说明）。

    删资产那条路（`assets.delete_asset`）是「先 commit 删行、再
    best-effort 删对象」。删对象这一步报错的话，用户的删除请求会变成
    一次失败，而**行已经删了** —— 一个「失败了但其实成功了」的接口。
    """
    storage, _ = store

    storage.delete("t/404/nothing.png")  # 不抛就算过

    storage.put_bytes("t/5/out.png", b"x")
    storage.delete("t/5/out.png")
    assert not storage.exists("t/5/out.png")
    storage.delete("t/5/out.png")  # 再删一次，仍然不抛


# ── key 的边界 ────────────────────────────────────────────────


def test_带上级目录的_key_逃不出media_root(store) -> None:
    """⚠️ 安全性质：key 里既有用户文件名、也有 task_id，是唯一的注入面。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这只在 B4 才成为一个真问题】

    B2 的 key 只是**拼进 URL** 的字符串，落不到盘上 —— 一个 `../`
    最多让 URL 难看。B4 起它要被拼成**磁盘路径**，于是同一个字符
    变成「写到 media_root 之外」。

    【为什么这条即使上游已经洗过文件名也必须有】
    因为洗的地方（`_safe_filename`）和拼的地方（`_safe_path`）是
    两个函数、两个文件。将来任何一处新增的调用方绕过前者，
    后者就是最后一道门。防御性问题上的「上游已经做过了」不是理由。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    storage, _ = store

    for bad in ("../escape.txt", "a/../../escape.txt", "./../escape.txt"):
        with pytest.raises(ValueError, match="逃出了"):
            storage.put_bytes(bad, b"nope")

    assert not (store[1].parent / "escape.txt").exists()


def test_绝对路径的_key_也逃不出去(store, tmp_path: Path) -> None:
    """Windows 上 `Path(root) / "C:/Windows/x"` 会**丢掉 root**（绝对路径赢）。

    【为什么字符串检查 `".." in key` 在这里是无效的】
    这一条里根本没有任何 `..`。只查那三个字符的实现会放它过去，
    然后它写进系统目录 —— 而 str 前缀比较也挡不住它，
    因为那时路径压根不以 media_root 开头。
    """
    storage, _ = store
    outside = tmp_path / "outside.png"

    with pytest.raises(ValueError, match="逃出了"):
        storage.put_bytes(str(outside), b"nope")

    assert not outside.exists()


def test_url_for_与_public_url_for_是同一个答案(store) -> None:
    """存储实现换了（B7 换 OSS），**这个 URL 的形状不许变**。

    它是契约：`public_base_url` + `/media/` + key。而 `main.py` 里挂的
    `StaticFiles` 必须挂在同一个前缀上 —— 两处漂移的表现是
    「上传成功但预览 404」。
    """
    storage, _ = store

    key = "u/5/9/cat.png"

    assert storage.url_for(key) == public_url_for(key)
    assert storage.url_for(key).endswith("/media/u/5/9/cat.png")


def test_leading_slash_的_key_不会逃出去(store) -> None:
    """`public_url_for` 会 `lstrip("/")`，存储层要能接受同一个形状。

    【为什么这条不是凑数】两个入口（上传与产物）传的 key 都是
    `u/…` / `t/…` 这种没有前导斜杠的；但 URL 里那个是带前缀的。
    将来有人把 URL 拆回来当 key 用的时候，一个 `/media/u/1/x`
    会以 `/` 打头 —— 在 POSIX 上那是绝对路径（`Path("/")` 会赢），
    在 Windows 上则被当成「当前盘根」。两种都不该发生。
    """
    storage, root = store

    storage.put_bytes("/t/2/out.png", b"ok")

    assert (root / "t/2/out.png").read_bytes() == b"ok"
