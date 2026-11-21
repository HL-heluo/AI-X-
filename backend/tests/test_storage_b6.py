"""`S3Storage` —— 走 S3 协议的那一份（B6）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这里的替身和 `test_jimeng_b6.py` 那种替身**不是一回事**】

即梦那边是个 `MockTransport`：**协议由我们编**，所以它只能证明
「给定这种响应，我们的处置是对的」。

这里不一样 —— **boto3 全程是真的**：真的序列化、真的 SigV4 签名、
真的按寻址风格拼地址。只有**发出去那一步**被 `before-send.s3.*`
截下来。所以下面这几句是真的在 boto3 身上验过的：

  · put 进去的东西 get 得回来、head 得到、delete 之后没了；
  · 开了路径风格时，桶名落在路径的第一段；
  · `Authorization` 是 `AWS4-HMAC-SHA256` 开头，且**请求里没有 SK**。

**仍然不能证**：真桶接不接受我们的桶名 / 区域 / 权限；OSS 到底要
path 还是 virtual 寻址（那是 §18-2 清单上的事，要用真桶确认）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import io

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.config import Config

from app.config import Settings
from app.services.storage import LocalStorage, S3Storage, build_storage

BUCKET = "bkt"
BASE = "https://cdn.example.com"
ENDPOINT = "http://s3.invalid"
SK = "SK-TEST-ONLY-NEVER-REAL"


# ══════════════════════════════════════════════════════════════
# 替身：内存里的一个桶
# ══════════════════════════════════════════════════════════════


class _Raw:
    """`AWSResponse.raw` 的替身。

    【为什么要自己写一个而不是塞 `io.BytesIO`】因为 botocore 对这个
    对象有**两个**要求：非流式响应走 `.content`（内部调 `.stream()`），
    流式响应（`get_object` 的 `Body`）走 `.read()`。`BytesIO` 只有后者，
    于是一次 PUT 会以
    `AttributeError: '_io.BytesIO' object has no attribute 'stream'`
    失败 —— 而那个报错长得像 boto3 装坏了。
    """

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    def read(self, amt: int | None = None) -> bytes:
        return self._buf.read() if amt is None else self._buf.read(amt)

    def stream(self, amt: int = 65536, decode_content: object = None):
        del decode_content
        while True:
            chunk = self._buf.read(amt)
            if not chunk:
                return
            yield chunk

    def close(self) -> None:
        pass


def _response(url: str, status: int, headers: dict[str, str], body: bytes = b"") -> AWSResponse:
    return AWSResponse(url, status, headers, _Raw(body))


class _FakeS3:
    """一个内存桶 + 一本流水，挂在 `before-send.s3.*` 上。

    ─────────────────────────────────────────────────────────
    【为什么不直接 mock 掉 `put_object` / `head_object`】

    因为那样等于**跳过了 boto3**，而 boto3 恰恰是这里唯一值得验的东西
    （参数名、签名、寻址风格、错误码的形状）。`before-send` 是它留的
    最后一处缝：消息已经造好、签好，只是还没上线路。
    ─────────────────────────────────────────────────────────
    """

    def __init__(self, *, miss_body: bytes | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[dict] = []
        # 404 的**形状**：真 S3 对 HEAD 回一个**空 body**，于是 botocore
        # 只能把错误码合成成字面量 `"404"`；对 GET 才会回一段 XML
        # （`NoSuchKey`）。两条都要走一遍 —— 见 `_miss_code`。
        self._miss_body = miss_body

    @staticmethod
    def _key_of(url: str) -> str:
        # 路径风格下 key 在桶名之后（`{endpoint}/{bucket}/{key}`）。
        return url.split(f"/{BUCKET}/", 1)[-1].split("?", 1)[0]

    def _miss(self, url: str) -> AWSResponse:
        if self._miss_body is None:
            return _response(url, 404, {})
        return _response(url, 404, {"content-type": "application/xml"}, self._miss_body)

    def __call__(self, request, **_kwargs: object) -> AWSResponse:
        url = str(request.url)
        key = self._key_of(url)
        body = request.body
        is_file = hasattr(body, "read")
        if is_file:
            body = body.read()
        self.calls.append(
            {
                "method": request.method,
                "url": url,
                "key": key,
                "body": body,
                "body_is_file": is_file,
                "headers": request.headers,
            }
        )

        if request.method == "PUT":
            self.objects[key] = body
            return _response(url, 200, {})
        if request.method in ("GET", "HEAD"):
            if key not in self.objects:
                return self._miss(url)
            payload = self.objects[key]
            headers = {"content-length": str(len(payload)), "content-type": "image/png"}
            if request.method == "HEAD":
                return _response(url, 200, headers)
            return _response(url, 200, headers, payload)
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return _response(url, 204, {})
        raise AssertionError(f"这个替身没料到 {request.method} —— 说明实现里多了一次调用")


def _store(*, public_base_url: str = BASE, fake: _FakeS3 | None = None) -> tuple[S3Storage, _FakeS3]:
    """一个「真 boto3 + 假线路」的 `S3Storage`。"""
    fake = fake or _FakeS3()
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="cn-hangzhou",
        aws_access_key_id="AK-TEST-ONLY",
        aws_secret_access_key=SK,
        config=Config(s3={"addressing_style": "path"}),
    )
    client.meta.events.register("before-send.s3.*", fake)
    return S3Storage(bucket=BUCKET, public_base_url=public_base_url, client=client), fake


# ══════════════════════════════════════════════════════════════
# 一轮真往返
# ══════════════════════════════════════════════════════════════


def test_一轮真_boto3_往返_写完读得到_删完就没了() -> None:
    """put / get / head / delete 各走一遍，**经 boto3 而不是经我们的 mock**。"""
    store, fake = _store()

    store.put_bytes("t/7/out.png", b"\x89PNG-hello", content_type="image/png")
    assert store.exists("t/7/out.png")
    assert store.read_bytes("t/7/out.png") == b"\x89PNG-hello"

    store.delete("t/7/out.png")
    assert not store.exists("t/7/out.png")
    # 【为什么连动词序列都要断言】因为多一次少一次都是钱：`delete`
    # 之前多一次 HEAD 是浪费，`read_bytes` 之后多一次 PUT 是**覆盖**。
    assert [c["method"] for c in fake.calls] == ["PUT", "HEAD", "GET", "DELETE", "HEAD"]


def test_put_file_过去的是文件句柄而不是内存里的那一份() -> None:
    """`put_file` 存在的**全部理由**：产物可能是几十 MB，不能先读成 bytes。

    【为什么要断言「是个文件对象」这种实现细节】因为这一条一旦退化，
    没有任何**行为上**的差别 —— 传上去的字节一模一样，只有峰值内存
    变成两倍，而内存在并发转存时会相乘。这种退化不会让任何一条
    「字节对不对」的用例变红，所以只能在这里钉住。
    """
    store, fake = _store()
    source = _tmp_file(b"\x89PNG" + b"x" * 4096)

    store.put_file("t/7/big.mp4", source)

    call = fake.calls[0]
    assert call["body_is_file"] is True, "put_file 把整份产物读进内存了"
    assert call["body"] == source.read_bytes()


def _tmp_file(data: bytes):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "artifact.bin"
    tmp.write_bytes(data)
    return tmp


def test_路径风格下桶名落在路径的第一段() -> None:
    """`s3_force_path_style=True` 的实际效果（OSS / COS / MinIO 要这个）。

    【为什么它值得一条用例】因为选错的表现是**一个 DNS 解析失败**，
    而错误信息里只有桶名 —— 看不出是寻址风格的问题。把「配置打开后
    地址长什么样」写死在这里，将来换桶时至少这一半是确定的。
    """
    store, fake = _store()

    store.put_bytes("t/7/out.png", b"x")

    assert fake.calls[0]["url"] == f"{ENDPOINT}/{BUCKET}/t/7/out.png"


def test_请求是真的签过名的_而且密钥不在请求里() -> None:
    """`Authorization` 是 SigV4；**SK 不出现在请求的任何一处**。

    【为什么要把「没有密钥」也断言上】因为在本地替身里签名对不对没人
    管，而「密钥跟着请求/日志跑出去」是这里唯一**不可挽回**的错误。
    顺手扫一遍整条请求，代价是零。
    """
    store, fake = _store()

    store.put_bytes("t/7/out.png", b"x")

    call = fake.calls[0]
    # 头值可能是 str 也可能是 bytes（urllib3 两种都会给）——
    # 只当 str 用的话，撞上 bytes 时报的是一个 `TypeError`，
    # 而那长得像「这个用例写坏了」，不像「签名没发生」。
    raw = call["headers"].get("Authorization", "")
    auth = raw.decode("latin-1") if isinstance(raw, bytes) else raw
    assert auth.startswith("AWS4-HMAC-SHA256 "), auth
    assert SK not in repr(call), "密钥泄漏进了请求 —— 这比签名错更严重"


# ══════════════════════════════════════════════════════════════
# url_for：必须是永久的
# ══════════════════════════════════════════════════════════════


def test_url_for_给的是永久地址_两次调用一模一样() -> None:
    """**不是预签名地址。**

    ─────────────────────────────────────────────────────────
    【为什么「两次调用一模一样」才是最锋利的那条断言】

    「不含 `X-Amz-Signature`」只否掉了预签名的一种拼法，而
    「地址能打开」在本地怎么测都是绿的 —— 预签名**只在时间过去之后**
    才出错，表现是「昨天生成的作品今天全裂了」。

    预签名的定义性特征是它**带时间**，所以同一次调用之间必然不同
    （`X-Amz-Date` 至少精确到秒）。两次相等这条断言，正好卡在
    那个特征上：任何把时间掺进地址的写法都会让它红。
    ─────────────────────────────────────────────────────────
    """
    store, _ = _store()

    first = store.url_for("t/7/out.png")
    second = store.url_for("t/7/out.png")

    assert first == second == f"{BASE}/t/7/out.png"
    for param in ("X-Amz-Signature", "X-Amz-Credential", "X-Amz-Date", "X-Amz-Expires"):
        assert param not in first, f"public_url 里出现了 {param} —— 那不是永久地址"


def test_url_for_不发任何请求() -> None:
    """拼地址是纯字符串的事 —— 一次网络都不该有。

    【为什么单独一条】因为「签名一下就能拿到地址」是 boto3 **确实提供**
    的能力（`generate_presigned_url`），而它走网络这件事在本地替身下
    完全看不出来。这条把它堵死。
    """
    store, fake = _store()

    store.url_for("t/7/out.png")

    assert fake.calls == []


def test_url_for_容忍开头多一道斜杠() -> None:
    """key 的两种形状（`t/7/x` 与 `/t/7/x`）不能拼出两个地址。

    【为什么这条有用】`public_url_for` 一直有 `lstrip("/")`，而
    `assets.py` 与 `generation.py` 两边的 key 来源不同。少这一句的
    表现是同一张图有两个 URL，缓存和去重都会分别算成两份。
    """
    store, _ = _store()

    assert store.url_for("/t/7/out.png") == store.url_for("t/7/out.png")


def test_没配公网前缀时_url_for_要吵() -> None:
    """配了 OSS 却忘了填 `S3_PUBLIC_BASE_URL` → **在 url_for 那一行**炸。

    【为什么不在 `Settings` 里就拦】见 `config.py`：桶名/密钥是启动
    必填，而公网前缀在 `local` 下不参与任何事。这里兜底的意义是让
    报错落在**地址被拼出来的那一刻**，而不是变成一个
    `/t/7/out.png` 这样的相对地址混进响应 —— 后者打开是 404，
    而排查的人会去查静态挂载。
    """
    store, _ = _store(public_base_url="")

    with pytest.raises(ValueError, match="S3_PUBLIC_BASE_URL"):
        store.url_for("t/7/out.png")


# ══════════════════════════════════════════════════════════════
# exists：三种「没有」与一种「不是没有」
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "miss_body",
    [
        b'<?xml version="1.0"?><Error><Code>NoSuchKey</Code><Message>x</Message></Error>',
        None,  # HEAD 的 404 是空 body → botocore 合成出字面量 "404"
    ],
    ids=["NoSuchKey", "裸404"],
)
def test_exists_对象不在时回_False(miss_body: bytes | None) -> None:
    """`NoSuchKey` 与裸 `404` 两种形状都要认。

    【为什么要两种】真 S3 对 HEAD 回空 body、对 GET 回 XML —— 只认
    其中一种的话，另一位厂商（OSS / MinIO）走另一条时会把「文件没了」
    报成一个 500，而那是用户删一张图就会撞到的路径。
    """
    fake = _FakeS3(miss_body=miss_body)
    store, _ = _store(fake=fake)

    assert store.exists("t/7/nope.png") is False


def test_exists_遇到别的错误要照抛_不能当成不存在() -> None:
    """403 / 500 必须炸出来。

    ─────────────────────────────────────────────────────────
    【一个 `except ClientError: return False` 会掩盖什么】

    桶策略改动、密钥过期、区域配错 —— 这些都会以 `ClientError`
    的形式出现（`AccessDenied` / `InvalidAccessKeyId` / `PermanentRedirect`）。
    把它们统一读成「文件不在」，表现是**整个作品列表的缩略图静默消失**，
    而用户会以为作品被删了、重新生成一遍 —— 再花一次钱，
    而账单上完全看不出原因（那些调用每一笔都是「成功」的）。
    ─────────────────────────────────────────────────────────
    """
    from botocore.exceptions import ClientError

    fake = _FakeS3()

    def deny(request, **_kwargs: object) -> AWSResponse:
        del request
        return _response(
            ENDPOINT,
            403,
            {"content-type": "application/xml"},
            b'<?xml version="1.0"?><Error><Code>AccessDenied</Code>'
            b"<Message>denied</Message></Error>",
        )

    store, _ = _store(fake=fake)
    store._client.meta.events.unregister("before-send.s3.*", fake)
    store._client.meta.events.register("before-send.s3.*", deny)

    with pytest.raises(ClientError):
        store.exists("t/7/out.png")  # type: ignore[attr-defined]


def test_删一个不存在的对象不算错() -> None:
    """S3 的 `DeleteObject` 本身就不保证「存在性」。

    【为什么把协议的行为写进测试】因为它是 `delete` 那一段**故意
    没有 try/except** 的依据（见 `storage.py` 里的说明）。哪天有人
    觉得「稳妥起见补个 except」，这条会先告诉他协议已经处理掉了。
    """
    store, fake = _store()

    store.delete("t/7/never-existed.png")

    assert [c["method"] for c in fake.calls] == ["DELETE"]


# ══════════════════════════════════════════════════════════════
# 按配置造存储
# ══════════════════════════════════════════════════════════════


def _oss_settings(**overrides: object) -> Settings:
    """一份「配了 OSS」的配置。同 `test_jimeng_b6.py`：直接构造，不走环境变量。"""
    base: dict[str, object] = {
        "jwt_secret": "x" * 40,
        "storage": "oss",
        "s3_bucket": BUCKET,
        "s3_region": "cn-hangzhou",
        "s3_endpoint_url": ENDPOINT,
        "s3_access_key_id": "AK-TEST-ONLY",
        "s3_secret_access_key": SK,
        "s3_public_base_url": BASE,
        "s3_force_path_style": True,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_配了_oss_就造出_S3Storage_桶名与公网前缀都来自配置(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_storage()` 的 oss 分支：**真的**去造 S3Storage，并用配置里的桶。

    【为什么用记录器替掉 `boto3.client`，而不是拿真客户端再拦线路】
    这里要验的只有一件事：**配置有没有被正确转交给 boto3/S3Storage**。
    拿真客户端会顺带把签名也验一遍，但那件事上面那条往返用例已经做了，
    而它需要把 `before-send` 挂在 `build_storage` 造出来的那个客户端上 ——
    那要伸手去够私有属性。用记录器更直接，也更能定位。
    """
    settings = _oss_settings()
    seen: dict[str, object] = {}

    class _Recorder:
        def __init__(self) -> None:
            self.puts: list[dict] = []

        def put_object(self, **kwargs: object) -> None:
            self.puts.append(kwargs)

    recorder = _Recorder()

    def fake_client(service: str, **kwargs: object) -> object:
        seen["service"] = service
        seen.update(kwargs)
        return recorder

    import boto3 as boto3_module

    monkeypatch.setattr(boto3_module, "client", fake_client)
    monkeypatch.setattr("app.services.storage.get_settings", lambda: settings)

    store = build_storage()
    store.put_bytes("t/7/out.png", b"x", content_type="image/png")

    assert isinstance(store, S3Storage)
    assert seen["service"] == "s3"
    assert seen["endpoint_url"] == ENDPOINT
    assert seen["aws_access_key_id"] == "AK-TEST-ONLY"
    assert recorder.puts[0]["Bucket"] == BUCKET
    assert recorder.puts[0]["Key"] == "t/7/out.png"
    assert store.url_for("t/7/out.png") == f"{BASE}/t/7/out.png"


