"""测试用的小工具。**不是测试文件**（文件名不以 `test_` 开头，pytest 不收集它）。

【为什么值得单独一个文件，而不是在 conftest 里做夹具】
因为这些是**函数**，不是环境：注册一个用户、拿一组鉴权头、提交一次生成。
做成夹具的话，用例里会出现一堆「为了拿一个 token 而声明三个夹具」的噪音，
读起来反而不像一条验收剧本。
"""

from __future__ import annotations

import struct
import tempfile
import zlib
from pathlib import Path

import httpx

# 前端**全部**测试与浏览器剧本用的密码（`pw123456`）。
# 这里照抄：契约测试的价值就在于它跑的是同一组输入。
PASSWORD = "pw123456"
MOCK_INVITE = "MOCK"


async def register(
    client: httpx.AsyncClient,
    username: str,
    *,
    password: str = PASSWORD,
    invite_code: str = MOCK_INVITE,
) -> dict:
    """注册并返回完整会话 `{token, user, credit_account}`。

    【为什么它不自己 assert 状态码】因为有一半用例**故意**要注册失败
    （重名、无效邀请码）。要断言的那个用例自己断言 —— 这里替它断言的话，
    那些用例就得绕过这个函数、自己拼请求，而那样它们测的东西
    就和不失败的路径不是同一段代码了。
    """
    res = await client.post(
        "/auth/register",
        json={"invite_code": invite_code, "username": username, "password": password},
    )
    assert res.status_code == 201, f"注册失败：{res.status_code} {res.text}"
    return res.json()


def auth(token: str) -> dict[str, str]:
    """Bearer 头。写成函数是为了让每个用例都**不可能**忘了 `Bearer ` 前缀
    —— 忘了的表现是 401，而 401 在多数用例里看起来像「鉴权坏了」，
    会把人往错的方向带。"""
    return {"Authorization": f"Bearer {token}"}


async def new_user(client: httpx.AsyncClient, username: str) -> tuple[dict[str, str], dict]:
    """注册一个新用户，返回 `(请求头, 会话体)`。

    单独包一层是因为「注册 → 拿头 → 干正事」是这个仓库里出现最多的
    三步，而第三步才是用例真正想写的东西。
    """
    session = await register(client, username)
    return auth(session["token"]), session


async def grant_credits(
    client: httpx.AsyncClient, username: str, amount: int
) -> dict:
    """走 `/__test/grant` 补积分（写 `adjust` 流水）。

    【为什么不用「多注册几个用户来回转」】因为那测不了「余额很大时」
    的分支，而余额充足正是大多数生成用例的前提。
    """
    res = await client.post("/__test/grant", json={"username": username, "amount": amount})
    assert res.status_code == 200, f"发积分失败：{res.status_code} {res.text}"
    return res.json()


async def submit_image(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    prompt: str = "一只在屋顶上看夕阳的猫",
    idempotency_key: str = "k-image-1",
    aspect_ratio: str | None = "1:1",
) -> httpx.Response:
    """提交一次文生图，返回**原始响应**（用例自己看状态码）。"""
    body: dict = {"prompt": prompt, "idempotency_key": idempotency_key}
    if aspect_ratio is not None:
        body["aspect_ratio"] = aspect_ratio
    return await client.post("/generation/image", json=body, headers=headers)


async def submit_video(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    source_asset_id: int | str | None,
    prompt: str = "镜头缓慢推进，猫的耳朵动了一下",
    idempotency_key: str = "k-video-1",
    duration: int = 5,
    ratio: str | None = "16:9",
) -> httpx.Response:
    """提交一次图生视频。

    【`source_asset_id` 的默认值是 None】因为「没给参考图」是一条
    要单独测的失败路径，让它成为默认值，用例里就不必为了造那个
    请求而绕过这个 helper —— 那正是契约测试最容易漂移的地方。
    """
    body: dict = {
        "prompt": prompt,
        "idempotency_key": idempotency_key,
        "duration": duration,
    }
    if source_asset_id is not None:
        body["source_asset_id"] = source_asset_id
    if ratio is not None:
        body["ratio"] = ratio
    return await client.post("/generation/video", json=body, headers=headers)


# ══════════════════════════════════════════════════════════════
# B4：造两种「图」—— 真的，和**只是声称**的
# ══════════════════════════════════════════════════════════════


def _chunk(kind: bytes, data: bytes) -> bytes:
    """PNG 的一个块：长度 + 类型 + 数据 + CRC32。"""
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def mini_png(width: int, height: int) -> bytes:
    """一个**结构完整、数据是假的** PNG，只有 68 字节。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么需要它，而不是「渲一张真的大图」】

    因为它就是**炸弹的真实形状**：一个 68 字节的文件，声称自己
    6 万 × 6 万像素。谁拿 `.size` 去信它，后面某次解码就是一次
    内存炸弹（60000² × 3 字节 = 10.8 GB）。

    【为什么不能靠「渲一张 60000×60000 的真图」来测】
    因为渲它本身就要 10.8 GB 内存 —— 测试会先把自己炸掉。
    PNG 的尺寸写在 IHDR 里，而 `Image.open()` + `.size` **只读那一块**，
    所以「声明」和「数据」可以完全脱钩。要测的正是这一点。

    【为什么它必须是结构完整的（IHDR + IDAT + IEND）】
    只给 IHDR 的话 Pillow 会当成**截断**文件、报 `undecodable` ——
    那样它就走「解不出也收」那条宽松路径了，测不到想测的东西。
    多两个块（一个假的 IDAT + IEND）就让 Pillow 认为这是一张
    「读得出尺寸、只是数据是坏的」图。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 32))
        + _chunk(b"IEND", b"")
    )


def real_png(width: int, height: int, *, color: tuple[int, int, int] = (17, 34, 51)) -> bytes:
    """渲一张**真的** PNG 并返回字节。

    【为什么走 `transcode.render_image` 而不是在测试里 `import PIL`】
    因为「Pillow 的调用点只有 `transcode.py` 一个」是 B4 定的规矩。
    测试自己 `import PIL` 的话，那条规矩第一个被违反的地方就是测试，
    而它接下来会一路松掉。顺带：渲出来的字节是真的能解码的，
    所以「探针读的是真尺寸」这件事在测试里是可证的。
    """
    from app.services.transcode import render_image

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "real.png"
        render_image(width, height, color, dest)
        return dest.read_bytes()


def real_jpeg(width: int = 1280, height: int = 720) -> bytes:
    """一张**真的** JPEG。走 `placeholder_cover` —— 同样是「Pillow 只有一个落点」。

    【为什么要 JPEG 而不是复用 PNG】因为上传接口里有一条分支是
    「客户端没给 Content-Type 时，用**探出来的**格式兜底」。
    拿 PNG 测它的话，兜底值恰好也等于写死的那句 `image/png`，
    用例就会因为一个与它无关的原因变绿。
    """
    from app.services.transcode import placeholder_cover

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "real.jpg"
        placeholder_cover(dest, width=width, height=height)
        return dest.read_bytes()
