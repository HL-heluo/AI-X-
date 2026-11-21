"""一次完整的双链联动演示（也就是报告里的「图 2：时序图」的可执行版）。

流程：
  0. 准备一个视频（没有就现场用 ffmpeg 生成 3 秒样片）
  1. SHA-256（精确指纹）
  2. videohash2 感知指纹（64 bit）
  3. 上传 IPFS 拿 CID          [--no-ipfs 可跳过]
  4. 调用 Fabric 链码写存证     [--no-fabric 可跳过，或 --bridge-url 指向 bridge]
  5. 读回存证并校验             （有桥才做）
  6. 打印/落盘一份回执 JSON

三种跑法：
  # 只验证指纹（零依赖：只要 ffmpeg + videohash2）
  python demo_e2e.py --no-ipfs --no-fabric

  # 指纹 + IPFS（需要 ipfs daemon）
  python demo_e2e.py --no-fabric

  # 全链路（需要 IPFS + fabric-samples + bridge 已启动）
  python demo_e2e.py --bridge-url http://127.0.0.1:8801
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

# Windows 中文控制台默认 GBK，中文输出会乱码/抛 UnicodeEncodeError。
# cmd 里先 `chcp 65001`，或直接用 Windows Terminal / PowerShell 7。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fingerprints import compute_perceptual_hash, compute_sha256, fingerprint  # noqa: E402


def ensure_sample_video(path: str) -> str:
    """没有样片就用 ffmpeg 造一个，避免作业卡在「视频从哪来」。"""
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
    ]
    print(f"[0] 生成样片：{' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    return path


def post_json(url: str, payload: dict, timeout: float = 60) -> dict:
    import requests

    headers = {"Authorization": f"Bearer {os.environ['FABRIC_BRIDGE_TOKEN']}"}
    with requests.Session() as client:
        client.trust_env = False
        resp = client.post(url, json=payload, timeout=timeout, headers=headers)
    data = resp.json()
    if not resp.ok or not data.get("ok", True):
        raise RuntimeError(f"{url} 失败：{resp.status_code} {data}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="双链视频存证端到端演示")
    ap.add_argument("--video", default=os.path.join("media", "sample.mp4"))
    ap.add_argument("--video-id", default=f"vid_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}")
    ap.add_argument("--creator", default="user_demo_001")
    ap.add_argument("--ipfs-api", default="http://127.0.0.1:5001")
    ap.add_argument("--no-ipfs", action="store_true")
    ap.add_argument("--bridge-url", default="", help="例如 http://127.0.0.1:8801")
    ap.add_argument("--no-fabric", action="store_true")
    ap.add_argument("--out", default="evidence_receipt.json")
    args = ap.parse_args()

    receipt: dict = {
        "videoId": args.video_id,
        "creator": args.creator,
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    # 0. 准备视频
    video = ensure_sample_video(args.video)
    receipt["video"] = os.path.abspath(video)

    # 1~2. 双指纹
    t0 = time.time()
    fp = fingerprint(video)
    receipt["fingerprint"] = fp
    receipt["fingerprintSeconds"] = round(time.time() - t0, 2)
    print(f"[1] SHA-256      {fp['sha256']}")
    print(f"[2] 感知哈希      {fp['perceptualHash']}（{fp['perceptualBits']} bit，阈值 {fp['similarThresholdBits']} bit）")

    # 3. IPFS
    cid = None
    if not args.no_ipfs:
        from ipfs_client import gateway_url, is_ipfs_alive, upload_to_ipfs

        if not is_ipfs_alive(args.ipfs_api):
            print(f"[3] 跳过：IPFS daemon 不在 {args.ipfs_api}（先跑 ipfs daemon）")
        else:
            cid = upload_to_ipfs(video, args.ipfs_api)
            receipt["ipfsCid"] = cid
            receipt["ipfsGateway"] = gateway_url(cid)
            print(f"[3] IPFS CID     {cid}")
    if cid is None:
        print("[3] 跳过 IPFS")

    # 4. Fabric 存证
    bridge = args.bridge_url
    if not args.no_fabric and bridge:
        record = {
            "videoId": args.video_id,
            "sha256": fp["sha256"],
            "perceptualHash": fp["perceptualHash"],
            "ipfsCid": cid,
            "creator": args.creator,
            "generationParams": json.dumps(
                {"model": "demo-model", "seed": 42, "prompt_hash": "demo"}, ensure_ascii=False
            ),
            "width": 640,
            "height": 360,
            "durationMs": 3000,
        }
        created = post_json(f"{bridge}/invoke", {"fn": "CreateVideoRecord", "args": [json.dumps(record)]})
        receipt["fabricCreate"] = json.loads(created["result"])
        print(f"[4] Fabric 存证   tx={receipt['fabricCreate']['ledgerTxId']}")

        # 5. 读回 + 校验（用「重新上传一份转码后的副本」模拟盗版检测）
        read = post_json(f"{bridge}/evaluate", {"fn": "ReadVideoRecord", "args": [args.video_id]})
        receipt["fabricRead"] = json.loads(read["result"])

        exact = post_json(f"{bridge}/evaluate", {
            "fn": "VerifyExactHash", "args": [args.video_id, fp["sha256"]],
        })
        receipt["verifyExact"] = json.loads(exact["result"])
        print(f"[5] 精确校验      match={receipt['verifyExact']['match']}")
    else:
        print("[4] 跳过 Fabric（--no-fabric 或没给 --bridge-url）")

    receipt["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)

    print(f"\n回执已写入 {os.path.abspath(args.out)}")
    print("这条回执 = 报告第六章「双链联动」表格的证据。")
    # 顺带演示「同一视频转码后感知哈希仍能对上」
    variant = os.path.join(os.path.dirname(video) or ".", "sample_transcoded.mp4")
    if os.path.exists(variant):
        other = compute_perceptual_hash(variant)
        from fingerprints import hamming_distance

        d = hamming_distance(fp["perceptualHash"], other)
        print(f"\n参考：同片转码副本的感知哈希 {other}，汉明距离 {d}/64")


if __name__ == "__main__":
    main()