def test_寻址风格这个开关真的接到了_boto3_上(monkeypatch: pytest.MonkeyPatch) -> None:
    """`s3_force_path_style` 不是个装饰品 —— 它要变成 `addressing_style`。

    【为什么值得一条】因为「配了但没接上」不会报错：地址照样拼得出来，
    只是在真桶上会 DNS 失败。而本地替身里那条路永远不会被走到。

    ⚠️ **这条用例自己错过一次，值一提。** 它原本断言关掉开关时
    `addressing_style == "auto"`，而那条断言是**照着实现抄的**，
    不是照着事实写的 —— 实现当时真的写的是 `"auto"`。

    2026-10-15 在真桶（火山引擎 TOS）上三种值各打一次，事实是：

        auto    → 实际发出 `PUT {endpoint}/{bucket}/{key}`（**路径风格**）
                  → TOS 回 `InvalidPathAccess: Forbidden path to access server`
        virtual → `PUT {bucket}.{endpoint}/{key}` → 通
        path    → 同 auto，不通

    也就是说 `"auto"` 在这里**不等于「交给 boto3 判」**，它等于路径风格 ——
    于是「关掉路径风格开关」这个动作在真桶上毫无作用，而且报错里
    没有一个字提到寻址风格。断言得改成 `"virtual"`（也就是它名字的意思）。

    【教训】「测试和实现一致」证明不了它们一起是对的。凡是断言**我们自己
    选的一个字符串常量**的地方，都要问一句：这个字符串有没有在真东西上
    验过？这一条验不了（本地没有真桶），所以它现在只在注释里记着实测结果，
    真正的证据在 HANDOFF §6.1 那张表里。
    """
    import boto3 as boto3_module
    from botocore.config import Config as BotoConfig

    seen: list[dict] = []
    monkeypatch.setattr(
        boto3_module, "client", lambda service, **kwargs: seen.append(kwargs)
    )
    monkeypatch.setattr(
        "app.services.storage.get_settings", lambda: _oss_settings(s3_force_path_style=True)
    )
    build_storage()

    config = seen[0]["config"]
    assert isinstance(config, BotoConfig)
    assert config.s3["addressing_style"] == "path"

    seen.clear()
    monkeypatch.setattr(
        "app.services.storage.get_settings",
        lambda: _oss_settings(s3_force_path_style=False),
    )
    build_storage()
    # **必须是 "virtual"，不能是 "auto"** —— 理由见上面 docstring 里那次实测。
    # 写成 "auto" 的话，这个开关的「关」位在真桶上是空的。
    assert seen[0]["config"].s3["addressing_style"] == "virtual"


