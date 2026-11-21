"""上传参考图 —— B4 的「字节真的落盘」那一段。§9.4 / §12.1。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【B2 的上传测试测的是契约（状态码、字段、上限），这里测的是**字节**】

B2 时上传的实现量完字节就把它们丢掉了（注释自己写着「只为了量出
大小」），所以 `public_url` 背后什么都没有 —— 打开是 404。
B4 起它落进 `media_root`，于是「上传成功」第一次意味着
「服务器上真的有一份」。

⚠️ 本文件的多数用例的**输入是垃圾字节**（PNG 魔数 + 填充、1024 个 NUL），
而它们**必须被收下**。那是用户拍板的口径，理由见
`test_非图片字节也照收` 里那段 —— 简单说：冻结前端的契约测试
传的就是这种东西，严格校验会让跨仓门禁因为**夹具**而变红。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import httpx
import pytest

from _helpers import mini_png, new_user, real_jpeg, real_png
from app.config import get_settings

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def _upload(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    payload: bytes,
    filename: str = "ref.png",
    content_type: str | None = "image/png",
) -> httpx.Response:
    file: tuple = (filename, payload) if content_type is None else (filename, payload, content_type)
    return await api.post("/uploads/image", files={"file": file}, headers=headers)


def _key_of(public_url: str) -> str:
    """从 `public_url` 里拆出 storage key。

    【为什么用拆 URL 而不是「自己拼一遍 key」】因为被测的正是
    「`public_url` 指向的那个文件真的存在」—— 自己拼一遍的话，
    拼错了也照样绿（两边用同一个错误公式）。
    """
    return public_url.split("/media/", 1)[1]


def _asset(api_response_body: dict, asset_id: int) -> dict:
    items = api_response_body["items"]
    return next(item for item in items if item["id"] == asset_id)


# ── 落盘 ──────────────────────────────────────────────────────


async def test_上传的字节真的落在media_root里(api: httpx.AsyncClient) -> None:
    """⚠️ B4 的第一条验收：磁盘上真的有一份，且与请求里的字节一致。"""
    headers, _ = await new_user(api, "传字节的人")
    payload = PNG_MAGIC + b"x" * 64

    body = (await _upload(api, headers, payload=payload)).json()

    on_disk = get_settings().media_root_ready / _key_of(body["public_url"])
    assert on_disk.is_file(), "上传成功但盘上什么都没有 —— public_url 又是一张空头支票"
    assert on_disk.read_bytes() == payload


async def test_media_地址能取到一模一样的字节_而且带_nosniff(
    api: httpx.AsyncClient,
) -> None:
    """C6 的「公网可访问」在本地存储下的等价物。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么还要断言 `X-Content-Type-Options`】

    因为 `/media` 下面放的是**用户上传的字节**：一个 `text/html`
    的伪装文件被浏览器按 HTML 执行，就是一次存储型 XSS。而浏览器
    其实是以**内容**嗅探类型的，所以这条头是关掉嗅探的唯一方式。

    它在这一层特别要紧：本地存储下这些都是静态文件，
    没有任何一处业务代码会「检查」它们。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "取字节的人")
    payload = PNG_MAGIC + b"y" * 100
    body = (await _upload(api, headers, payload=payload)).json()

    res = await api.get(f"/media/{_key_of(body['public_url'])}")

    assert res.status_code == 200
    assert res.content == payload
    assert res.headers.get("x-content-type-options") == "nosniff"


async def test_删掉资产_文件也一起删掉(api: httpx.AsyncClient) -> None:
    """§9.4 给了删除权，就该真的删 —— 包括存储上的那一份。

    【顺序为什么必须是「先删行、再删文件」】反过来（先删文件再提交）的话，
    一次提交失败就留下「行还在、文件没了」—— 用户点开自己的作品
    是一张裂图，而列表里它明明还在。反过来（先删行）最坏的后果是
    留一个孤儿文件，而那不影响用户看到的东西。
    """
    headers, _ = await new_user(api, "删东西的人")
    body = (await _upload(api, headers, payload=PNG_MAGIC + b"z" * 32)).json()
    on_disk = get_settings().media_root_ready / _key_of(body["public_url"])
    assert on_disk.is_file()

    res = await api.delete(f"/assets/{body['asset_id']}", headers=headers)

    assert res.status_code == 200, res.text
    assert not on_disk.exists(), "行删了、文件还在 —— 存储会一直涨"
    assert (await api.get("/assets", headers=headers)).json()["items"] == []


# ── 探针 ──────────────────────────────────────────────────────


async def test_真图能读出宽高(api: httpx.AsyncClient) -> None:
    """B4 起宽高来自真实字节（B2 时恒为 None）。"""
    headers, _ = await new_user(api, "传真图的人")

    body = (await _upload(api, headers, payload=real_png(640, 480))).json()
    asset = _asset((await api.get("/assets", headers=headers)).json(), body["asset_id"])

    assert (asset["width"], asset["height"]) == (640, 480)
    assert asset["mime"] == "image/png"


