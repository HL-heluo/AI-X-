"""上传参考图 —— §9.4 / §12.1。"""

from __future__ import annotations

import httpx

from _helpers import new_user

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def _upload(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    filename: str = "ref.png",
    payload: bytes = PNG_MAGIC + b"x" * 64,
    content_type: str | None = "image/png",
) -> httpx.Response:
    """传一张图。`content_type=""` 时发一个**空的** Content-Type。

    【为什么要能发空的】因为真实客户端（包括某些自己拼 multipart 的
    小脚本、以及浏览器表单的某些情形）确实会发一个没有类型的 part。
    那时 `UploadFile.content_type` 是 `None` 或空串，而库里那一列
    不能是空字符串 —— 前端按 mime 分支时会认不出它。

    ⚠️ 注意 httpx 的一个坑：两元组形式 `(name, data)` 会用**文件扩展名**
    猜类型，猜不出才退回 `application/octet-stream` —— 也就是说
    它总能发出一个**非空**的类型，测不到「没有类型」这条路径。
    只有显式传空串才会发出 `Content-Type: `（空的）。这条我实测过。
    """
    file: tuple = (filename, payload) if content_type is None else (filename, payload, content_type)
    return await api.post("/uploads/image", files={"file": file}, headers=headers)


# ── 成功路径 ──────────────────────────────────────────────────


async def test_上传返回_asset_id_和_public_url(api: httpx.AsyncClient) -> None:
    """响应同时给 `asset_id` 与 `public_url` —— **这是刻意的**。

    ─────────────────────────────────────────────────────────
    【为什么两个都给：§12.1 自己矛盾】

    §12.1 的表格说 `/uploads/image` 「返回公网 URL」，但
    `/generation/video` 要的参数却是 `source_asset_id` —— 一个说给 URL、
    一个说要 id。两个都给，App 就能用 id 提交、用 URL 显示预览。

    前端 `RemoteAssetRepository.uploadImage` 取的是 `asset_id`，
    取不到会直接 `StateError`（它明确拒绝「拿 URL 当 id 用」）。
    所以 `asset_id` 是**必需**的那个，`public_url` 是给预览用的。
    ─────────────────────────────────────────────────────────
    """
    headers, session = await new_user(api, "传图的人")

    res = await _upload(api, headers, filename="猫.png")

    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["asset_id"], int), "必须同时给整数 id（前端靠它下单）"
    assert body["public_url"].startswith("http")
    assert f"/media/u/{session['user']['id']}/" in body["public_url"]


