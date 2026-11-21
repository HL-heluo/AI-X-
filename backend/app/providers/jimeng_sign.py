"""火山引擎「签名方法 v4」（即梦接入文档 §2）—— **未经真实网关验证**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️⚠️ 这段代码的每一行都**没有**被真实的火山网关接受过。

  · 手头没有 AK/SK（§18-2 未完成），所以一次真请求都发不出去；
  · 我们**能**验证的只有它自己自洽：给定固定的输入与时间戳，
    签名是确定的、`Authorization` 的形状对、密钥不出现在任何
    输出里、改了 body 签名就变。
  · 我们**不能**验证的是：网关认不认。签名差一个字节的表现是
    一个 `403` 和一句「签名不匹配」——**那不是这段代码错了的信号，
    而是「该对着真网关调一次」的信号**。

所以这里刻意把它与 `jimeng.py` 分开：出问题时，「是签名不对还是
请求体不对」可以一次排除一个。合成上游（`httpx.MockTransport`）
只能证后者。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【铁律在这份实现里的落点】

  · AK/SK 只作为**参数**传进来，本模块不读 `get_settings()`、
    不落任何日志、不把它放进返回值；
  · `Authorization` 里只有 AK（`Credential=AK/...`）—— **SK 永远
    不出现在输出里**，它是 HMAC 的钥匙，不是被签的内容。
    这正是「密钥不进库、不进日志」这条铁律在协议层面成立的原因。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import quote

ALGORITHM = "HMAC-SHA256"
"""`Authorization` 头的前缀。**测试钉着它** —— 即梦的网关按这个
字符串选验签算法，写成 `AWS4-HMAC-SHA256` 之类会是一个 403。"""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _quote(value: str) -> str:
    """RFC 3986 的百分号编码。

    【为什么不用 `urllib.parse.urlencode`】它的默认 safe 集合是
    `'/'`，而 canonical query string 里 `/` 必须被编码成 `%2F`。
    差这一个字符的表现是「签名算出来是对的，网关说不对」——
    这类 bug 在本地永远复现不出来，因为两边都用同一个错函数。
    """
    return quote(value, safe="-_.~")


def canonical_query_string(query: Mapping[str, str]) -> str:
    """`k1=v1&k2=v2`，**按 key 的字节序排序**，值要编码。

    【为什么排序不能省】签名的输入必须与网关重算的那份**逐字节**
    相同，而字典的迭代顺序在这里是「碰巧」的。不排序的话，
    单参数时全对、两个参数时一半的请求 403 ——
    那种「有时好有时坏」的故障最难归因。
    """
    return "&".join(f"{_quote(k)}={_quote(query[k])}" for k in sorted(query))


def canonical_headers(headers: Mapping[str, str]) -> tuple[str, str]:
    """返回 `(canonical_headers, signed_headers)`。

    canonical headers 是 `name:value` 每行一个（名字小写、值去首尾空白、
    按名字排序），signed headers 是把名字用 `;` 连起来。
    """
    lowered = sorted((k.lower(), v.strip()) for k, v in headers.items())
    canonical = "".join(f"{k}:{v}\n" for k, v in lowered)
    signed = ";".join(k for k, _ in lowered)
    return canonical, signed


def sign_request(
    *,
    method: str,
    host: str,
    path: str,
    query: Mapping[str, str],
    body: bytes,
    headers: Mapping[str, str],
    ak: str,
    sk: str,
    region: str,
    service: str,
    now: datetime,
) -> dict[str, str]:
    """算出一组要发出去的请求头（含 `Authorization`）。

    ─────────────────────────────────────────────────────────
    `headers` 里传进来的是**除 `Host` / `X-Date` /
    `X-Content-Sha256` / `Authorization` 之外**的头
    （`Content-Type`、`Region`、`Service`…）。
    本函数把前三个补上、把它们一起算进签名，再返回完整的头。
    这样调用方拿到的就是可以直接 `httpx` 发出去的东西 ——
    「签了一组头、发了另一组头」是这类实现最常见的一处静默失败。

    【`host` 为什么必须进签名 —— 一次真网关的教训】
    第一版把 `host` 收成参数却**忘了并进 `signed_headers_in`**，
    签名里就只有 `content-type;region;service;x-content-sha256;x-date`。
    真网关回的是
        `InvalidAuthorization: Invalid 'Authorization' header,
         Pls check your authorization header.`
    —— 那是**网关**的错（不是业务码），说明请求根本没进业务层。
    原因：`Host` 是参与签名的头，网关重算规范请求时一定会把它算进去，
    我们不算 → 两边逐字节不同 → 签名对不上。
    补救在这里而不是在调用方，因为本函数的返回值就是**要发出去的头**，
    放这儿才能保证「算的」与「发的」是同一份。
    ⚠️ `httpx` 只在头里没有 `host` 时才按 URL 补一个；我们给了，它就用我们的，
    于是发出去的那个值与签名时用的**必然是同一个**。
    ─────────────────────────────────────────────────────────

    【`now` 为什么是参数】签名里带时间戳，而**时间戳是签名的输入**。
    用 `datetime.now()` 的话，这条函数不可测（每次结果都不同）。
    真调用方传 `utcnow()`。
    ─────────────────────────────────────────────────────────
    """
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_date = stamp[:8]

    signed_headers_in = {
        **headers,
        # 【放在 `**headers` 之后是有意的】`host` 参数是权威值，
        # 调用方若也在 `headers` 里传了一个 `host`，**以参数为准** ——
        # 否则签名用的 Host 与 URL 里的主机名可能不是同一个。
        "host": host,
        "x-date": stamp,
        "x-content-sha256": _sha256_hex(body),
    }
    canonical, signed_names = canonical_headers(signed_headers_in)

    canonical_request = "\n".join(
        [
            method.upper(),
            path,
            canonical_query_string(query),
            canonical,
            signed_names,
            _sha256_hex(body),
        ]
    )

    scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(
        [ALGORITHM, stamp, scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )

    # ── 派生签名密钥：四段 HMAC 链 ────────────────────────────
    # 【为什么不是直接用 SK 签】因为派生出来的这把钥匙**只对这一天、
    # 这个 region、这个 service 有效**。直接拿 SK 签的话，一次
    # 签名泄漏就等于长期密钥泄漏。
    key = _hmac(sk.encode("utf-8"), short_date)
    key = _hmac(key, region)
    key = _hmac(key, service)
    key = _hmac(key, "request")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        **signed_headers_in,
        "Authorization": (
            f"{ALGORITHM} Credential={ak}/{scope}, "
            f"SignedHeaders={signed_names}, Signature={signature}"
        ),
    }
