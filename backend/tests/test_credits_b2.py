"""记账与流水 —— §7.2 / §7.3。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件里最重要的两个数字：32 和 22】

    register       +50          → balance 50, frozen  0
    image          freeze+settle 4（固定）→ balance 46, frozen  0
    video(5s)      freeze       32        → balance 46, frozen 32
                   settle       24        → balance 22, frozen  0
                   （refund     8 是「frozen 少 32、balance 只少 24」自动出来的）

§15.1 的剧本、前端 `repository_layer_test.dart` 里都写死了这两个数。
对不上就是记账错了 —— 而这批代码里最容易错的正是这里的顺序。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import httpx

from _helpers import auth, new_user, register, submit_image, submit_video


async def _upload(api: httpx.AsyncClient, headers: dict[str, str], name: str = "ref.png") -> int:
    """传一张参考图，返回 asset_id。

    【为什么不用一个假 id】因为 `services/generation` 会**真的去查**
    这张图存不存在、是不是本人的（Mock 查不到这一条）。用一个编出来的
    id 会让「图生视频」的用例全都撞 404，而那是夹具的锅、不是被测代码的。
    """
    res = await api.post(
        "/uploads/image",
        files={"file": (name, b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["asset_id"]


async def _me(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    return (await api.get("/me", headers=headers)).json()["credit_account"]


def _newest(entries: list[dict], kind: str) -> dict:
    """取某类流水里**最新**的一条。

    ─────────────────────────────────────────────────────────
    【为什么不是 `{e['kind']: e for e in entries}[kind]`】

    那样写会返回**最早**的那一条 —— 这是我自己在这里踩到的坑：
    流水是最新在前的，所以字典推导式里后面的元素会覆盖前面的，
    最终留下的是列表末端的、也就是最旧的一条。而断言用的是
    「我以为最新那条」的数字，于是测试红在了一个和被测代码
    毫无关系的地方（断言自己错了），排查时先怀疑的是记账。

    写成显式的「扫一遍取第一个」把这件事钉死，顺便让读的人知道
    「这里要的是最新那条，因为列表最新在前」。
    ─────────────────────────────────────────────────────────
    """
    for entry in entries:
        if entry["kind"] == kind:
            return entry
    raise AssertionError(f"流水里没有 kind={kind!r} 的记录：{entries}")


# ── 那笔账 ────────────────────────────────────────────────────


async def test_注册_出图_转视频之后余额落在_22(api: httpx.AsyncClient) -> None:
    """§15.1 的验收剧本，一句话跑完。

    ─────────────────────────────────────────────────────────
    【为什么这一条值得写成一整段剧本，而不是拆成三条小用例】

    因为要验的是**账户在连续动作下的状态**，而每一步的中间态
    （balance 46 / frozen 32）恰恰是分拆后会丢掉的东西。
    分拆的话，每条用例都从一个新用户开始，于是「冻结 32 时
    balance 还是 46」这个**最难对的状态**永远不会被观察到 ——
    而它正是 §7.2 三段式里「冻结只是把可用搬走」的证明。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "走完剧本的人")

    assert (await _me(api, headers))["balance"] == 50

    # ① 出图：固定 4，冻 4 结 4，退 0
    image = await submit_image(api, headers)
    assert image.status_code == 200, image.text
    assert image.json()["freeze_amount"] == 4
    assert image.json()["settled_amount"] == 4
    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (46, 0)

    # ② 转视频：冻 32
    asset_id = await _upload(api, headers)
    video = await submit_video(api, headers, source_asset_id=asset_id)
    assert video.status_code == 200, video.text
    task = video.json()
    assert task["freeze_amount"] == 32, "5 秒视频要冻 (5+3)×4 = 32"
    assert task["output_duration_sec"] == 6, "成片 = 请求时长 + 1"
    assert task["settled_amount"] == 24, "实结 = (输入 0 + 成片 6)×4 = 24"
    assert task["status"] == "succeeded"

    # ③ 收尾状态：冻结归零，balance 只少了 24（不是 32）
    account = await _me(api, headers)
    assert (account["balance"], account["frozen"]) == (22, 0), (
        f"§15.1 的剧本要求最终落在 22/0，实际 {account}"
    )


