"""积分功能上线验收（本机，fake provider + local storage）。

跑法（在后端 venv 的 Python 里跑，httpx 已装）：
    cd G:\\AIVideo\\backend
    .venv\\Scripts\\python.exe ..\\上线本地\\accept_credits.py

验收内容：
  1. 用邀请码注册（注册赠送 50）
  2. 查 /me 余额
  3. 文生图：冻结 4 → 成功结算 4 → 余额 46，流水有 grant/freeze/settle
  4. 失败退款：prompt 含 __FAIL__ → 任务失败 → 全额退回
  5. 上传参考图 + 图生视频：冻结 32 → 结算 (24) → 退还 8
  6. 余额不足：再次提交视频 → 402/403 + 错误码
"""

from __future__ import annotations

import io
import os
import sys
import hashlib
import time
import uuid

import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
INVITE = os.environ.get("INVITE_CODE", "AIV-2026-01")
USER = f"credits_{int(time.time())}_{uuid.uuid4().hex[:4]}"
PASSWORD = "Passw0rd!2026"

passed = 0
failed = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  [PASS] {msg}")


def bad(msg: str) -> None:
    global failed
    failed += 1
    print(f"  [FAIL] {msg}")


def check(cond: bool, msg: str) -> None:
    ok(msg) if cond else bad(msg)


