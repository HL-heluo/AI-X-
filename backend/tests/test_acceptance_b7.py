"""§15.1 端到端验收 —— 一条剧本走完全程，然后逐笔对账。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件和别的契约测试的分别】

别的文件各测一块（记账、队列、转存、标识）。这一个测**它们接起来
之后还是不是同一个故事**：

    注册送 50 → 文生图（冻 4、结 4）→ 图生视频（冻 32、结 24、退 8）
    → 余额 22、冻结 0

§15.1 就是这么一条剧本。它同时是「跨时间」的：两条任务都不是在请求
路径上完成的，是 worker 一轮一轮推过去的。

【为什么它跑的是 `scripted` 而不是默认的 `fake`】

因为 fake **提交即完成**：整条路走完一次 `poll` 都不会发生，于是
「谁把任务推到终态」「`provider_calls` 里有几次查询」这些问题在这条
剧本里全都看不见。`ScriptedProvider` 只改「什么时候算完」这一件与
契约无关的事，计价仍逐字来自 `FakeProvider` —— 所以它算出来的账
和前 138 条前端测试里写死的数**必须是同一个**。

【这条剧本**不能**证明什么（别把它的绿读成「接了真外部就没问题」）】

  · 即梦的签名能不能过网关、请求 JSON 的字段名对不对 —— 替身与
    `MockTransport` 都只能证明**我们自己自洽**（HANDOFF §2.6）；
  · 桶 / CDN / 云厂商 —— 这里跑的是 `STORAGE=local`，字节落的是磁盘；
  · 真进程里才看得见的东西：静态挂载、后台线程、日志、启动横幅。

那三件分别由 §2.6 的清单与「真进程手工验收」负责。**这一条剧本的
存在不改变那个结论，只是把「逻辑上应该对」变成「当场验过」。**

【为什么断言里到处是「另一个会话 / 另一条连接」】

因为「任务状态不放在进程内存里」是铁律，而它在测试进程里**天然
无法被反证** —— 同一个会话读同一个 ORM 对象，怎么写都是绿的。
所以每一处「读到终态」都**另开连接**去读：那样才对「状态在文件里」
这件事有区分力。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from _helpers import PASSWORD, new_user, submit_image, submit_video
from _providers import ScriptedProvider
from app import worker
from app.database import build_engine
from app.enums import AssetKind, LedgerKind, TaskStatus
from app.models import Asset, CreditLedger, ProviderCall, Task
from app.services.transcode import read_implicit_marker
from app.types import utcnow

# ── 契约值（§7.2 / §12.1）—— 前端那 138 条里写死的同一组数 ─────────
# 【为什么在这里再抄一遍而不是从代码里 import】
# 从 `pricing.py` import 的话，算式改了这里**跟着一起改**，于是这条
# 验收对「算出来的数和前端期待的不是同一个」这件事完全没有感觉。
# 逐字抄一遍，改坏了才红。
REGISTER_GRANT = 50
IMAGE_SETTLE = 4
VIDEO_FREEZE = 32
VIDEO_SETTLE = 24
VIDEO_REFUND = VIDEO_FREEZE - VIDEO_SETTLE  # 8
EXPECTED_BALANCE = REGISTER_GRANT - IMAGE_SETTLE - VIDEO_SETTLE  # 22

FORBIDDEN = ("available", "provider_url", "storage_key", "params_json")
"""绝不能出现在任何响应体里的键名（同 `test_contract_shapes_b2.py`）。"""


@pytest.fixture(autouse=True)
def _clean_poll_schedule() -> None:
    """忘掉「上一轮问过 provider」—— `worker._last_poll_round` 是模块级全局。

    不清的话，上一条用例留在里面的时间戳会让这一条的第一次轮询被
    **静默跳过**，表现是「任务没往前推」，而代码是对的。理由详见
    `test_worker_b3.py` 里那个同名夹具。
    """
    worker.reset_poll_schedule()


@dataclass
class Script:
    """一条剧本跑完之后，手里剩下的东西。

    【为什么收成一个对象，而不是让每个用例各跑一遍自己的剧本】
    因为 §15.1 的价值恰恰在于「**一条**剧本」。四个用例各写一遍
    剧情的后果不是重复，是它们会慢慢变成四个略有不同的故事 ——
    然后「账对得上」这句话就不再覆盖任何一条完整的路。
    """

    headers: dict[str, str]
    username: str
    db_url: str
    media_root: Path
    image_task: dict
    video_task: dict
    image_asset: dict
    video_asset: dict
    responses: dict[str, str]


def _scripted_request(scripted: ScriptedProvider) -> None:
    """让两条任务都需要**问两次**才有结果。

    第一次 `poll` 回 `None`（对方还在生成），第二次回成品。这正是
    「跨时间的真排队」的形状 —— 若 `polls_before_done == 0`，任务会在
    出队那一轮就结束，`provider_calls` 里也不会有「问了还没好」的行。
    """
    scripted.polls_before_done = 1


async def _run_15_1(
    api: httpx.AsyncClient,
    api_session: Session,
    scripted: ScriptedProvider,
    *,
    username: str,
) -> Script:
    """§15.1 的剧本。**唯一的一份。**"""
    _scripted_request(scripted)
    headers, _ = await new_user(api, username)
    responses: dict[str, str] = {}

    # ── ① 注册 ────────────────────────────────────────────────
    me = (await api.get("/me", headers=headers)).json()
    responses["me_after_register"] = str(me)
    assert me["credit_account"]["balance"] == REGISTER_GRANT, "注册赠送不是契约值"
    assert me["credit_account"]["frozen"] == 0

    # ── ② 文生图 ──────────────────────────────────────────────
    image_res = await submit_image(api, headers, idempotency_key="15-1-image")
    responses["generation_image"] = image_res.text
    assert image_res.status_code == 200, image_res.text
    image_task = image_res.json()
    # 走替身（异步接口）时提交只拿到回执 —— 这一步正是「真 provider
    # 长什么样」。fake 那支会在这里直接给 `succeeded`。
    assert image_task["status"] == "submitted", image_task
    assert (await api.get("/me", headers=headers)).json()["credit_account"]["frozen"] == IMAGE_SETTLE

    t0 = utcnow()
    first = worker.run_once(api_session, now=t0)
    assert first.advanced == [], "第一次问就说好了？那不是跨时间的排队"
    worker.run_once(api_session, now=t0 + timedelta(seconds=11))
        # 11 秒是为了跨过 `provider_poll_interval_sec`（10），不是等它。

    image_row = _task_from_new_connection(api, image_task["id"])
    assert image_row.status is TaskStatus.succeeded
    assert image_row.settled_amount == IMAGE_SETTLE
    assert (await api.get("/me", headers=headers)).json()["credit_account"]["balance"] == (
        REGISTER_GRANT - IMAGE_SETTLE
    )

    # ── ③ 从 /assets 挑那张图，用它做图生视频 ────────────────────
    assets_res = await api.get("/assets", headers=headers)
    responses["assets_after_image"] = assets_res.text
    image_asset = _pick(assets_res.json()["items"], AssetKind.image, task_id=image_task["id"])

    video_res = await submit_video(
        api,
        headers,
        source_asset_id=image_asset["id"],
        idempotency_key="15-1-video",
    )
    responses["generation_video"] = video_res.text
    assert video_res.status_code == 200, video_res.text
    video_task = video_res.json()
    assert video_task["status"] == "submitted", video_task
    # 冻结必须是**契约值 32**：(输入 0 + 请求 5 + 余量 3) × 4。图片没有时长。
    account = (await api.get("/me", headers=headers)).json()["credit_account"]
    assert account["frozen"] == VIDEO_FREEZE, account

    worker.run_once(api_session, now=t0 + timedelta(seconds=22))
    worker.run_once(api_session, now=t0 + timedelta(seconds=33))

    video_row = _task_from_new_connection(api, video_task["id"])
    assert video_row.status is TaskStatus.succeeded
    assert video_row.settled_amount == VIDEO_SETTLE

    # ── ④ 收尾：账、资产、对账表 ──────────────────────────────
    final = (await api.get("/me", headers=headers)).json()["credit_account"]
    assert (final["balance"], final["frozen"]) == (EXPECTED_BALANCE, 0), final

    ledger_res = await api.get("/credits/ledger?page_size=100", headers=headers)
    responses["ledger"] = ledger_res.text
    video_asset = _pick(
        (await api.get("/assets", headers=headers)).json()["items"],
        AssetKind.video,
        task_id=video_task["id"],
    )
    responses["assets_final"] = str(video_asset)
    responses["tasks"] = (await api.get("/tasks", headers=headers)).text
    responses["task_detail"] = (await api.get(f"/tasks/{video_task['id']}", headers=headers)).text

    return Script(
        headers=headers,
        username=username,
        db_url=_db_url(),
        media_root=_media_root(),
        image_task=image_task,
        video_task=video_task,
        image_asset=image_asset,
        video_asset=video_asset,
        responses=responses,
    )


# ══════════════════════════════════════════════════════════════
# 读回来的三个工具 —— 共同点是**都不走请求路径上那个会话**
# ══════════════════════════════════════════════════════════════


def _db_url() -> str:
    from app.config import get_settings

    return get_settings().database_url


def _media_root() -> Path:
    from app.config import get_settings

    return Path(get_settings().media_root)


def _fresh_engine() -> Engine:
    """**另建一个引擎**，指到同一个库文件上。

    ─────────────────────────────────────────────────────────
    【为什么这不是「多此一举」】

    铁律是「任务状态不放在进程内存里」，而它在这条测试里最容易被
    假的绿掉：`api_session` 里那个 ORM 对象可能是**已经加载过**的
    （`expire_on_commit=False`），于是断言读到的是「worker 动手之前」
    的样子 —— 或者反过来，一个把状态放在模块级字典里的实现也能通过。

    另建引擎 = 另开连接池 = 另一条 TCP/文件句柄，读到的东西只可能
    来自**库文件**。这才对那句话有区分力。
    ─────────────────────────────────────────────────────────
    """
    engine = build_engine(_db_url())
    return engine


def _task_from_new_connection(api: httpx.AsyncClient, task_id: int) -> Task:
    """从**另一条连接**读任务行（见 `_fresh_engine`）。"""
    del api  # 参数留着是为了让调用点读起来是「这个剧本里的那条任务」
    engine = _fresh_engine()
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as s:
            row = s.get(Task, task_id)
            assert row is not None, f"任务 {task_id} 不在库里"
            s.expunge(row)
            return row
    finally:
        engine.dispose()


def _pick(items: list[dict], kind: AssetKind, *, task_id: int) -> dict:
    matches = [a for a in items if a["kind"] == kind and a["task_id"] == task_id]
    assert matches, f"任务 {task_id} 没有 {kind} 资产：{[a['kind'] for a in items]}"
    return matches[0]


def _asset_path(asset: dict) -> Path:
    """从 `public_url` 反推磁盘路径。

    【为什么敢用 `split` 而不是引一个拼接函数】因为 `STORAGE=local`
    下 `public_url` 就是 `{PUBLIC_BASE_URL}/media/{storage_key}`，
    而这条剧本跑的正是 local。**它刻意不是**通用的取路径方式：
    `STORAGE=oss` 时字节不在本地，这一段就不成立（那也是 §2.6 那条
    清单里第 ④ 步要人真去看桶的原因）。
    """
    key = asset["public_url"].split("/media/", 1)[-1]
    return _media_root() / key


# ══════════════════════════════════════════════════════════════
# ① 账：三段式逐笔对得上
# ══════════════════════════════════════════════════════════════


async def test_15_1_账逐笔对得上_冻结结算退回三段都在(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    script = await _run_15_1(api, api_session, scripted, username="账要对得上的人")

    rows, _ = _ledger_of(_db_url(), video_task_id=script.video_task["id"])
    assert [(r.kind, r.amount) for r in rows] == [
        (LedgerKind.freeze, VIDEO_FREEZE),
        (LedgerKind.settle, VIDEO_SETTLE),
        (LedgerKind.refund, VIDEO_REFUND),
    ], [(r.kind, r.amount) for r in rows]
    # 【这条断言的分量，是改坏验出来的】把 `settle_and_refund` 里那行
    # 退款流水删掉，红的是**这里** —— 而本用例最后那句「余额 22 / 冻结 0」
    # 照样绿。因为差额本来就靠「`frozen` 少 freeze、`balance` 只少
    # `settle`」体现，退款那行只是**账本**，不是账。
    # 也就是说：只看余额的话，「用户被退了多少」在库里是不可查的。

    # 快照逐个对 —— 这是**唯一**能证明「冻结只是把可用搬走、没有花钱」的东西。
    # 只看最终余额的话，「先扣 24、再补 8」这种写法也能得到同一个 22。
    #
    # ⚠️ 冻结那一行的 `balance_after` 是 **46，不是 14** —— 这是 §7.2 的
    # 设计，不是笔误：`balance` 只有**结算**才动，冻结动的是 `frozen`，
    # 而用户看到的「可用」是现算的 `balance − frozen` = 46 − 32 = 14。
    # 把这里写成 14 的话，就变成「冻结时余额也少了」—— 那是另一种账法，
    # 而它会和前端 `available = balance − frozen` 那句话对不上。
    assert [(r.balance_after, r.frozen_after) for r in rows] == [
        (REGISTER_GRANT - IMAGE_SETTLE, VIDEO_FREEZE),  # 冻 32：余额 46 不动，可用 14
        (EXPECTED_BALANCE, 0),                          # 结 24：余额 46 → 22
        (EXPECTED_BALANCE, 0),                          # 退 8：余额不动，钱从冻结里回来
    ], [(r.balance_after, r.frozen_after) for r in rows]

    # 把上面那句翻译成用户能感觉到的话：冻结期间的可用额是 14。
    assert rows[0].balance_after - rows[0].frozen_after == 14

    # 文生图那条路**只有两段**：冻 4、结 4 —— 没有退款行，
    # 因为 `_write_ledger` 对「退回 0 积分」是**静默跳过**的
    # （零额流水有表约束挡着）。所以「三段式」是**最多**三段。
    image_rows, _ = _ledger_of(_db_url(), video_task_id=script.image_task["id"])
    assert [(r.kind, r.amount) for r in image_rows] == [
        (LedgerKind.freeze, IMAGE_SETTLE),
        (LedgerKind.settle, IMAGE_SETTLE),
    ], [(r.kind, r.amount) for r in image_rows]

    # §15.1 那句原话：**余额 = 赠送 − 实计之和**。
    spent = sum(r.amount for r in rows if r.kind is LedgerKind.settle)
    spent += sum(r.amount for r in image_rows if r.kind is LedgerKind.settle)
    me = (await api.get("/me", headers=script.headers)).json()["credit_account"]
    assert me["balance"] == REGISTER_GRANT - spent == EXPECTED_BALANCE
    assert me["frozen"] == 0


def _ledger_of(db_url: str, *, video_task_id: int) -> tuple[list[CreditLedger], int]:
    """按任务取出流水（**旧的在前面**，方便逐笔对三段式）。"""
    engine = build_engine(db_url)
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as s:
            stmt = (
                select(CreditLedger)
                .where(CreditLedger.task_id == video_task_id)
                .order_by(CreditLedger.id)
            )
            rows = list(s.scalars(stmt))
            for r in rows:
                s.expunge(r)
            return rows, len(rows)
    finally:
        engine.dispose()


# ══════════════════════════════════════════════════════════════
# ② 跨重启：状态在库文件里，不在进程内存里
# ══════════════════════════════════════════════════════════════


async def test_15_1_任务跨重启还在_换一条连接读得到终态(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """拿同一个 id，从**另一条连接**再取一次。

    ─────────────────────────────────────────────────────────
    【它测的不是「能不能查库」】

    而是铁律那句话：**任务状态不放在进程内存里。** 一个把状态存进
    `dict` 的实现，在这条测试里会红 —— 因为另一条连接看不到它。
    同一个会话里读同一个对象是**没有区分力**的（怎么都对），
    所以这条用例的断言全都走 `_task_from_new_connection`。

    【顺带钉住的两件事】
    · `provider_url` 在成功收尾后被**清空**了（它只活 1 小时，
      不是资产真相 —— `test_contract_shapes_b2` 扫的是响应，
      这里扫的是列）；
    · `queued_at` / `submitted_at` / `finished_at` 三个时间戳都在，
      而且顺序是对的。「跨时间的排队」如果只有终态、没有这几个
      时间戳，事后就没法回答「它到底排了多久」。
    ─────────────────────────────────────────────────────────
    """
    script = await _run_15_1(api, api_session, scripted, username="要跨重启的人")

    for task in (script.image_task, script.video_task):
        row = _task_from_new_connection(api, task["id"])
        assert row.status is TaskStatus.succeeded
        assert row.provider_url is None, f"{row.provider_url!r} 不该留在库里"
        assert row.queued_at and row.submitted_at and row.finished_at
        assert row.queued_at <= row.submitted_at <= row.finished_at
        assert row.settled_amount is not None  # 成功 ⟹ 有结算额（B1 的表约束）


# ══════════════════════════════════════════════════════════════
# ③ 字节与标识：`public_url` 打得到，且读得出「这是 AI 生成的」
# ══════════════════════════════════════════════════════════════


async def test_15_1_取回_public_url_拿得到字节_而且读得出隐式标识(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """§15.1 的最后一步，也是 B5 留下的那个「只在测试进程里验过」。

    ─────────────────────────────────────────────────────────
    【为什么这一步必须是「真的取一次」】

    标识是**法律义务**，而「写进去了」如果只由写它的那份代码自己
    声明，它永远是对的。所以要：拿响应里那个 `public_url` → 真的请求
    一次 → 拿到字节 → 从落盘的那份文件里**读回**标识，并确认里面
    有这条任务的 id。

    【为什么这里读的是磁盘，而不是走 `/media` 之外的路径】
    因为 `read_implicit_marker` 是**验收的读路径**（B5 就为这件事
    写好的）。它读的正是用户能拿到的那一份字节的落盘形态，
    而 `GET /media/...` 那一步验的是「这份字节能被取到」——
    两件事都做，才拼出完整的一句话。
    ─────────────────────────────────────────────────────────
    """
    script = await _run_15_1(api, api_session, scripted, username="要看标识的人")

    for asset, task_id, expect_format in (
        (script.image_asset, script.image_task["id"], "PNG"),
        (script.video_asset, script.video_task["id"], "video"),
    ):
        url = asset["public_url"]
        path = url.split("/media/", 1)[-1]
        got = await api.get(f"/media/{path}")
        assert got.status_code == 200, f"{url} 取不回来：{got.status_code}"
        assert len(got.content) == asset["size_bytes"], (
            "响应里的 size_bytes 和真取回来的字节数不一致 —— "
            "那说明 size_bytes 记的不是落盘的那一份"
        )

        marker = read_implicit_marker(_asset_path(asset))
        assert marker["format"] == expect_format, marker
        if expect_format == "PNG":
            # EXIF 那一支：ASCII 版进最通用的 `ImageDescription`，
            # 完整的中文版进 `UserComment`（UTF-16-BE）。两个都要在。
            assert f"task={task_id}" in (marker["ImageDescription"] or ""), marker
            assert "AI" in (marker["ImageDescription"] or ""), marker
            assert f"task={task_id}" in (marker["UserComment"] or ""), marker
            assert marker["xmp"], "没有 XMP 包"
        else:
            assert f"task={task_id}" in (marker["comment"] or ""), marker
            assert marker["title"], "MP4 的 title 是标识的一部分"

    # 封面也是 AI 生成的一帧，所以它同样带标识（B5 的决定）。
    cover = _pick(
        (await api.get("/assets", headers=script.headers)).json()["items"],
        AssetKind.thumbnail,
        task_id=script.video_task["id"],
    )
    assert f"task={script.video_task['id']}" in (
        read_implicit_marker(_asset_path(cover))["ImageDescription"] or ""
    ), "封面没带标识"


# ══════════════════════════════════════════════════════════════
# ④ 对账表：provider 到底被调了几次
# ══════════════════════════════════════════════════════════════


async def test_15_1_provider_calls_里留下_submit_和每一次查询(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """§11.1 的成本对账表 —— 这张表 B1 就建好，到 B5 才第一次被写。

    ─────────────────────────────────────────────────────────
    【为什么「问了但还没好」那一次最要紧】

    一条真视频会问几十次，其中**绝大多数**都是「还没好」（替身这里
    是 1 次）。如果只有拿到结果的那一次被记下来，对账表会显示
    「每条视频只问了 1 次」—— 于是「闸门开得够不够」「是不是在刷
    对方的接口」这两个问题全都查不出来。所以断言里那个 `>= 1` 次
    「没有结果的查询」是**核心**，不是凑数。

    【为什么按任务分别断言，而不是数全表】
    全表条数会随剧本细节变化（比如将来给图片路径也加一次轮询），
    而「每条任务各被问了几次」才是对账要回答的问题。
    ─────────────────────────────────────────────────────────
    """
    script = await _run_15_1(api, api_session, scripted, username="要对账的人")

    for task_id in (script.image_task["id"], script.video_task["id"]):
        rows = _calls_of(_db_url(), task_id)
        submits = [r for r in rows if r.action == "submit"]
        queries = [r for r in rows if r.action == "query"]
        assert len(submits) == 1, f"任务 {task_id} 提交了 {len(submits)} 次"
        assert len(queries) >= 2, (
            f"任务 {task_id} 只被问了 {len(queries)} 次 —— "
            "「问了还没好」的那几次没被记下来"
        )
        # 替身不发 HTTP，所以状态码是**诚实的 NULL** —— 一个编出来的
        # 200 会让对账表看起来像真的打过网络。（真即梦那支有真状态码，
        # 见 `test_jimeng_b6.py`。）
        assert all(r.http_status is None for r in rows), rows
        assert all(r.latency_ms is not None for r in rows), "延迟没记"
        # ⚠️ 表里**不得**出现任何请求头/签名/AK —— 见 `models.ProviderCall`。
        assert all(r.resp_message is None or "http" not in r.resp_message.lower() for r in rows)


def _calls_of(db_url: str, task_id: int) -> list[ProviderCall]:
    engine = build_engine(db_url)
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as s:
            stmt = (
                select(ProviderCall)
                .where(ProviderCall.task_id == task_id)
                .order_by(ProviderCall.id)
            )
            rows = list(s.scalars(stmt))
            for r in rows:
                s.expunge(r)
            return rows
    finally:
        engine.dispose()


# ══════════════════════════════════════════════════════════════
# ⑤ 契约守卫：这条剧本里出现过的所有响应
# ══════════════════════════════════════════════════════════════


async def test_15_1_整条剧本的响应里没有那几个键(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """`available` / `provider_url` / `storage_key` / `params_json`。

    【它和 `test_contract_shapes_b2` 那条扫全端点的不重复】
    那条打的是「每个端点各一次」；这条打的是**一条真实的剧本**：
    任务真的跑完了、资产真的落盘了、流水真的有六条。全字段的
    ORM 对象最容易在这种「有内容的响应」里被顺手丢出去 ——
    而一个刚注册、什么都是空的响应里，它压根不会出现。
    """
    script = await _run_15_1(api, api_session, scripted, username="要扫响应的人")

    assert script.responses, "剧本没收集到任何响应"
    for name, raw in script.responses.items():
        for key in FORBIDDEN:
            assert key not in raw, f"{name} 的响应里出现了 {key!r}：{raw[:400]}"


# ══════════════════════════════════════════════════════════════
# ⑥ 一条「这条剧本真的走进去了」的守卫
# ══════════════════════════════════════════════════════════════


async def test_15_1_剧本走的是异步路径_不是提交即完成(
    api: httpx.AsyncClient, api_session: Session, scripted: ScriptedProvider
) -> None:
    """⚠️ 这条守卫钉的是**剧本的形状本身**，不是某一条账。

    ─────────────────────────────────────────────────────────
    【它守的是「别的用例会不会静默失效」，所以断言长得不像记账】

    ①–⑤ 那些断言，在「provider 提交即完成」的世界里**大部分照样成立**：
    余额还是 22、流水还是那三段、资产还是带标识。

    ——这不是推理，是**实测**：把 `ScriptedProvider.submit` 改回
    「直接给成品」（即让它退化成 fake 的形状），红的是**整个文件**，
    而红的理由是**剧本里那两三句内联断言**
    （`assert image_task["status"] == "submitted"`），不是 ①–⑤ 自己。
    也就是说，整个文件对「剧本形状」的防护全押在那几句话上 ——
    而它们是最容易被顺手放松的：一句「先容忍两种形状吧」就能把整条
    剧本变回假的，而 ①–⑤ 会一起失去区分力。

    所以这里单独再钉一遍，而且钉到内联那两句**看不见**的粒度：
    两条任务各提交**一次**、各被问了**两次**（第一次「还没好」、
    第二次才拿到结果）。「问两次」正是「跨时间的排队」这句话的
    全部内容 —— 只断言 `status == "submitted"` 的话，一个「提交后
    立刻自己编一个成品」的实现也能过。
    ─────────────────────────────────────────────────────────
    """
    script = await _run_15_1(api, api_session, scripted, username="要看剧本形状的人")

    assert scripted.polls_before_done == 1, "剧本被改成提交即完成了"
    for task in (script.image_task, script.video_task):
        row = _task_from_new_connection(api, task["id"])
        assert row.submitted_at is not None
        # `queued_at` 在两条路上都会写（B3 的决定），所以它是剧本形状的
        # 一部分而不是异步路径的独有特征 —— 但「它存在」仍然排除了
        # 「一步到位、根本没过队列」那种形状。
        assert row.queued_at is not None

    # 两次轮询各推进了一条任务：这正是「跨时间」的现场。
    assert scripted.poll_count >= 4, scripted.poll_count
    assert scripted.submit_count == 2, scripted.submit_count