async def test_冻结期间余额还在_只是不可用(api: httpx.AsyncClient) -> None:
    """冻结**不减少 balance**，只占用可用额。

    ─────────────────────────────────────────────────────────
    【为什么要专门验这条】

    因为「冻结 32」最容易被实现成「balance −= 32」。那样最终余额
    也是 22，剧本照样过，但**流水会错**：账单上会多出一笔
    「扣 32」，再把 8 记成「退回」—— 看起来合理，实际上把
    「平台先占住钱」和「平台真的花了钱」混成了一件事。

    §7.2 区分这两者的理由很实际：用户中途取消时，`freeze` 是能
    全额退回来的，`settle` 不能（§7.4）。混成一个就退不了。

    ─────────────────────────────────────────────────────────
    【怎么在「提交即完成」的 B2 里看到这个中间态】

    直接读**流水上的快照**，而不是读账户的当前值。每一条流水都带着
    `balance_after` / `frozen_after` —— 那正是写这条流水那一刻的
    账户状态。于是「冻结之后、结算之前」这个瞬间被永久留在了
    `kind == "freeze"` 那一条上，不需要真实排队也能断言它。

    （绕开 HTTP 直接调 `credits.freeze` 也能看到同样的东西，
    但那样测的是 service，不是**接口**。这批的门禁要的是后者。）
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "看冻结的人")
    await submit_image(api, headers, idempotency_key="before")
    asset_id = await _upload(api, headers)
    await submit_video(api, headers, source_asset_id=asset_id)

    entries = (await api.get("/credits/ledger", headers=headers)).json()["items"]

    # 视频那条冻结的快照：balance **还是 46**（出图之后的值），frozen 变成 32。
    freeze = _newest(entries, "freeze")
    assert (freeze["balance_after"], freeze["frozen_after"]) == (46, 32), (
        "冻结不该改变 balance —— 它只是把钱从「可用」搬到「冻结」；"
        f"实际快照 {freeze}"
    )
    # 结算与退回的快照：balance 只少了 24（不是 32），frozen 归零。
    settle = _newest(entries, "settle")
    assert (settle["balance_after"], settle["frozen_after"]) == (22, 0)
    refund = _newest(entries, "refund")
    assert (refund["balance_after"], refund["frozen_after"]) == (22, 0)


async def test_流水里的每一笔加起来正好等于余额(api: httpx.AsyncClient) -> None:
    """对账：`balance == Σ(grant, adjust) − Σ(settle)`。

    ─────────────────────────────────────────────────────────
    【方向规则（§7.3 + 前端 `CreditLedgerKind`）】amount **恒为正**：

      grant / adjust → 往余额里**加**
      settle         → 从余额里**减**（唯一真正花钱的一类）
      freeze/refund  → **只动冻结，不进这个求和**

    最后一条是整套冻结机制最容易理解错的地方，前端
    `CreditLedgerKind.reducesAvailable` 的注释专门写了它：
    freeze 不减余额，refund 也不加余额，两者都只是把「可用」和
    「冻结」之间搬来搬去。所以把 refund 当成「加钱」来求和，
    会算出 30 而余额是 22 —— 那不是记账错了，是求和规则错了。

    这条断言是「平台的账本自己能算平」的机器证明。它比「逐笔断言
    金额」更强：逐笔只能证明**我们预期的那几笔**是对的，
    求和能抓住任何一笔多出来或漏写的流水。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "要对账的人")
    await submit_image(api, headers, idempotency_key="k-1")
    asset_id = await _upload(api, headers)
    await submit_video(api, headers, source_asset_id=asset_id, idempotency_key="k-2")

    entries = (await api.get("/credits/ledger", headers=headers)).json()["items"]
    account = await _me(api, headers)

    signed = 0
    for entry in entries:
        assert entry["amount"] > 0, f"amount 必须恒为正，实际 {entry}"
        if entry["kind"] in ("grant", "adjust"):
            signed += entry["amount"]
        elif entry["kind"] == "settle":
            signed -= entry["amount"]

    assert signed == account["balance"], (
        f"流水加起来是 {signed}，余额是 {account['balance']}；"
        f"流水：{[(e['kind'], e['amount']) for e in entries]}"
    )
    # 顺带钉住：这个剧本的最终两者都是 22。
    assert signed == 22


async def test_退回那笔是_8_而且冻结归零(api: httpx.AsyncClient) -> None:
    """§7.2 ③：退回 = 冻结 − 结算 = 32 − 24 = 8。

    【为什么退回额必须写成一条流水】因为它是用户能看见的唯一证据：
    「说好冻 32，实际花了 24，那 8 去哪了」—— 流水上有一条 `refund 8`
    才解释得清。只把 frozen 减回去、不写流水，账面上说得通，
    但用户看不出发生过什么。
    """
    headers, _ = await new_user(api, "看退回的人")
    asset_id = await _upload(api, headers)
    await submit_video(api, headers, source_asset_id=asset_id)

    entries = (await api.get("/credits/ledger", headers=headers)).json()["items"]

    assert _newest(entries, "refund")["amount"] == 8
    assert _newest(entries, "refund")["frozen_after"] == 0
    assert _newest(entries, "settle")["amount"] == 24
    assert _newest(entries, "freeze")["amount"] == 32


# ── 流水的形状与顺序 ──────────────────────────────────────────


