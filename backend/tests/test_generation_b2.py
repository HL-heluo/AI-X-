"""提交生成 —— §7.1 计价 / §7.2 扣费 / §7.5 四道闸。

这个文件里最要紧的一组是**「被拒之后账户一个数字都不许动」**。
它对应前端 `repository_layer_test.dart` 里那条用例：提交失败以后，
余额、冻结、任务数、流水条数全都要原样。
"""

from __future__ import annotations

import httpx

from _helpers import auth, grant_credits, new_user, register, submit_image, submit_video


async def _account(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    return (await api.get("/me", headers=headers)).json()["credit_account"]


async def _snapshot(api: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    """账户 + 任务数 + 流水条数的一个快照。

    【为什么要把这三样打成一个包】因为「校验走在任何写之前」这条纪律
    要求它们**同时**不变。只看余额的话，「先建了任务再发现余额不够」
    这种写法照样绿 —— 而它会留下一条永远跑不起来的僵尸任务，
    在「进行中」列表里挂着，用户点不动也取消不掉。
    """
    account = await _account(api, headers)
    tasks = (await api.get("/tasks", headers=headers)).json()
    ledger = (await api.get("/credits/ledger?page_size=100", headers=headers)).json()
    return {
        "balance": account["balance"],
        "frozen": account["frozen"],
        "task_total": tasks["total"],
        "ledger_total": ledger["total"],
    }


async def _upload(api: httpx.AsyncClient, headers: dict[str, str], name: str = "ref.png") -> int:
    res = await api.post(
        "/uploads/image",
        files={"file": (name, b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["asset_id"]


# ── 问价 ──────────────────────────────────────────────────────


async def test_问价_图片是固定的_4(api: httpx.AsyncClient) -> None:
    """图片 `{min: 4, max: 4, freeze: 4}`。

    【为什么三个数字必须相等】前端 `TaskCostEstimate.isFixed` 判的是
    `min == max`，相等时把文案从「4~4 积分」改成「本次冻结 4 积分」。
    不相等的话，用户看到的是区间 —— 而图片的成本根本不可能是区间。
    """
    res = await api.get("/generation/cost?kind=text_to_image")

    assert res.status_code == 200, res.text
    assert res.json() == {"min": 4, "max": 4, "freeze": 4}


async def test_问价_视频是区间_而冻结取上限(api: httpx.AsyncClient) -> None:
    """5 秒视频 `{min: 20, max: 32, freeze: 32}`。

    ─────────────────────────────────────────────────────────
    【为什么 `min` 和 `max` 必须不一样】

    因为成片时长由 provider 侧的 Agent 决定 —— 下单那一刻连后端也不知道
    最终会扣多少（§7.2）。给一个确定数字就是在撒谎，而 §13.4 明令
    禁止在按钮下面写确定数字：用户按 4 秒付了钱、结果被扣 6 秒的账，
    那是投诉。

    `freeze` 和 `max` 相等是**有意的**：冻结额就是「最多可能花多少」，
    按它冻住，最后多退少补（§7.2 ③④）。
    ─────────────────────────────────────────────────────────
    """
    res = await api.get("/generation/cost?kind=image_to_video&duration=5&ratio=16:9")

    assert res.status_code == 200, res.text
    assert res.json() == {"min": 20, "max": 32, "freeze": 32}


async def test_问价不认识_kind_时是_400_不是_500(api: httpx.AsyncClient) -> None:
    """`kind=瞎写的` 是调用方的错，必须是 400。

    【为什么这条要专门测】直接 `TaskKind(raw)` 抛的是 `ValueError`，
    它会一路冒成 500 + 一段堆栈。500 的意思是「服务端坏了」，
    而这里服务端好得很，是请求写错了 —— 排查方向完全不同。
    """
    res = await api.get("/generation/cost?kind=瞎写的")

    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INVALID_REQUEST"


async def test_问价不需要登录(api: httpx.AsyncClient) -> None:
    """问价是公开信息（价目表），不带 token 也要能用。

    【为什么它没被 `CurrentUser` 保护】因为登录页下一步就是创作页，
    而创作页一进去就要显示「本次冻结 4 积分」。要求先登录才能问价，
    等于把一个纯展示的数字和鉴权绑在一起 —— 而 v1 的价目表本来就
    写在前端常量里（`_creditsPerImage`），它从来不是秘密。
    """
    assert (await api.get("/generation/cost?kind=text_to_image")).status_code == 200


# ── 提交成功 ──────────────────────────────────────────────────


async def test_出图返回一个已经成功的任务(api: httpx.AsyncClient) -> None:
    """fake provider 的「提交即完成」：响应里 status 已经是 `succeeded`。

    ─────────────────────────────────────────────────────────
    【为什么 B2 要这样，而不是返回 `queued`】

    因为这是前端 `repository_layer_test` 要求的：提交完之后它立刻断言
    余额是 46，而余额要变成 46 就必须**已经结算**。返回 `queued`
    的话那条用例会红，而它是冻结的 —— 方向是后端适配前端。

    真实跨时间的排队是 B3（worker 真跑起来，`queued` 会被真的观察到）。
    届时这个响应会先返回 `queued`，而**调用方这一层不用改** ——
    那正是 §12.2 把 provider 收成 Protocol 的意义。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "看任务形状的人")
    res = await submit_image(api, headers)

    assert res.status_code == 200, res.text
    task = res.json()

    assert task["status"] == "succeeded"
    assert task["kind"] == "text_to_image"
    assert task["freeze_amount"] == 4
    assert task["settled_amount"] == 4
    assert isinstance(task["id"], int), "id 必须是 JSON 整数"
    # 【params 必须是对象，不是那根 JSON 字符串】前端 `Task.fromJson` 优先读
    # 对象形式的 `params`，只有它不在时才退回 `params_json` 字符串。
    assert task["params"] == {"ratio": "1:1"}, task["params"]
    assert task["source_asset_id"] is None
    assert task["error_code"] is None and task["error_msg"] is None
    # 终态任务的排队位次必须是 null —— 见 `queue_position_of` 的说明。
    assert task["queue_position"] is None
    assert task["created_at"] and task["submitted_at"] and task["finished_at"]


async def test_出图不传_aspect_ratio_时_params_里就没有这个键(api: httpx.AsyncClient) -> None:
    """`params` 省掉 null 键 —— 和前端 `TaskParams.toJson` 逐字一致。

    【为什么「多一个 ratio: null」也算错】前端的 `fromJson` 对
    「键不存在」和「键是 null」是同样处理的，所以它**不会崩**。
    但契约是逐字段对齐的，而多出来的键会一路带到将来某个
    「按 ratio 分组统计」的地方去 —— 那时 `null` 会被当成一个真实取值。
    """
    headers, _ = await new_user(api, "不选比例的人")
    res = await submit_image(api, headers, aspect_ratio=None)

    assert res.json()["params"] == {}


async def test_图生视频的_params_里带_ratio_和_duration(api: httpx.AsyncClient) -> None:
    """视频的 `params` 是 `{ratio, duration}`，字段名与前端 `TaskParams` 一致。"""
    headers, _ = await new_user(api, "传参考图的人")
    asset_id = await _upload(api, headers)

    res = await submit_video(api, headers, source_asset_id=asset_id, duration=5, ratio="9:16")

    assert res.status_code == 200, res.text
    assert res.json()["params"] == {"ratio": "9:16", "duration": 5}
    assert res.json()["source_asset_id"] == asset_id
    assert res.json()["kind"] == "image_to_video"


async def test_source_asset_id_用字符串发也能收(api: httpx.AsyncClient) -> None:
    """⚠️ 前端发的 `source_asset_id` 是**字符串**。

    【为什么这条非有不可】前端 `Asset.id` 是 `String`
    （`requireInt(json['id']).toString()`），所以 `POST /generation/video`
    体里是 `"1001"` 而不是 `1001`。谁要是给这个字段加了
    `strict=True`，真机上的每一次图生视频都会 400 —— 而 Mock 里
    完全看不出来（它不做类型校验）。这里就是把那个「谁要是」
    钉在测试里。
    """
    headers, _ = await new_user(api, "发字符串的人")
    asset_id = await _upload(api, headers)

    res = await submit_video(api, headers, source_asset_id=str(asset_id))

    assert res.status_code == 200, res.text
    assert res.json()["source_asset_id"] == asset_id


# ── 校验失败：一个数字都不许动 ────────────────────────────────


async def test_空提示词是_INVALID_PROMPT_而不是_INVALID_REQUEST(api: httpx.AsyncClient) -> None:
    """⚠️ 这条钉的是「契约测试里的那条断言」。

    ─────────────────────────────────────────────────────────
    【为什么空串会走岔路，值得写这么长】

    `repository_layer_test.dart` 有一条要求 `submitImage(prompt: '')`
    返回 `INVALID_PROMPT`。天真写法是给 pydantic 模型加
    `Field(min_length=1)` —— 那样空串会**先被 pydantic 拦下来**，
    返回 `INVALID_REQUEST`。服务端确实拒绝了，只是**理由码错了**：
    前端认 `INVALID_PROMPT`，会显示「提示词不能为空，且不超过 2000 字」；
    认不出就退回到通用兜底的「出错了，请稍后重试」。

    所以 `schemas.py` 里那条纪律是：**业务校验一律放 service，
    不写进 pydantic 的 Field 约束**。这条测试就是它的守卫 ——
    把 `min_length=1` 加回去，它会红。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "提交空提示词的人")
    before = await _snapshot(api, headers)

    res = await submit_image(api, headers, prompt="")

    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INVALID_PROMPT", (
        f"空提示词要落到 INVALID_PROMPT（前端认它），实际 {res.json()}"
    )
    assert await _snapshot(api, headers) == before, "被拒之后账户与任务必须原样"


async def test_只有空白的提示词也算空(api: httpx.AsyncClient) -> None:
    """`"   "` 在用户眼里就是没写。

    【为什么用 `strip()` 判断但用原串判长度】见 `services/generation.submit`：
    「全是空格」要拒，而「2000 个字符」的判定按**原串**算 ——
    用 `strip()` 之后的长度判的话，一个前面有 500 个空格的提示词
    会被悄悄放行，而它在 UI 上看起来一样是超长。
    """
    headers, _ = await new_user(api, "提交空格的人")
    res = await submit_image(api, headers, prompt="   \n\t ")

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_PROMPT"


async def test_超长提示词也是_INVALID_PROMPT(api: httpx.AsyncClient) -> None:
    """§11.2：上限 2000 字，前后端同款。"""
    headers, _ = await new_user(api, "提交超长的人")

    ok = await submit_image(api, headers, prompt="猫" * 2000, idempotency_key="boundary")
    assert ok.status_code == 200, "正好 2000 字要能过（边界是含的）"

    res = await submit_image(api, headers, prompt="猫" * 2001, idempotency_key="too-long")
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_PROMPT"


async def test_图生视频不给参考图是_400(api: httpx.AsyncClient) -> None:
    """图生视频**必须**有参考图。

    【为什么拦在这里而不是让 provider 报错】Mock 的注释写了同一个理由：
    让 provider 报一个「参数不合法」的错，用户看到的是一个和
    「我没传图」毫无关系的错误。挡在门口，错误和原因才能对上。
    """
    headers, _ = await new_user(api, "忘传参考图的人")
    before = await _snapshot(api, headers)

    res = await submit_video(api, headers, source_asset_id=None)

    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INVALID_REQUEST"
    assert await _snapshot(api, headers) == before


async def test_参考图不属于自己时是_404(api: httpx.AsyncClient) -> None:
    """⚠️ 这条是**真后端比 Mock 严**的地方之一。

    Mock 没有「别人的资产」这个概念，所以它拦不住「拿一个编出来的 id 下单」。
    真后端必须查 —— 否则用户可以用一个不存在的参考图提交任务，
    而那笔任务事后追溯不到任何输入（`tasks.source_asset_id` 没有外键，
    见 `models.py` 的说明）。

    【为什么是 404 而不是 403】403 会告诉调用方「这个 id 存在、
    只是不属于你」—— 那是一个可以拿来枚举 id 的探针。
    """
    mine_headers, _ = await new_user(api, "拿别人图的人")
    other_headers, _ = await new_user(api, "被拿图的人")
    other_asset_id = await _upload(api, other_headers, name="别人的图.png")

    res = await submit_video(api, mine_headers, source_asset_id=other_asset_id)

    assert res.status_code == 404, res.text
    assert res.json()["code"] == "NOT_FOUND"


async def test_积分不够时一个数字都不许动(api: httpx.AsyncClient) -> None:
    """⚠️ 本批最要紧的一条：被拒的提交**不留痕**。

    ─────────────────────────────────────────────────────────
    【为什么这条是整批的门禁】

    它是前端 `repository_layer_test.dart` 里那条用例的后端版本：
    提交失败之后，`balance` / `frozen` / 任务数 / 流水条数必须**全都**不变。

    最危险的错误写法是「先冻结、再校验余额」—— 钱已经扣了，再发现
    不够。那时就算回滚能救回来，只要将来有人把 `atomic()` 挪个位置，
    它就变成一笔**真实的误扣**。所以校验一律前置
    （见 `services/generation.submit` 里那段顺序说明）。

    快照里连**流水条数**都要算，是因为「冻结 + 写流水」是两件事：
    只回滚余额、漏了流水那一条，账本上就会多出一条永远解释不清的记录。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "钱不够的人")
    asset_id = await _upload(api, headers)

    # 第一次成功：赠 50 − 实结 24 = 26 可用（冻结的 32 已经放回来了）
    first = await submit_video(api, headers, source_asset_id=asset_id, idempotency_key="v1")
    assert first.status_code == 200, first.text
    before = await _snapshot(api, headers)
    assert before["balance"] == 26, before

    # 第二次要冻 32，只有 22 —— 必须被拒，且**什么都不留下**
    res = await submit_video(api, headers, source_asset_id=asset_id, idempotency_key="v2")

    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INSUFFICIENT_CREDITS"
    assert await _snapshot(api, headers) == before, (
        "积分不足被拒之后，余额/冻结/任务数/流水条数必须一个都不变"
    )


# ── 幂等 ──────────────────────────────────────────────────────


async def test_同一个幂等键提交两次只建一个任务(api: httpx.AsyncClient) -> None:
    """⚠️ §7.5 第 2 道闸：防连点双扣。

    ─────────────────────────────────────────────────────────
    【为什么响应是 409 却还带着 task】

    §12.3 写着 `DUPLICATE_REQUEST` 的客户端行为是**静默复用已存在的任务**。
    光给一个 409 的话，客户端只知道「重了」，不知道重的是哪一个 ——
    前端 `RemoteGenerationRepository._submitOrReuse` 明确拒绝
    「随便造一个空任务糊过去」，所以它只能把错误原样抛给用户。
    用户看到的是「我点了一下生成，它报错了」，而其实任务已经在跑。

    带上 task 之后，那次重复点击对用户是**完全无感**的 —— 这才是
    幂等键该有的样子。

    ─────────────────────────────────────────────────────────
    【「故意改坏跑一遍」的结果 —— 有一个反直觉的发现】

    我按计划把**去重那一段抠掉**跑了一次：它**没有红**。
    原因是这道闸有两层：查重是第一层，数据库上
    `(user_id, idempotency_key)` 那条唯一约束是第二层 ——
    抠掉第一层之后，第二次 INSERT 会撞唯一约束，
    `_translate_integrity_error` 把它翻译成同一个 409 + 同一个 task。

    这也顺带暴露了第二层里的一个真 bug（已修）：那段兜底原先
    取的是「这个用户任意一个带 key 的任务」，在没有并发、只有
    一个任务的测试里看不出问题，但真走到那条路径时会把
    **别的任务**当成重复的那个返回给客户端 —— 用户点生成，
    拿回来一个他上周做的视频。

    真正能让这条红的是**把幂等键存成 null**（也就是「忘了登记」）：
    两层一起失效，第二次提交会建出第二个任务、再扣一次钱。
    我按那个改法验过一次，确实是红的，失败信息就是那个
    多出来的任务和 `idempotency_key: null`。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "连点两次的人")

    first = await submit_image(api, headers, idempotency_key="same-key")
    assert first.status_code == 200, first.text
    after_first = await _snapshot(api, headers)

    second = await submit_image(api, headers, idempotency_key="same-key")

    assert second.status_code == 409, second.text
    body = second.json()
    assert body["code"] == "DUPLICATE_REQUEST"
    assert body["task"]["id"] == first.json()["id"], "要带回**那一个**已存在的任务"
    assert body["task"]["status"] == "succeeded"

    assert await _snapshot(api, headers) == after_first, (
        "重复提交不该再建任务，也不该再扣一次钱"
    )


async def test_不同的幂等键是两次真实提交(api: httpx.AsyncClient) -> None:
    """先确认反向：幂等键不同时，确实会建两个任务。

    【为什么要这条】否则上面那条「只建一个」可能只是因为
      第二个请求压根没被处理。有了这一条，「只建一个」才是幂等键的功劳。
    """
    headers, _ = await new_user(api, "故意建两个的人")

    await submit_image(api, headers, idempotency_key="k-a")
    await submit_image(api, headers, idempotency_key="k-b")

    tasks = (await api.get("/tasks", headers=headers)).json()
    assert tasks["total"] == 2
    assert (await _account(api, headers))["balance"] == 42, "两张图扣 8"


async def test_缺_idempotency_key_是_400_INVALID_REQUEST(api: httpx.AsyncClient) -> None:
    """⚠️ 形状错误走 `INVALID_REQUEST`，而且必须是**带 code 的 400**。

    【为什么这条不能只断状态码】FastAPI 默认会把「缺必填字段」返回成
    422 + `{"detail":[{...}]}` —— 那个形状**破了「无信封」契约**：
    前端从顶层读 `code`，读出来是 null，于是显示
    「服务端返回 HTTP 422，且响应体里没有 message 字段」。
    用户看不懂，而真正的原因只是它少发了一个字段。

    所以 `errors.py` 里那个 `RequestValidationError` 处理器是必需的，
    这条测试就是它的守卫。
    """
    headers, _ = await new_user(api, "少发字段的人")

    res = await api.post("/generation/image", json={"prompt": "只有提示词"}, headers=headers)

    assert res.status_code == 400, res.text
    body = res.json()
    assert body["code"] == "INVALID_REQUEST"
    assert "idempotency_key" in body["message"], (
        f"message 要指出是哪个字段（它是给开发看的），实际 {body['message']!r}"
    )


# ── 配额 ──────────────────────────────────────────────────────


async def test_每天最多_20_个任务(api: httpx.AsyncClient) -> None:
    """§7.5 第 3 道闸：每日上限。

    ─────────────────────────────────────────────────────────
    【为什么走 fake provider 还要真做这道闸】

    因为它的价值在于**让 UI 里那句「已达今日生成上限」真的被执行过**。
    不写的话，那句话在真机上长什么样没人知道 —— 而它正是
    上线第一天最可能被用户撞到的提示（20 个任务对重度用户来说
    一上午就到）。等到那时才发现文案或形状不对，代价比现在高。

    【为什么连发 20 次不算慢】因为 fake provider 是纯内存的，
    一次提交几毫秒。真实的 20 秒视频要等 10 分钟，那时这条用例
    会改用注入时钟的方式（B3 的 worker 测试已经有这个计划）。
    ─────────────────────────────────────────────────────────
    """
    headers, _ = await new_user(api, "用满额度的人")
    # 20 张图要 80 积分，注册只给 50 —— 先补足。
    await grant_credits(api, "用满额度的人", 200)

    for i in range(20):
        res = await submit_image(api, headers, idempotency_key=f"q{i}")
        assert res.status_code == 200, f"第 {i + 1} 个任务就被拒了：{res.text}"

    over = await submit_image(api, headers, idempotency_key="q20")

    assert over.status_code == 429, over.text
    assert over.json()["code"] == "RATE_LIMITED"
