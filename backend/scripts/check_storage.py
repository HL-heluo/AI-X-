"""真桶冒烟 —— 「`STORAGE=oss` 到底能不能用」，**不花钱**的那一半。

运行：`.venv/Scripts/python.exe scripts/check_storage.py`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么需要它，而不是「`check_deps.py` 里 boto3 那项过了就行」】

`check_deps.py` 的 boto3 那项**拦的是 `before-send.s3.*`** ——
boto3 的序列化、SigV4 签名、寻址风格全是真的，只有「发出去」那一步
被截下来。它证明的是「我们的实现自洽」，**证不了桶认不认**。

而那些桶不认的东西，恰恰是本地永远看不见的：

  · 桶名对不对          · endpoint / region 对不对
  · 密钥有没有效、有没有那个桶的权限
  · **寻址风格**对不对（这一条 2026-10-15 真的错了一次，
    见 HANDOFF §6.1 —— `S3_FORCE_PATH_STYLE=0` 曾经什么都没做）
  · 桶是不是**公共读**（不是的话 `url_for` 拼出来的每一个地址都点不开，
    而生成、扣费、落库全都正常）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【它做什么】往桶里写一个几十字节的探针文件 → 读回来逐字节比 →
匿名 GET 一次那个公网地址 → 删掉 → 确认删干净。

【它不做什么】不碰用户的任何数据；探针固定放在 `_probe/` 前缀下，
一眼能看出「这不是用户的东西」，万一半途挂了没删干净也能直接删。
全程 `finally` 清理。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 【为什么在这里强改 STORAGE，而不是要求 `.env` 先切过去】
# 因为切过去之前**正是**要证明桶能用 —— 顺序反了的话，一个配错的桶
# 会让「起服务」这一步失败，而那时的报错离病因很远。
# 这里只影响本进程，不改任何文件。
os.environ["STORAGE"] = "oss"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.services.storage import build_storage  # noqa: E402

OK = "  [ok]  "
FAIL = "  [!!]  "


def _anonymous_get(url: str) -> tuple[int, str]:
    """不带任何凭据去打一个地址 —— 这就是「用户点开作品」那一刻的视角。"""
    request = urllib.request.Request(url, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            body = response.read()
            return response.status, f"{len(body)} 字节"
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        code = ""
        if "<Code>" in detail:
            code = detail.split("<Code>", 1)[1].split("</Code>", 1)[0]
        return exc.code, f"{code or exc.reason}"


def main() -> int:
    settings = get_settings()

    print()
    print("=" * 68)
    print("  真桶冒烟 —— 写 / 读回 / 公共读 / 删")
    print("=" * 68)
    print(f"  endpoint  : {settings.s3_endpoint_url or '(未配，用 boto3 默认)'}")
    print(f"  region    : {settings.s3_region or '(未配)'}")
    print(f"  bucket    : {settings.s3_bucket}")
    print(
        "  寻址风格   : "
        + ("path（{endpoint}/{bucket}/{key}）" if settings.s3_force_path_style
           else "virtual（{bucket}.{endpoint}/{key}）")
    )
    print(f"  公网前缀   : {settings.s3_public_base_url or '(未配)'}")
    print()

    store = build_storage()
    key = f"_probe/{secrets.token_hex(6)}.txt"
    payload = f"aivideo storage probe for {key}\n".encode()

    failures: list[str] = []

    def step(name: str, run) -> None:  # noqa: ANN001
        try:
            detail = run()
        except Exception as exc:  # noqa: BLE001 - 这里就是要抓住一切
            failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:160]}")
            print(f"{FAIL}{name:<24} {type(exc).__name__}: {str(exc)[:160]}")
            return
        print(f"{OK}{name:<24} {detail}")

    public_url = ""
    try:
        step(
            "① 写（put_bytes）",
            lambda: (store.put_bytes(key, payload, content_type="text/plain"), "已写入")[1],
        )
        step("② 写完该在（exists）", lambda: f"在 = {store.exists(key)}")
        step(
            "③ 读回来逐字节比（read_bytes）",
            lambda: (
                f"一致 = {store.read_bytes(key) == payload}（{len(payload)} 字节）"
            ),
        )
        public_url = store.url_for(key)
        step("④ 产物对外地址（url_for）", lambda: public_url)

        # 这一条是整份脚本的重点：**匿名**打一次那个公网地址。
        # 带凭据打是没有意义的 —— 用户点开作品时手里没有凭据。
        def _public_read() -> str:
            status, detail = _anonymous_get(public_url)
            if status != 200:
                raise AssertionError(
                    f"匿名 GET 回 {status}（{detail}）—— 桶不是公共读？"
                    " 产物地址是**永久**的，所以这条路必须是匿名可读的"
                    "（§9.1 的第一种：公共读，或挂一个带鉴权的 CDN）。"
                )
            return f"200，{detail}"

        step("⑤ 匿名 GET 公网地址", _public_read)
    finally:
        step("⑥ 删（delete）", lambda: (store.delete(key), "已删")[1])
        step("⑦ 删干净了（exists）", lambda: f"还在 = {store.exists(key)}")

    print()
    print("=" * 68)
    if failures:
        print(f"  ❌ {len(failures)} 项没过：")
        for item in failures:
            print(f"     · {item}")
        print("=" * 68)
        return 1
    print("  ✅ 真桶可用：写、读回、匿名下载、删，四样都通了。")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
