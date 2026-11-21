"""MVP 演示：视频生成完成 → 创作信息上 Fabric → 作者/平台都能查到。

依赖：
  · 平台侧：本机 Python（标准库）+ 可选 ffprobe
  · Fabric 侧：已经起来的 test-network + 部署好的 video-evidence 链码 + bridge/server.js
  · IPFS：可选（不给 --ipfs-api 就跳过）

用法：
  # 1) 只生成记录、不上链（先验证字段）
  python demo_creation.py --video sample.mp4 --video-id vid_demo_001 --owner user_1001 \
      --model jimeng --seed 42 --prompt "一只猫在弹钢琴" --dry-run

  # 2) 上链（bridge 默认 http://127.0.0.1:8801）
  python demo_creation.py --video sample.mp4 --video-id vid_demo_001 --owner user_1001 \
      --model jimeng --seed 42 --prompt "一只猫在弹钢琴"

  # 3) 带 IPFS
  python demo_creation.py --video sample.mp4 --video-id vid_demo_001 --owner user_1001 \
      --ipfs-api http://127.0.0.1:5001
"""

from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from creation_record import build_record  # noqa: E402


def post_json(url: str, payload: dict, timeout: float = 30) -> dict:
    """调 bridge 的 /invoke 或 /evaluate，返回解析后的 dict。"""
    import requests

    headers = {"Authorization": f"Bearer {os.environ['FABRIC_BRIDGE_TOKEN']}"}
    with requests.Session() as client:
        client.trust_env = False
        resp = client.post(url, json=payload, timeout=timeout, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"{url} 返回非 JSON：{resp.status_code} {resp.text[:200]}")
    if not resp.ok or not data.get("ok", True):
        raise RuntimeError(f"{url} 失败：{resp.status_code} {data}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="创作信息存证 MVP 演示")
    ap.add_argument("--video", required=True, help="视频文件路径")
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--owner", required=True, help="作者用户 ID")
    ap.add_argument("--model")
    ap.add_argument("--seed")
    ap.add_argument("--prompt")
    ap.add_argument("--provider-task-id")
    ap.add_argument("--ipfs-api", help="例如 http://127.0.0.1:5001；不填则跳过 IPFS")
    ap.add_argument("--bridge-url", default="http://127.0.0.1:8801")
    ap.add_argument("--dry-run", action="store_true", help="只生成记录，不上链")
    ap.add_argument("--out", help="把回执写到文件")
    args = ap.parse_args()

    # ① 生成记录（算 SHA-256 + 媒体信息）
    record = build_record(
        args.video,
        video_id=args.video_id,
        owner_id=args.owner,
        model=args.model,
        seed=args.seed,
        prompt=args.prompt,
        provider_task_id=args.provider_task_id,
    )
    print("① 记录已生成：")
    print(f"   videoId   {record['videoId']}")
    print(f"   ownerId   {record['ownerId']}")
    print(f"   sha256    {record['sha256']}")
    print(f"   mediaMeta {record['mediaMeta']}")

    # ② 可选：上传 IPFS
    if args.ipfs_api:
        from ipfs_client import is_ipfs_alive, upload_to_ipfs

        if not is_ipfs_alive(args.ipfs_api):
            print(f"② 跳过 IPFS：daemon 不在 {args.ipfs_api}")
        else:
            cid = upload_to_ipfs(args.video, args.ipfs_api)
            record["ipfsCid"] = cid
            print(f"② IPFS CID   {cid}")
    else:
        print("② 跳过 IPFS（没给 --ipfs-api）")

    receipt = {"record": record}

    if args.dry_run:
        print("③ --dry-run：不上链。把上面的 record 作为 args[0] 调 CreateVideoRecord 即可。")
    else:
        # ③ 写入 Fabric
        payload = json.dumps(record, ensure_ascii=False)
        try:
            created = post_json(
                f"{args.bridge_url}/invoke",
                {"fn": "CreateVideoRecord", "args": [payload]},
            )
            receipt["create"] = json.loads(created["result"])
            print(f"③ 已写入 Fabric，txId {receipt['create']['ledgerTxId']}")
            print(f"   交易时间 {receipt['create']['createdAtTx']}")
        except Exception as e:  # noqa: BLE001
            print(f"③ 写入失败：{e}")
            sys.exit(1)

        # ④ 作者视角：查自己的作品
        by_owner = post_json(
            f"{args.bridge_url}/evaluate",
            {"fn": "QueryRecordsByOwner", "args": [args.owner]},
        )
        owner_res = json.loads(by_owner["result"])
        receipt["byOwner"] = owner_res
        print(f"④ 作者查询：{owner_res['ownerId']} 共 {owner_res['count']} 条")

        # ⑤ 平台视角：查全部
        all_res = json.loads(
            post_json(
                f"{args.bridge_url}/evaluate",
                {"fn": "QueryAllRecords", "args": ["10"]},
            )["result"]
        )
        receipt["allRecords"] = all_res
        print(f"⑤ 平台查询：共 {all_res['count']} 条（limit {all_res['limit']}）")

        # ⑥ 完整性校验
        exact = json.loads(
            post_json(
                f"{args.bridge_url}/evaluate",
                {"fn": "VerifyExactHash", "args": [record["videoId"], record["sha256"]]},
            )["result"]
        )
        receipt["verifyExact"] = exact
        print(f"⑥ 完整性校验：matched={exact['matched']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(receipt, f, ensure_ascii=False, indent=2)
        print(f"\n回执已写入 {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