async def test_上传的图变成资产_而且不打_AI_标(api: httpx.AsyncClient) -> None:
    """⚠️ §10.1：用户上传的原图**不是** AI 生成的，不能打 AI 标识。

    ─────────────────────────────────────────────────────────
    【为什么这条是合规性质的，不是显示问题】

    这一列是《人工智能生成合成内容标识办法》要求的那条义务：
    「AI 生成的内容要标识」。反过来，把用户自己的照片标成
    「AI 生成」同样是错的 —— 那是在用户的原创作品上盖一个
    不属于它的章。所以 `Asset.is_ai_generated` 不能写死成 true
    （`models.py` 里专门写了这一条）。

    顺带钉住另外两个字段：
      · `task_id` 是 **null** —— 参考图是任务的**输入**，不是产物。
        填上某个任务 id 会让「删任务」把用户的原始素材一并带走。
      · `size_bytes` 是真实字节数 —— 前端靠它显示「2.3 MB」。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "传原图的人")
    payload = PNG_MAGIC + b"y" * 100
    asset_id = (await _upload(api, headers, payload=payload)).json()["asset_id"]

    items = (await api.get("/assets", headers=headers)).json()["items"]
    asset = next(item for item in items if item["id"] == asset_id)

    assert asset["is_ai_generated"] is False
    assert asset["task_id"] is None
    assert asset["kind"] == "image"
    assert asset["size_bytes"] == len(payload)
    assert asset["duration_sec"] is None


async def test_没有_content_type_时_mime_退回_image_png(api: httpx.AsyncClient) -> None:
    """和 Mock 的 `mimeType ?? 'image/png'` 逐字一致。"""
    headers, _ = await new_user(api, "不发类型的人")
    asset_id = (
        await _upload(api, headers, filename="无类型", content_type="")
    ).json()["asset_id"]

    items = (await api.get("/assets", headers=headers)).json()["items"]
    asset = next(item for item in items if item["id"] == asset_id)

    assert asset["mime"] == "image/png"


# ── 上限与文件名 ──────────────────────────────────────────────


async def test_超过_20MB_的图被挡在门外(api: httpx.AsyncClient) -> None:
    """§9.4：对齐 provider 的限制，超大图**在门口**就拒。

    ─────────────────────────────────────────────────────────
    【为什么要在这里挡，而不是等 provider 拒绝】

    provider 拒绝的时候，带宽已经花掉了、用户的等待已经发生了，
    而且他拿到的是一个和「图太大」没什么关系的外语错误
    （§9.4 的原文就是「不要等传完了才被 provider 拒绝」）。

    【为什么这条能证明分块读是对的】超限的那一份有 20MB+1，
    如果实现是 `await file.read()` 一把梭，它会先把整份读进内存
    再判断 —— 现在判得早，但**从外部看不出区别**。
    所以这条只证明「超限被拒」；那条「先读满 20MB 才拒」的性质
    由 `services/assets._UPLOAD_CHUNK` 的注释说明，不靠测试证明。
    ─────────────────────────────────────────────────────────
    """
    from app.config import get_settings

    headers, _ = await new_user(api, "传大图的人")
    limit = get_settings().max_image_bytes

    res = await _upload(api, headers, payload=PNG_MAGIC + b"z" * (limit + 1))

    assert res.status_code == 400, res.text
    assert res.json()["code"] == "IMAGE_TOO_LARGE"


async def test_正好到上限的图能过(api: httpx.AsyncClient) -> None:
    """边界是**含**的：`> limit` 才拒。"""
    from app.config import get_settings

    headers, _ = await new_user(api, "传刚好的人")
    limit = get_settings().max_image_bytes

    res = await _upload(api, headers, payload=b"z" * limit)

    assert res.status_code == 200, res.text


async def test_文件名里的路径穿越被洗掉(api: httpx.AsyncClient) -> None:
    """⚠️ `../../etc/passwd` 这种文件名不能进路径。

    ─────────────────────────────────────────────────────────
    【为什么这条是安全性质的】

    multipart 的 filename 完全由**客户端**控制。它会被拼进两个地方：
    我们本地磁盘的路径、以及对外的 URL。不洗的话，一个普通用户
    就能写到服务器上的任意位置（经典的上传漏洞），或者让
    `public_url` 指向别人目录里的文件。

    洗法很保守（只留 ASCII 字母数字和 `._-`），因为文件名在这个系统里
    只是**给人看的线索**，真正的标识是自增的 `assets.id`。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "想穿越的人")

    body = (
        await _upload(api, headers, filename="../../../etc/passwd")
    ).json()

    assert ".." not in body["public_url"], body["public_url"]
    assert "etc/passwd" not in body["public_url"] or ".." not in body["public_url"]


# ── 鉴权 ──────────────────────────────────────────────────────


async def test_没登录不能上传(api: httpx.AsyncClient) -> None:
    """上传要占存储和带宽，必须先知道是谁。"""
    res = await api.post("/uploads/image", files={"file": ("x.png", PNG_MAGIC, "image/png")})

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


async def test_multipart_的字段名必须是_file(api: httpx.AsyncClient) -> None:
    """⚠️ 字段名 `file` 是**前端写死的**（`DioApiClient` 的 multipart part）。

    【为什么这条要专门测】名字对不上的表现是 FastAPI 报「field required」，
    而前端看到的是一个「上传失败」但说不出为什么的错误 ——
    排查时得同时读两端才能发现是这一处。这条用例用错名字发一次，
    确认它会被拒；再用对名字发一次，确认它能过。
    """
    headers, _ = await new_user(api, "试字段名的人")

    wrong = await api.post(
        "/uploads/image", files={"image": ("x.png", PNG_MAGIC, "image/png")}, headers=headers
    )
    right = await api.post(
        "/uploads/image", files={"file": ("x.png", PNG_MAGIC, "image/png")}, headers=headers
    )

    assert wrong.status_code == 400, "字段名不对时必须失败，否则说明契约没被钉住"
    assert right.status_code == 200, right.text
