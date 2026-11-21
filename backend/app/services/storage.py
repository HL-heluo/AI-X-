"""对象存储 —— **名字怎么算**（B2）与**字节怎么落**（B4）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【B4 起这里真的有文件了】

B2 时 `public_url` 指向 `/media/...`，而背后**没有文件**（打开是 404，
与当时 Mock 的 `mock-oss.local` 行为一致）。B4 补上了字节，于是
那个 URL 第一次真的能被浏览器打开。

新增的是 `Storage` Protocol 和 `LocalStorage`（§12.2 的第二个 Protocol，
`providers/__init__.py` 里那句「另一个 Protocol 是 `Storage`」说的就是它）。
第 2 节那些 `*_key` 与 `public_url_for` **保持原样** —— 名字策略与
存储实现在 B4 里被拆开成两件事，换 OSS（B6）时改的是实现，不是名字。

【为什么 `put_*` 都写成「临时文件 + `os.replace`」】

因为 `StaticFiles` 是**并发读**的：它不是「等你写完再读」，而是
随时可能有人正在 GET 这个 URL。直接往目标路径写的话，那次 GET
会读到半个文件（一张只有上半截的图）。`os.replace` 在同一个卷内
是原子的，读的人要么看到旧文件、要么看到新文件。

它顺带解决第二个 Windows 特有的问题：重试覆盖时，如果那个文件
正被读者打开，直接写会拿到一个共享冲突错误。`replace` 不会。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import get_settings

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LEN = 80


def _safe_filename(filename: str) -> str:
    """把客户端给的文件名洗成一个能安全放进路径的片段。

    ─────────────────────────────────────────────────────────
    【为什么不能直接用它】

    这个字符串来自**用户**（`multipart` 的 filename），而它会被拼进
    两种地方：我们本地磁盘的路径、以及对外的 URL。两类真实的事故：

      · `../../etc/passwd` —— 路径穿越。上传接口的经典漏洞，
        表现是「一个普通用户能覆盖服务器上的任意文件」。
      · `发票 2026-10.pdf` —— 中文和空格进 URL 要百分号编码，
        不编码就是一个 404 或一个被截断的键名（§4 记着同类教训：
        GBK 区域编码下中文进配置文件会让工具直接崩）。

    洗法保守：只留 ASCII 字母数字和 `._-`，其余一律换成 `_`。
    文件名在这个系统里只是**给人看的线索**，不是一个需要保真的标识
    —— 真正的标识是自增的 `assets.id`。
    ─────────────────────────────────────────────────────────
    """
    cleaned = _SAFE_NAME.sub("_", filename).strip("._") or "file"
    return cleaned[:_MAX_NAME_LEN]


def public_url_for(storage_key: str) -> str:
    """storage_key → 对外的永久地址。

    【为什么路径前缀是写死的 `/media`】它和 `app/main.py` 里挂的
    `StaticFiles` 必须是同一个字符串。写成两处常量会漂移，
    而漂移的表现是「上传成功但预览 404」。
    """
    settings = get_settings()
    return f"{settings.public_base_url}/media/{storage_key.lstrip('/')}"


def reference_image_key(user_id: int, asset_id: int, filename: str) -> str:
    """用户上传的参考图。

    按 `u/{user_id}/...` 分层，是为了让「删一个用户」在存储层也是
    一次前缀删除，而不是去全表找他的文件。
    """
    return f"u/{user_id}/{asset_id}/{_safe_filename(filename)}"


def generated_asset_key(task_id: int, name: str) -> str:
    """平台产出的文件（正片 / 缩略图）。

    【为什么要分开放】因为「用户上传的东西」和「我们生成的东西」
    在合规上不是一回事：§10.1 要求 AI 生成内容带隐式标识，
    而用户上传的原图**不带**。按前缀分开，将来要做元数据批处理时
    就有了一个准确的筛选条件。
    """
    return f"t/{task_id}/{name}"


# ══════════════════════════════════════════════════════════════
# B4：Storage Protocol 与它的本地实现
# ══════════════════════════════════════════════════════════════


@runtime_checkable
class Storage(Protocol):
    """§12.2 的第二个 Protocol。**调用方只认这五个方法。**

    【为什么不用一个「base_url + 前缀」的简单抽象】
    因为 OSS 与本地盘真正的差别不在地址怎么拼，而在**写入**：
    本地是一次 `os.replace`，OSS 是一次分片上传 + 可能的分片续传。
    把 `put_file` 放进 Protocol，B6 换 OSS 时调用方（`assets.py` /
    `transfer.py`）一行不改 —— 这正是 §12.2 把它们收成 Protocol 的意义。
    """

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        """写一段字节。"""
        ...

    def put_file(self, key: str, source: Path, *, content_type: str | None = None) -> None:
        """把一个**已经落盘的文件**搬进去。

        【为什么要有它，而不是「读出来再 put_bytes」】因为产物可能是
        一段几十 MB 的视频：读进内存再写出去等于平白多占一份内存，
        而这份内存在并发转存时会相乘。
        """
        ...

    def read_bytes(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None:
        """删对象。**对象不存在不算错** —— 参见 `assets.delete_asset`。"""
        ...

    def exists(self, key: str) -> bool: ...

    def url_for(self, key: str) -> str:
        """对外的**永久**地址（B6 换成 OSS 的 CDN 地址）。"""
        ...


class LocalStorage:
    """`STORAGE=local`：文件落在 `settings.media_root`，由 `/media` 静态挂载出去。

    【它的对外行为与 OSS 一样吗】一样，这正是 §12.2 敢先做本地的原因：
    调用方拿到的仍然是一个**永久可读、不带鉴权**的 URL。差别只在
    谁能读到它（本地盘只有这个进程能写）。
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        # 【为什么在构造时就 resolve】后面每次包含性比较都要用它，
        # 而 `resolve()` 会碰文件系统。构造一次即可 —— 但它也意味着
        # **这个对象不该被跨目录改名使用**。测试里换个 MEDIA_ROOT 就会
        # 造一个新的 LocalStorage（`build_storage()` 每次都按配置现造）。
        self._resolved_root = root.resolve()

    # ── 路径 ───────────────────────────────────────────────

    def _safe_path(self, key: str) -> Path:
        """key → 本地绝对路径。**key 不许逃出 root。**

        ─────────────────────────────────────────────────────────
        【为什么 `resolve()` + `is_relative_to`，而不是检查 ".." 】

        因为 key 的来源不止一处：上传的文件名（用户可控）、
        `t/{task_id}/...`（我们自己拼）。检查 `".." in key` 看似够用，
        但它挡不住 Windows 的 `C:/Windows/...` 这种**绝对路径**，
        也挡不住符号链接指向别处。

        `resolve()` 把这两种都抹平（绝对路径会脱离 root、
        符号链接会被展开成真身），然后按**路径**比较父子关系 ——
        字符串前缀比较在这里是错的：`/media-evil` 也以 `/media` 开头。
        ─────────────────────────────────────────────────────────
        """
        candidate = (self._resolved_root / key.lstrip("/")).resolve()
        if candidate != self._resolved_root and not candidate.is_relative_to(
            self._resolved_root
        ):
            raise ValueError(f"storage key 逃出了 media_root：{key!r}")
        return candidate

    # ── 写 ─────────────────────────────────────────────────

    def _atomic_write(self, dest: Path, write: Callable[[Path], None]) -> None:
        """先在**同目录**写临时文件，再 `os.replace` 顶上去。

        【为什么临时文件必须在同一个目录，而不是系统临时目录】
        因为 `os.replace` 只在**同一个卷**内是原子的（跨卷要退化成
        复制+删除，那就没有原子性了）。本机的系统临时目录在 `C:`，
        而 `MEDIA_ROOT` 在 `G:` —— 跨卷时 `os.replace` 直接抛 `EXDEV`，
        表现是「所有生成都失败，而错误信息里全是 C 和 G 两个盘符」。
        ─────────────────────────────────────────────────────────
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-", suffix=dest.suffix)
        os.close(fd)  # 拿到名字就够了；下面的 write 自己开文件
        tmp = Path(tmp_name)
        try:
            write(tmp)
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        # `content_type` 在本实现里用不上（HTTP 头由 StaticFiles 按扩展名猜），
        # 但它是 Protocol 的一部分：OSS 要它来设 Content-Type。留着，
        # 免得 B6 换实现时才发现调用方两处都忘了传。
        del content_type
        self._atomic_write(self._safe_path(key), lambda tmp: tmp.write_bytes(data))

    def put_file(self, key: str, source: Path, *, content_type: str | None = None) -> None:
        del content_type
        self._atomic_write(self._safe_path(key), lambda tmp: shutil.copyfile(source, tmp))

    # ── 读 / 删 ────────────────────────────────────────────

    def read_bytes(self, key: str) -> bytes:
        return self._safe_path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._safe_path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._safe_path(key).is_file()

    def url_for(self, key: str) -> str:
        return public_url_for(key)


class S3Storage:
    """`STORAGE=oss`：走 **S3 协议**（boto3）。

    ─────────────────────────────────────────────────────────
    【为什么是 S3 协议，而不是「阿里云 OSS SDK」或「腾讯云 COS SDK」】

    因为这三家（外加 MinIO、Ceph、Cloudflare R2）说的是同一个协议。
    换成某一家的专有 SDK 之后，「换个云厂商」就不再是一次配置改动，
    而是一次**代码改动 + 重新发版 + 重新验证**——而它们之间唯一的
    差别其实只是 `endpoint_url` 和 `addressing_style`。

    代价是官方文档里的某些高级特性（分片续传的断点记录、
    bucket 级别的策略 API）用起来要绕路。v1 用不上它们。
    ─────────────────────────────────────────────────────────
    """

    def __init__(self, *, bucket: str, public_base_url: str, client: object) -> None:
        """`client` 是**注入**的。

        【为什么不让它自己 `boto3.client(...)`】因为那样这个类就没法测 ——
        而「能不能测」在这里不是洁癖：S3 的四个失败形态（键不存在、
        桶不存在、权限不足、网络超时）各自要走一条不同的分支，
        真桶验不了前三条（谁会为了跑测试去删一个桶）。
        """
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")
        self._client = client

    # ── 写 ─────────────────────────────────────────────────

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def put_file(self, key: str, source: Path, *, content_type: str | None = None) -> None:
        """把一个已落盘的文件传上去。

        ⚠️ **这里是单次 PUT，不是分片上传。** 分片上传能断点续传，
        而我们没有用它，理由是：产物上限 200MB（`max_artifact_bytes`）
        远在单次 PUT 的 5GB 上限之内，而**重试已经在 §9.3 那一层了**
        （`transfer_max_retries`，失败的搬运整条重来）。
        两处都做续传的话，读的人要在两个地方分别理解「传到第几片了」。

        留一句：真出现「200MB 传到 99% 断了要重头来」成为常态的那天，
        `upload_file` 就是替换点 —— 而那要先有证据（`provider_calls`
        里的重试率）说它真的是常态。
        """
        extra = {"ContentType": content_type} if content_type else {}
        with source.open("rb") as fh:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=fh, **extra)

    # ── 读 / 删 ────────────────────────────────────────────

    def read_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        """删对象。**对象不存在不算错。**

        【为什么这里没有 try/except】S3 的 `DeleteObject` 对不存在的键
        返回成功（它不保证「存在性」，只保证「删过之后不存在」）——
        所以「吞掉 404」这件事**由协议本身做掉了**，不需要我们写。
        加一个 `except ClientError: pass` 反而会吞掉真正的权限错误。
        """
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def url_for(self, key: str) -> str:
        """对外的**永久**地址。

        ─────────────────────────────────────────────────────────
        ⚠️ **不是预签名地址（presigned URL）。**

        预签名看起来更「安全」（不用把桶开成公共读），但它**会过期**
        ——而 `public_url` 在契约里是**永久**的：用户的作品列表里那个
        地址要能放一年，`GET /media/...` 那条 live 门禁断言也要求它
        随时能 200。用预签名的话，表现是「昨天生成的作品今天全裂了」，
        而且它**只在时间过去之后才出错**，本地怎么测都是好的。

        所以这条路要求桶是公共读（或者挂在 CDN 后面）——§9.1 的第一种。
        ─────────────────────────────────────────────────────────
        """
        if not self._public_base_url:
            # 【为什么留这条分支，而不是让配置必填】因为它只在
            # `STORAGE=oss` 下才走到，而那条路已经被 `Settings` 的
            # `model_post_init` 拦过一道（桶名/密钥必填）。这里兜底，
            # 是为了让「配了 OSS 但忘了填公网前缀」的报错**发生在
            # `url_for` 这一行**，而不是变成一个 `f"/{key}"` 这样的
            # 相对地址混进响应里 —— 后者打开是一个 404，而排查的人
            # 会去查静态挂载。
            raise ValueError(
                "STORAGE=oss 时必须配 S3_PUBLIC_BASE_URL（产物的永久公网前缀）"
            )
        return f"{self._public_base_url}/{key.lstrip('/')}"


def build_storage() -> Storage:
    """按配置造存储。**照 `build_provider()` 的形状写。**

    【为什么 `oss` 这一支长得和 `local` 不一样】因为它多了一步
    「造客户端」，而这一步要 `import boto3`。**惰性 import 是故意的**：
    `STORAGE` 默认是 `local`，而 `boto3` 连同 `botocore` 的 import
    要几百毫秒 —— 每个进程（包括每次 `pytest`）都白付一次。

    【为什么这里不再抛 `NotImplementedError`】B6 之前它抛，是为了让
    「配置成 OSS 而实现没写」在启动那一刻响亮地失败。现在实现写了，
    那条纪律挪到了 `Settings.model_post_init`：桶名/密钥没配就**起不来**。
    """
    from app.config import StorageKind

    settings = get_settings()
    if settings.storage is StorageKind.local:
        return LocalStorage(settings.media_root_ready)

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region or None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        aws_session_token=settings.s3_session_token or None,
        config=Config(
            # 【为什么这里必须是 path / virtual 这两个值，不能有第三个】
            #
            # 第一版写的是 `"path" if 开关 else "auto"`，理由是「不指定就交给
            # boto3 自己判」。**实测证明那是错的**：对着火山引擎 TOS
            # （2026-10-15，真桶）三种值各打一次，`auto` 发出的请求是
            # `PUT {endpoint}/{bucket}/{key}` —— 也就是**路径风格**，
            # 于是 TOS 回 `InvalidPathAccess: Forbidden path to access server`。
            #
            # 也就是说：`S3_FORCE_PATH_STYLE=0` 原本**并没有**给出虚拟主机风格，
            # 它给出的是「碰运气」。这个开关是个假二分 —— 名字上只有两种取值，
            # 行为上却有第三种，而那第三种恰好等于第一种。
            #
            # 改成显式的两个值之后，这个布尔才真的是它名字说的那个意思：
            #   0（默认）→ virtual：`{bucket}.{endpoint}/{key}`  AWS 本家 / TOS
            #   1        → path   ：`{endpoint}/{bucket}/{key}`  阿里云 OSS / COS / MinIO
            #
            # ⚠️ 选错的报错**每一种服务商都不一样**，而且都不说「是寻址风格的问题」：
            #   · 该用 virtual 却用了 path → `InvalidPathAccess: Forbidden path
            #     to access server`（TOS 实测）
            #   · 该用 path 却用了 virtual → 一个 DNS 解析失败，错误里只有桶名
            s3={"addressing_style": "path" if settings.s3_force_path_style else "virtual"}
        ),
    )
    return S3Storage(
        bucket=settings.s3_bucket,
        public_base_url=settings.s3_public_base_url,
        client=client,
    )