async def test_流水最新在最前面(api: httpx.AsyncClient) -> None:
    """`/credits/ledger` 最新的在前。

    ─────────────────────────────────────────────────────────
    【为什么这条要单独测，而不能靠「恰好在同一次请求里」顺带验】

    因为同一微秒写进来的多条流水**时间完全相同**，只按 `created_at`
    排序的话顺序由排序算法决定、不稳定 —— 表现是刷新一次顺序就变。
    `services/credits.list_ledger` 用 `id DESC` 兜底正是为了它。

    这里连做三次操作，取回来的第一条必须是**最后**那次产生的。
    把 `id DESC` 去掉（只留 `created_at DESC`）时，这条在
    SQLite 上**不一定会红** —— 它依赖物理行序。所以它是一条
    「在 PostgreSQL 上一定会红」的守卫，写在 SQLite 上是为了
    迁移那天不要才发现。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "要排序的人")
    await submit_image(api, headers, idempotency_key="a")
    await submit_image(api, headers, idempotency_key="b")

    entries = (await api.get("/credits/ledger", headers=headers)).json()["items"]
    amounts = [entry["amount"] for entry in entries]

    assert entries[0]["kind"] == "settle", f"最新一笔应当是 settle，实际 {entries[0]}"
    # 注册赠 50 是最早的一笔，必须排到最后。
    assert amounts[-1] == 50
    # 幂等键不同 → 是两次真实提交。每次出图写两笔 4（冻结 4 + 结算 4），
    # 所以一共四笔 —— 不是两笔。写这条断言时我把它算成了两笔，
    # 红了一次；这也说明**流水条数本身**值得被机器记下来。
    assert amounts.count(4) == 4, f"两次出图应当有四笔 4，实际 {amounts}"


async def test_流水分页的账目数字要对得上(api: httpx.AsyncClient) -> None:
    """分页：`page` 从 1 起，`total` 是**全部**条数（不是本页条数）。

    【为什么要同时断 items 和 total】分页最常见的 bug 是 total 忘了带
    用户过滤（于是「共 100 条」里混进了别人的），或者忘了带 where
    （于是翻到第二页就没有了）。这条用例用 `page_size=2` 强制翻页，
    把两种都盖住。
    """
    headers, _ = await new_user(api, "翻页的人")
    for i in range(3):
        await submit_image(api, headers, idempotency_key=f"p{i}")

    # 注册赠送 + 3 次「冻结 + 结算」= 1 + 6 = 7 条
    first = (
        await api.get("/credits/ledger?page=1&page_size=2", headers=headers)
    ).json()
    second = (
        await api.get("/credits/ledger?page=2&page_size=2", headers=headers)
    ).json()

    assert first["page"] == 1 and first["page_size"] == 2
    assert len(first["items"]) == 2
    assert first["total"] == 7, f"total 应当是流水总条数，实际 {first}"
    assert len(second["items"]) == 2
    # 两页不能有重叠 —— 重叠的表现是用户看到同一条流水出现两次。
    ids_first = {item["id"] for item in first["items"]}
    ids_second = {item["id"] for item in second["items"]}
    assert ids_first.isdisjoint(ids_second), (ids_first, ids_second)

    # 翻到超出范围的页：返回空 items，但 total 不变（前端靠它判断还有没有下一页）
    beyond = (
        await api.get("/credits/ledger?page=99&page_size=20", headers=headers)
    ).json()
    assert beyond["items"] == []
    assert beyond["total"] == 7


async def test_流水只包含自己的(api: httpx.AsyncClient) -> None:
    """⚠️ 别人的流水一条都不能出现。

    【为什么这条是安全性质的】流水里有金额和时间点，是纯隐私数据。
    而这类 bug 的写法非常常见：`select(CreditLedger)` 忘了
    `where(user_id == ...)`，开发期只有一个人在用，看不出问题。
    """
    mine_headers, _ = await new_user(api, "我")
    register_result = await register(api, "别人")
    other_id = register_result["user"]["id"]

    await submit_image(api, mine_headers, idempotency_key="mine")

    entries = (await api.get("/credits/ledger", headers=mine_headers)).json()["items"]

    assert entries, "自己的流水不该是空的"
    for entry in entries:
        assert entry["user_id"] != other_id, f"漏了别人的流水：{entry}"
    # 自己那头：两笔（赠送 50 + 出图的冻/结）
    assert {entry["kind"] for entry in entries} >= {"grant", "freeze", "settle"}


async def test_分页参数不合法时是_400_不是_500(api: httpx.AsyncClient) -> None:
    """`page=0` 是调用方的错，要当场 400。

    【为什么不悄悄纠正成 1】因为 `page` 从 1 起是**契约**
    （见 `lib/models/paged.dart`）。悄悄纠正会让一个页码算错了的
    客户端一直拿到「它以为的那一页」的**另一页**，而它不会报错。
    当场 400 至少让写错的那个客户端暴露出来。
    """
    headers, _ = await new_user(api, "乱传页码的人")

    res = await api.get("/credits/ledger?page=0", headers=headers)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INVALID_REQUEST", (
        "形状错误要走 INVALID_REQUEST —— 它必须带 code，"
        "否则前端读不到、只能说「连不上服务器」"
    )