async def test_没带类型时_用探出来的格式(api: httpx.AsyncClient) -> None:
    """客户端既没给 Content-Type、我们又能从字节里认出格式 → 用认出来的。

    【为什么比写死的 `image/png` 好】一张真的 JPEG 被记成 PNG，
    前端按 mime 分支的地方会走错路。这条兜底只在**两边都不给**
    的时候生效（正常客户端总会带一个）。
    """
    headers, _ = await new_user(api, "不发类型的人")

    body = (await _upload(api, headers, payload=real_jpeg(), content_type="")).json()
    asset = _asset((await api.get("/assets", headers=headers)).json(), body["asset_id"])

    assert asset["mime"] == "image/jpeg"


async def test_声明边长超限的图被拒(api: httpx.AsyncClient) -> None:
    """⚠️ §9.4 的「≤4096×4096」——**宽松口径里唯一硬的地方**。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么这条不能被「解不出也收」吞掉】

    因为那样一来，宽松口径就有了一个很显然的滥用方式：
    把一张 20MB 以内、声称 6 万 × 6 万像素的 PNG 伪装成
    「解不出来」。它会被存下来、发布出去，然后在**任何一次**
    后续解码里炸掉某个进程。

    所以「解不出」和「太大」必须是两个结论：读得出尺寸的，就按尺寸管。

    下面两个样本各 68 字节，走**两条不同的代码路径**（边长比较 /
    Pillow 的炸弹保护）—— 见 `_helpers.mini_png`。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "想传大图的人")

    for width, height in ((5000, 5000), (60000, 60000)):
        res = await _upload(api, headers, payload=mini_png(width, height))
        assert res.status_code == 400, f"{width}x{height} 被放行了：{res.text}"
        assert res.json()["code"] == "IMAGE_TOO_LARGE"


async def test_正好到边长上限的图能过(api: httpx.AsyncClient) -> None:
    """边界是**含**的（`> 4096` 才拒），和 20MB 那条一样。"""
    headers, _ = await new_user(api, "卡边界的人")

    res = await _upload(api, headers, payload=mini_png(4096, 4096))

    assert res.status_code == 200, res.text


async def test_非图片字节也照收(api: httpx.AsyncClient) -> None:
    """⚠️ **用户拍板的口径**，用一条用例把它钉在这里。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【为什么是「照收」而不是「拒绝」】

    冻结前端的契约测试里，参考图传的就是
    `List<int>.filled(1024, 0)` —— 1024 个 NUL
    （`test/live_backend.dart:772`、`test/repository_layer_test.dart:194,297`）。
    严格校验会让**跨仓门禁**变红，而那个红来自夹具、不来自契约 ——
    也就是说它会把一次正确的实现判成错的。

    【代价记在案】对这类文件，§9.4 的 ≤4096 不执行（没有尺寸可查）。
    见 HANDOFF 的缺口表。这条用例同时钉住了「代价」的样子：
    宽高是 None，文件照样落盘。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, "传空字节的人")
    payload = bytes(1024)

    body = (await _upload(api, headers, payload=payload, filename="ref.png")).json()
    asset = _asset((await api.get("/assets", headers=headers)).json(), body["asset_id"])

    assert asset["width"] is None and asset["height"] is None
    assert asset["size_bytes"] == len(payload)
    assert asset["kind"] == "image", "用户说要传参考图，就按参考图收"
    assert (get_settings().media_root_ready / _key_of(body["public_url"])).read_bytes() == payload


# ── 安全 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("filename", ["../../../etc/passwd", "..\\..\\windows\\win.ini", ".."])
async def test_文件名里的穿越不会让文件跑出media_root(
    api: httpx.AsyncClient, filename: str
) -> None:
    """⚠️ 安全性质：multipart 的 filename **完全由客户端控制**。

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    【B2 只测了 URL，B4 必须测磁盘】

    B2 里这个名字最多让 URL 难看（背后没有文件）。B4 起它会被拼成
    磁盘路径 —— 不洗的话，一个普通用户就能写到服务器上的任意位置，
    那是上传接口的经典漏洞。

    三种形状都要试：POSIX 的 `../`、Windows 的反斜杠、以及裸的 `..`
    （最后这个最容易漏：洗完之后剩下一个「上级目录」，而它正好是
    一个合法的路径片段）。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
    headers, _ = await new_user(api, f"想穿越的人{len(filename)}")

    res = await _upload(api, headers, payload=PNG_MAGIC + b"q" * 16, filename=filename)

    assert res.status_code == 200, res.text
    media = get_settings().media_root_ready
    on_disk = (media / _key_of(res.json()["public_url"])).resolve()
    assert on_disk.is_relative_to(media.resolve()), f"文件落到了 media_root 之外：{on_disk}"
    assert on_disk.is_file()
