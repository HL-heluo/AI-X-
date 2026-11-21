"""IPFS（Kubo）上传封装。

为什么要自己写 20 行而不是装 `ipfshttpclient`：
  · Kubo 的 HTTP RPC 就是 `POST /api/v0/add`，没必要多一个包；
  · `ipfshttpclient` 的版本与 Kubo 版本绑定很紧，课程作业里换机器就炸；
  · 出问题时能看懂请求体，比调试第三方库快得多。

使用前提：
  1. 本机（或 WSL）装了 Kubo：https://github.com/ipfs/kubo/releases
  2. `ipfs init` 之后 `ipfs daemon` 跑起来（默认 API 端口 5001、网关 8080）
  3. 上传会自动 pin（`pin=true` 是默认值，显式写出来省得以后有人改成 false）
"""

from __future__ import annotations

import json
import os

import requests

DEFAULT_API = "http://127.0.0.1:5001"
DEFAULT_GATEWAY = "http://127.0.0.1:8080"


def upload_to_ipfs(
    file_path: str,
    api: str = DEFAULT_API,
    *,
    timeout: float = 180,
    pin: bool = True,
) -> str:
    """上传一个文件，返回 CID（内容标识符）。

    Kubo 的响应是「一行一个 JSON」（目录上传会有多行），单文件只有一行。
    所以先按行切开再取最后一行，不要直接 `resp.json()` ——
    目录场景下那样会解析失败。
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)

    url = f"{api.rstrip('/')}/api/v0/add"
    params = {
        "pin": "true" if pin else "false",
        "cid-version": "1",  # CIDv1（bafy...）；写 CIDv0（Qm...）也行，报告里要统一
        "raw-leaves": "false",
    }
    with open(file_path, "rb") as f:
        resp = requests.post(
            url, params=params, files={"file": (os.path.basename(file_path), f)},
            timeout=timeout,
        )
    resp.raise_for_status()

    lines = [line for line in resp.text.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"IPFS 返回空响应：{resp.text!r}")
    data = json.loads(lines[-1])
    cid = data.get("Hash")
    if not cid:
        raise RuntimeError(f"IPFS 响应里没有 Hash 字段：{data!r}")
    return cid


def is_ipfs_alive(api: str = DEFAULT_API, timeout: float = 3) -> bool:
    """探活：daemon 没跑时别等到上传超时才报错。"""
    try:
        resp = requests.post(f"{api.rstrip('/')}/api/v0/version", timeout=timeout)
        return resp.ok
    except requests.RequestException:
        return False


def gateway_url(cid: str, gateway: str = DEFAULT_GATEWAY) -> str:
    """浏览器/播放器可访问的地址（前提：本地 daemon 在跑）。"""
    return f"{gateway.rstrip('/')}/ipfs/{cid}"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="把文件上传到本地 IPFS 节点")
    parser.add_argument("file")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    args = parser.parse_args()

    if not is_ipfs_alive(args.api):
        raise SystemExit(
            f"IPFS daemon 没在 {args.api} 上跑。先执行：ipfs daemon"
        )
    cid = upload_to_ipfs(args.file, args.api)
    print(json.dumps(
        {"file": os.path.abspath(args.file), "cid": cid, "gateway": gateway_url(cid, args.gateway)},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