def test_默认还是本地存储(monkeypatch: pytest.MonkeyPatch) -> None:
    """`STORAGE` 不填时**不能**意外走到 S3 —— 那会让本机开发去连一个桶。

    【为什么要这条】因为 OSS 那一支会真的 `import boto3` 并连网络，
    而默认配置下本地跑测试/开发不该有这件事。conftest 也钉了
    `STORAGE=local`，这里是第二道。
    """
    from pathlib import Path

    settings = Settings(jwt_secret="x" * 40, media_root=str(Path(".")))
    monkeypatch.setattr("app.services.storage.get_settings", lambda: settings)

    assert isinstance(build_storage(), LocalStorage)


@pytest.mark.parametrize(
    "missing",
    [{"s3_bucket": ""}, {"s3_access_key_id": ""}],
    ids=["没桶名", "没密钥"],
)
def test_配了_oss_却没配齐_构造配置就该炸(missing: dict[str, str]) -> None:
    """缺桶或缺密钥 → `Settings(...)` 当场抛，**不等第一次生成**。

    【为什么是「构造就炸」而不是「用到才炸」】因为用到它的那一刻，
    积分已经冻了、provider 那边也已经开始干活了 —— 那时候发现桶名
    没配，损失的不只是一条报错。
    """
    with pytest.raises(ValueError, match="S3_BUCKET|S3_ACCESS_KEY_ID"):
        _oss_settings(**missing)