def avail(account: dict) -> int:
    """可用余额 = balance - frozen（服务端不存 available，前端也是现算）。"""
    return account["balance"] - account["frozen"]


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=30)

    print(f"== 1. 注册（邀请码 {INVITE}） ==")
    r = c.post("/auth/register", json={"invite_code": INVITE, "username": USER, "password": PASSWORD})
    if r.status_code != 201:
        bad(f"注册失败：{r.status_code} {r.text[:200]}")
        return 1
    session = r.json()
    token = session["token"]
    check(session["credit_account"]["balance"] == 50, "注册赠送 50 积分")
    check(avail(session["credit_account"]) == 50, "可用余额 50")
    h = {"Authorization": f"Bearer {token}"}

    print("== 2. 影子链：链上余额应与账本一致 ==")
    info = wait_chain(c, h, 50)
    check(info["on_chain_balance"] == 50, f"链上余额 50（合约 {info['contract']}，钱包 {info['address']}）")
    check(len(info["recent_ops"]) >= 1 and info["recent_ops"][0]["kind"] == "mint",
          "最近一条链上操作是 mint")
    print("== 2.1 /me 余额 ==")
    me = c.get("/me", headers=h).json()
    check(avail(me["credit_account"]) == 50, "/me 返回可用余额 50")

    print("== 3. 文生图（固定 4 积分） ==")
    r = c.post("/generation/image", headers=h, json={
        "prompt": "上线验收：一只坐在键盘上的猫",
        "idempotency_key": str(uuid.uuid4()),
        "aspect_ratio": "1:1",
    })
    if r.status_code != 200:
        bad(f"提交失败：{r.status_code} {r.text[:200]}")
        return 1
    task = wait_task(c, h, r.json()["id"])
    check(task["status"] == "succeeded", f"任务状态 succeeded（实际 {task['status']}）")
    check(task["freeze_amount"] == 4, "冻结 4 积分")
    check(task["settled_amount"] == 4, "结算 4 积分")
    me = c.get("/me", headers=h).json()
    check(avail(me["credit_account"]) == 46, "余额 50 → 46")
    info = wait_chain(c, h, 46)
    consumes = [op for op in info["recent_ops"] if op["kind"] == "consume"]
    check(info["on_chain_balance"] == 46, f"链上余额同步到 46（totalSupply {info['total_supply']}）")
    check(bool(consumes) and consumes[0]["tx_hash"], f"链上消耗有交易哈希：{consumes[0]['tx_hash'] if consumes else '无'}")

    print("== 4. 流水 ==")
    page = c.get("/credits/ledger", headers=h, params={"page": 1, "page_size": 20}).json()
    kinds = [it["kind"] for it in page["items"]]
    check("grant" in kinds, "流水含 grant（注册赠送）")
    check("freeze" in kinds, "流水含 freeze（冻结）")
    check("settle" in kinds, "流水含 settle（结算）")
    check(all(it["amount"] > 0 for it in page["items"]), "流水 amount 恒为正")

    print("== 5. 失败退款（__FAIL__ 哨兵） ==")
    before = avail(c.get("/me", headers=h).json()["credit_account"])
    r = c.post("/generation/image", headers=h, json={
        "prompt": "上线验收 __FAIL__ 触发失败",
        "idempotency_key": str(uuid.uuid4()),
        "aspect_ratio": "1:1",
    })
    if r.status_code == 200:
        t = wait_task(c, h, r.json()["id"])
        check(t["status"] == "failed", f"任务失败（实际 {t['status']}）")
    else:
        ok(f"同步路径按契约返回 {r.status_code}（失败已上抛）")
    after = avail(c.get("/me", headers=h).json()["credit_account"])
    check(after == before, f"失败后余额不变（{before} → {after}）")

    print("== 6. 上传参考图 + 图生视频（冻结 32，按实际时长结算） ==")
    from PIL import Image  # 后端 venv 里有 pillow

    buf = io.BytesIO()
    Image.new("RGB", (512, 512), (90, 140, 200)).save(buf, format="PNG")
    up = c.post("/uploads/image", headers=h, files={"file": ("ref.png", buf.getvalue(), "image/png")})
    if up.status_code != 200:
        bad(f"上传失败：{up.status_code} {up.text[:200]}")
        return 1
    asset_id = up.json()["asset_id"]
    ok(f"上传参考图成功 asset_id={asset_id}")

    before = avail(c.get("/me", headers=h).json()["credit_account"])
    r = c.post("/generation/video", headers=h, json={
        "prompt": "上线验收：让参考图动起来",
        "idempotency_key": str(uuid.uuid4()),
        "source_asset_id": asset_id,
        "duration": 5,
        "ratio": "16:9",
    })
    if r.status_code != 200:
        bad(f"视频提交失败：{r.status_code} {r.text[:200]}")
        return 1
    vt = wait_task(c, h, r.json()["id"])
    check(vt["status"] == "succeeded", f"视频任务成功（实际 {vt['status']}）")
    check(vt["freeze_amount"] == 32, "冻结 32 积分")
    check(vt["settled_amount"] is not None and 0 < vt["settled_amount"] <= 32,
          f"结算额在 (0,32]（实际 {vt['settled_amount']}）")
    after = avail(c.get("/me", headers=h).json()["credit_account"])
    check(before - after == vt["settled_amount"], f"扣款 = 结算额（{before} → {after}）")
    info = wait_chain(c, h, after)
    check(info["on_chain_balance"] == after, f"视频结算后链上余额 {after}")

    if os.environ.get("REQUIRE_FABRIC") == "1":
        print("== 6.1. Fabric 存证 ==")
        verify_evidence(c, h, vt["id"])

    print("== 7. 余额不足拦截 ==")
    r = c.post("/generation/video", headers=h, json={
        "prompt": "余额不足测试",
        "idempotency_key": str(uuid.uuid4()),
        "source_asset_id": asset_id,
        "duration": 5,
        "ratio": "16:9",
    })
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    code = (body.get("error") or {}).get("code") or body.get("code")
    check(r.status_code == 400 and code == "INSUFFICIENT_CREDITS",
          f"余额不足被拦（{r.status_code} {code}）")

    print(f"\n账号：{USER}  密码：{PASSWORD}（可用于登录前端验收）")
    print(f"结果：{passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


def wait_chain(c: httpx.Client, h: dict, expected: int, timeout: float = 40.0) -> dict:
    """轮询 /credits/chain，直到链上余额与账本一致且等于 expected。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = c.get("/credits/chain", headers=h).json()
        if last.get("on_chain_balance") == expected == last.get("ledger_balance"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"链上余额未同步到 {expected}：{last}")


def wait_task(c: httpx.Client, h: dict, task_id: int, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = c.get(f"/tasks/{task_id}", headers=h).json()
        if t["status"] in ("succeeded", "failed", "expired", "cancelled"):
            return t
        time.sleep(0.5)
    raise TimeoutError(f"任务 {task_id} 超时未完成")


def verify_evidence(c: httpx.Client, h: dict, task_id: int) -> None:
    items = c.get("/assets", params={"task_id": task_id}, headers=h).raise_for_status().json()["items"]
    video = next(item for item in items if item["kind"] == "video")
    deadline = time.monotonic() + 60
    receipt = {}
    while time.monotonic() < deadline:
        receipt = c.get(f"/assets/{video['id']}/evidence", headers=h).raise_for_status().json()
        if receipt["status"] == "committed":
            break
        if receipt["status"] in ("disabled", "failed", "conflict"):
            break
        time.sleep(0.5)
    committed = receipt.get("status") == "committed"
    check(committed, f"Fabric 提交状态：{receipt.get('status')}")
    if not committed:
        return
    result = c.get(video["public_url"]).raise_for_status().content
    check(hashlib.sha256(result).hexdigest() == receipt["sha256"], "下载字节与 Fabric 记录的指纹一致")
    check(bool(receipt.get("tx_id")), "有 Fabric 交易 ID")


if __name__ == "__main__":
    sys.exit(main())
