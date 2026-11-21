"""生成「创作信息存证」记录 —— 给 Fabric 链码 CreateVideoRecord 用的 JSON。

只依赖标准库（Python 3.10+）。ffprobe 存在时会补上时长/分辨率/codec，
不存在也能跑（媒体信息留空）。

设计要点：
  · 只存哈希，不存 prompt 原文（prompt 只保留 sha256，日后可揭示验证）；
  · 视频本身不进链，链上只放 SHA-256 + IPFS CID；
  · 时间戳不在客户端生成 —— 由链码用交易时间填，避免「自己给自己公证」。

用法：
    python creation_record.py video.mp4 --video-id vid_001 --owner user_1001 \
        --model jimeng --seed 42 --prompt "一只猫在弹钢琴" [--ipfs-cid bafy...] [--out record.json]

输出：stdout 打印 JSON（或写文件），可直接作为 bridge /invoke 的 args[0]。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VIDEO_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def sha256_file(file_path: str, chunk_size: int = 8192) -> str:
    """文件字节的 SHA-256（分块读，大文件也不吃内存）。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def probe_media(video_path: str) -> dict:
    """用 ffprobe 取媒体信息；没有 ffprobe 就返回空 dict。"""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,duration",
        "-show_entries", "format=duration,size",
        "-of", "json", video_path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return {}

    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    meta = {}
    if stream.get("width"):
        meta["width"] = int(stream["width"])
    if stream.get("height"):
        meta["height"] = int(stream["height"])
    if stream.get("codec_name"):
        meta["codec"] = stream["codec_name"]
    duration = fmt.get("duration") or stream.get("duration")
    if duration:
        meta["durationMs"] = int(round(float(duration) * 1000))
    if fmt.get("size"):
        meta["sizeBytes"] = int(fmt["size"])
    return meta


def build_record(
    video_path: str,
    *,
    video_id: str,
    owner_id: str,
    model: str | None = None,
    seed: int | str | None = None,
    prompt: str | None = None,
    ipfs_cid: str | None = None,
    provider_task_id: str | None = None,
    media: dict | None = None,
) -> dict:
    """组装链码需要的 recordJson（字段名与链码一一对应）。"""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if not video_id or any(c not in VIDEO_ID_CHARS for c in video_id):
        raise ValueError("videoId 只能包含字母数字和 ._-（链码限制）")
    if not owner_id or not owner_id.strip():
        raise ValueError("ownerId 不能为空")

    digest = sha256_file(video_path)
    media_info = dict(media if media is not None else probe_media(video_path))
    media_info.setdefault("sizeBytes", os.path.getsize(video_path))

    # 生成参数：只记录可公开的摘要；prompt 只存哈希
    params: dict = {}
    if model:
        params["model"] = model
    if seed is not None and seed != "":
        params["seed"] = int(seed) if str(seed).isdigit() else str(seed)
    if prompt:
        params["promptSha256"] = sha256_text(prompt)
        params["promptChars"] = len(prompt)

    record = {
        "videoId": video_id,
        "sha256": digest,
        "ownerId": owner_id,
        "ipfsCid": ipfs_cid or "",
        "generationParams": json.dumps(params, ensure_ascii=False, separators=(",", ":")) if params else "",
        "providerTaskId": provider_task_id or "",
        "mediaMeta": json.dumps(media_info, ensure_ascii=False, separators=(",", ":")),
    }
    if "width" in media_info:
        record["width"] = media_info["width"]
    if "height" in media_info:
        record["height"] = media_info["height"]
    if "durationMs" in media_info:
        record["durationMs"] = media_info["durationMs"]
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description="生成视频创作信息存证记录（JSON）")
    ap.add_argument("video", help="视频文件路径")
    ap.add_argument("--video-id", required=True, help="业务视频 ID（字母数字._-）")
    ap.add_argument("--owner", required=True, help="作者用户 ID")
    ap.add_argument("--model", help="生成模型名，如 jimeng / minimax")
    ap.add_argument("--seed", help="随机种子")
    ap.add_argument("--prompt", help="提示词原文（只会上链它的 sha256）")
    ap.add_argument("--ipfs-cid", help="已上传 IPFS 的 CID（可选）")
    ap.add_argument("--provider-task-id", help="provider 返回的任务 ID（可选，用于对账）")
    ap.add_argument("--no-probe", action="store_true", help="不调 ffprobe，只算文件大小")
    ap.add_argument("--out", help="写到文件；不填则打印到 stdout")
    args = ap.parse_args()

    record = build_record(
        args.video,
        video_id=args.video_id,
        owner_id=args.owner,
        model=args.model,
        seed=args.seed,
        prompt=args.prompt,
        ipfs_cid=args.ipfs_cid,
        provider_task_id=args.provider_task_id,
        media={} if args.no_probe else None,
    )
    payload = json.dumps(record, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
        print(f"已写入 {os.path.abspath(args.out)}")
        print(f"  videoId {record['videoId']}  sha256 {record['sha256'][:16]}…  owner {record['ownerId']}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