# ══════════════════════════════════════════════════════════════
# 产物地址：走 Storage 实例，而不是模块级的 public_url_for
# ══════════════════════════════════════════════════════════════


class _CdnStorage:
    """「字节在本地、地址在 CDN」的存储 —— OSS 在**地址**上的可观测行为。

    ─────────────────────────────────────────────────────────
    【为什么不直接拿 `STORAGE=oss` 起一个 app】

    因为那会让每一次转存都去连一个不存在的桶（要拦 `before-send`
    得钻进 boto3 的事件系统，而这里要验的跟签名一点关系都没有）。

    这个替身把两件事拆开：字节仍然落在原来的本地实现上（转存、
    探针、封面全都能正常跑完），只有 `url_for` 换成 CDN 前缀。
    于是断言的落点非常干净：**`Asset.public_url` 是谁算的。**
    ─────────────────────────────────────────────────────────
    """

    def __init__(self, inner: LocalStorage, base: str) -> None:
        self._inner = inner
        self._base = base

    def url_for(self, key: str) -> str:
        return f"{self._base}/{key.lstrip('/')}"

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


async def test_产物的地址跟着存储实现走_而不是写死的_media(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端：`POST /generation/image` 出来的 `public_url` 在 CDN 上。

    ─────────────────────────────────────────────────────────
    【这条防的是一次**看起来很对**的回归】

    `_create_assets_for` 原来调的是模块级的 `storage.public_url_for`，
    而那个函数把 `/media/` 写死在路径里。走 `local` 时它完全正确 ——
    所有 B4 的用例都会绿。只有把存储换成 OSS，那个地址才会变成
    `{PUBLIC_BASE_URL}/media/t/12/x.mp4`：一个指向**我们这台机器**的
    地址，而文件在桶里。对用户是 404，对排查的人是「静态挂载配错了」
    的假线索。

    所以这条用例必须让「存储实现」和「地址」**分开**：替身只改地址，
    其余照旧 —— 改回 `public_url_for` 就会立刻变红。
    ─────────────────────────────────────────────────────────
    """
    from _helpers import new_user, submit_image

    real_build = build_storage
    stub = _CdnStorage(real_build(), BASE)
    monkeypatch.setattr("app.services.storage.build_storage", lambda: stub)

    headers, _ = await new_user(api, "作品挂在CDN上的人")
    res = await submit_image(api, headers, idempotency_key="cdn-1")
    assert res.status_code == 200, res.text

    asset = (await api.get("/assets", headers=headers)).json()["items"][0]
    assert asset["public_url"].startswith(f"{BASE}/t/")
    assert "/media/" not in asset["public_url"], (
        "产物地址又走回了写死 `/media/` 的那条路 —— 换 OSS 之后它指向的是我们这台机器"
    )
