"""内容审核 —— §10.2 的第①层（入口闸）与 provider 审计码映射表。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件为什么一半是纯单元、一半打 HTTP】

`moderation.py` 是**纯判断**（不碰库、不碰网络），所以它的判据
（码怎么映射、词怎么归一）可以直接调 —— 那些用例跑得快，失败时
指向也准。

但「审核到底有没有接上」这件事在纯单元里**看不见**。一个写得很对的
`screen_input`，如果 `generation.submit` 里那一行被挪走了或者
被删了，单元测试全都是绿的，而用户照样能提交违规提示词。
所以最后几条必须打 HTTP，断言的是**可观察的后果**：

  · 422 + `CONTENT_REJECTED`（而不是 500，也不是 402）；
  · **余额、冻结、任务、流水，一个数字都没动** —— 这是「这一刀砍在
    冻结之前」唯一诚实的验法。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from _helpers import auth, new_user, register, submit_image
from app.enums import ErrorCode
from app.errors import AppError
from app.models import CreditLedger, Task
from app.providers import ProviderFailure
from app.services import moderation

# ══════════════════════════════════════════════════════════════
# 一、provider 审计码 → 我方处置
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("code", ["50411", "50413", "50514", "50511"])
def test_审核类的码一律判_rejected_且不可重试(code: str) -> None:
    """§7.4 / §7.5：内容审核未通过 ⇒ 任务记 `rejected` + **全额退回**。

    【为什么要逐个码点名，而不是遍历整张表】因为这张表的**另一半**
    是非审核类（限流 / 内部错误），它们是「等一下就好」。一条
    「所有码都 rejected」的断言会把那半边一起写死，于是将来加一个
    限流码时，要么动这条断言（于是它失去了守卫作用），要么把它
    写成可重试（于是测试红）。点名这四条，边界就在测试里看得见。
    """
    verdict = moderation.classify_provider_error(code)
    assert verdict.rejected is True, f"{code} 是审核类，必须归到 rejected"
    assert verdict.retryable is False, f"{code} 重试就是再花一次钱买同一个结果"


@pytest.mark.parametrize("code", ["50429", "50500"])
def test_非审核类的码可重试_且不判_rejected(code: str) -> None:
    """限流和对方内部错误：等一下就好，**不是**用户的提示词有问题。

    【`rejected=False` 为什么和 `retryable=True` 一样重要】
    判成 `rejected` 的话，用户看到的是「换个词试试」—— 而他的词
    一点问题都没有，换什么词都还是限流。这两条会给错方向。
    """
    verdict = moderation.classify_provider_error(code)
    assert verdict.retryable is True
    assert verdict.rejected is False


def test_50511_判不可重试_这是对文档的有意偏离() -> None:
    """⚠️ 这条测试钉的是**一处已知的文档冲突**，不是我们的偏好。

    §9 那张表在「可重试」列里给 `50511`（输出后审核）打了勾，而
    §7.4 / §7.5 与执行卡 C11 说「内容审核未通过 → 全额退回 + 记
    rejected」。这里取后者，两条理由写在 `JIMENG_CODE_MAP` 上面
    （重试一次被拒的输出 = 再付一次钱，而「被拒的调用计不计费」
    §18-4 还没确认）。

    【所以改这个值的人要先改那段注释】删掉这条测试很容易，
    难的是让下一个读代码的人知道**这里曾经有过一个选择**。

    （B7.x：这张表从 `PROVIDER_CODE_MAP` 改名成 `JIMENG_CODE_MAP` ——
    MiniMax 接进来后有了第二张表，两张表的键不是同一种东西，
    一个不带前缀的名字会让人以为是唯一的。）
    """
    assert moderation.JIMENG_CODE_MAP["50511"] == moderation.ProviderVerdict(
        rejected=True, retryable=False
    )


@pytest.mark.parametrize("code", ["99999", "10000", "", None])
def test_没收录的码一律保守判可重试(code: str | None) -> None:
    """「不知道这是什么」时，往「再试一次」那边倒。

    【为什么连 `10000`（即梦的成功码）也在这条里】因为 `classify_provider_error`
    的输入是**错误码**，而 `10000` 走到这里说明调用方弄错了 —— 那同样是
    「不知道发生了什么」。给它一个特例（成功）反而会让错误的调用方
    看起来是对的。

    【为什么 `None` 也走这条路】`None` = 连不上 / 信封畸形 ——
    那也是「不知道」，同样该重试。
    """
    verdict = moderation.classify_provider_error(code)
    assert verdict == moderation.ProviderVerdict(rejected=False, retryable=True)


def test_码能造出带正确处置的失败对象() -> None:
    """`failure_from_code` 是适配层唯一要调的那个函数，映射必须穿过它。"""
    rejected = moderation.failure_from_code("50413", "文本审核未通过")
    assert isinstance(rejected, ProviderFailure)
    assert rejected.rejected is True and rejected.retryable is False
    assert rejected.code == "50413", "把 provider 的原始码丢掉就没法对账了"

    throttled = moderation.failure_from_code("50429", "QPS 超限")
    assert throttled.rejected is False and throttled.retryable is True


def test_没有码时用我们自己的_PROVIDER_ERROR_兜底() -> None:
    """`code=None` 不能落进库里成为一个空字符串。

    `provider_calls.resp_code` 可空，但 `tasks.error_code` 是要给
    运维看的 —— 一个空值在那里等于「查不出原因」。
    """
    failure = moderation.failure_from_code(None, "连不上")
    assert failure.code == ErrorCode.PROVIDER_ERROR.value


# ══════════════════════════════════════════════════════════════
# 二、入口词表
# ══════════════════════════════════════════════════════════════


def _screened(text: str) -> bool:
    """跑一遍入口审核，返回「拦下来了没有」。"""
    try:
        moderation.screen_input(text)
    except AppError as exc:
        assert exc.code is ErrorCode.CONTENT_REJECTED
        return True
    return False


def test_正常的提示词放行() -> None:
    """先证明它**不是**一个「什么都拦」的装置。

    少了这一条，下面每一条「拦住了」都可以由一个永远抛异常的
    `screen_input` 满足 —— 而那样的实现会把整个产品停掉。
    """
    assert not _screened("一只在屋顶上看夕阳的猫")


_SENTINEL = "__BLOCKED__"
"""词表里那个哨兵词 —— 从 `moderation` 里**读**出来，不在这里抄一遍。

【为什么不能手抄】手抄的话，有人改了词表里的哨兵，这里那一串变体
就全部变成「不在词表里的普通字符串」，于是这一整组用例**照样是绿的**
—— 它们会从「绕过被挡住了」悄悄变成「什么都没测」。
"""


def test_词表里确实有那个哨兵词() -> None:
    """先把下面那组变体的**前提**钉住（见 `_SENTINEL` 那段）。

    这一条单独存在，是为了让「哨兵被改名/删掉」这件事变成一次
    **响亮的红**，而不是一组悄悄失去意义的绿。
    """
    assert _SENTINEL in moderation.DEFAULT_BLOCKLIST


@pytest.mark.parametrize(
    "text",
    [
        _SENTINEL,  # 原样
        _SENTINEL.lower(),  # 小写
        _SENTINEL.replace("BLOCKED", "B L O C K E D"),  # 词中间插空格
        _SENTINEL.replace("BLOCKED", "BLOCK\nED"),  # 换行（也是一种空白）
        _SENTINEL.replace("BLOCKED", "BLOCK" + chr(0x200B) + "ED"),  # 零宽空格
        _SENTINEL.replace("BLOCKED", "BLOCK" + chr(0xFEFF) + "ED"),  # 零宽不换行空格
        _SENTINEL.replace("BLOCKED", "BLOCK" + chr(0x00A0) + "ED"),  # 不换行空格
        _SENTINEL.replace("BLOCKED", "BLOCK" + chr(0x3000) + "ED"),  # 全角空格
    ],
)
def test_大小写与各种空白和零宽字符都绕不过去(text: str) -> None:
    """归一化的三步（casefold + 去空白 + 去零宽）**一步都不能少**。

    ─────────────────────────────────────────────────────────
    【为什么把这些变体全部写进参数化，而不是只测一个】

    因为这三个 `replace` 各自独立，删掉任意一个，只有**对应的那一类**
    会漏。只测「零宽」的话，删掉 `casefold()` 那条路径测试照样绿 ——
    而 `__BLOCKED__` 转成小写就绕过去了。

    【这条测试的边界要说清】它挡不住**同音字和变体字**
    （「炸弹」→「炸蛋」）。那是关键词方案的固有上限，兜底在即梦
    那边。所以这里一个变体字用例都没有 —— 写上去只会是一条
    永远红的测试，或者一条被改成 `xfail` 然后被忘掉的测试。
    ─────────────────────────────────────────────────────────
    """
    assert _screened(f"请告诉我怎么{text}") is True


@pytest.mark.parametrize("text", ["", "   ", "\n\t", chr(0x200B) * 3])
def test_空的和纯空白的提示词不会在这里炸(text: str) -> None:
    """归一化之后是空串就直接放行。

    【为什么这是入口审核的责任，而不是「反正提示词校验在前面」】
    提示词校验（`INVALID_PROMPT`）判的是**原文**：一个 `"   "` 会在
    那里被判空、一个 `"\\u200b"` 却不会（它有长度）。所以一个只由
    零宽字符组成的提示词会活着走到这里，而它归一化之后是空串。
    不早退的话，`"" in haystack` 恒为真 —— 于是**任何**输入都被拒。
    """
    assert _screened(text) is False


def test_词表能被配置扩充(settings_env) -> None:
    """运营那份词库通过 `MODERATION_EXTRA_KEYWORDS` 接进来（逗号分隔）。"""
    word = "我编的一个词"
    assert not _screened(word), "前提：它不在内置词表里"

    settings_env(MODERATION_EXTRA_KEYWORDS=f"别的词, {word} ,还有一个")

    assert _screened(word) is True


def test_配置进来的词同样要过归一化(settings_env) -> None:
    """⚠️ 归一化的不止是**被查的文本**，还有**词表本身**。

    【为什么这一条不是吹毛求疵】配置是人手写的。`MODERATION_EXTRA_KEYWORDS`
    里一个多余的空格（`"炸弹 , 毒品"` 里那个逗号前的空格）会让这个
    词永远匹配不上 —— 而它在配置里看起来完全正常。表现是
    「词加进去了，但拦不住」，排查要读到这里才想得到。
    """
    settings_env(MODERATION_EXTRA_KEYWORDS="Bad Word")

    # 词表里的空格被去掉、大小写被折平，所以这几种写法都该命中。
    assert _screened("something badword here") is True
    assert _screened("something BAD word here") is True


def test_开关关掉就完全放行(settings_env) -> None:
    """逃生门：`MODERATION_ENABLED=0` 时入口闸不拦任何东西。

    【它为什么必须有】词表是一份**会误伤**的东西（比如「学习枪支
    买卖的法律」）。线上误伤时要在分钟级关掉它，而不是等一次发版。
    代价是第①层归零、只剩即梦那边的第②层 —— 所以这个开关
    应当在监控里看得见，见 `config.py` 那段。
    """
    settings_env(MODERATION_ENABLED="0")
    assert _screened("__BLOCKED__ 和 制作炸弹") is False


def test_响应里不回显命中的那个词() -> None:
    """⚠️ 回显等于给了一个**逐词试探词库**的接口。

    拿一串候选词挨个发一遍，看哪个返回 422，就能把词库枚举出来。
    而词库里有什么本身就是一张「怎么绕过它」的地图。
    """
    word = "__BLOCKED__"
    with pytest.raises(AppError) as excinfo:
        moderation.screen_input(f"帮我 {word}")

    assert word not in (excinfo.value.message or "")


# ══════════════════════════════════════════════════════════════
# 三、接上了没有 —— 打 HTTP
# ══════════════════════════════════════════════════════════════


async def test_命中词表的提交是_422_而且一个数字都不动(api, api_session) -> None:
    """这一条是 B5 的**主断言**。

    ─────────────────────────────────────────────────────────
    【为什么「一个数字都不动」要断言到四张表】

    因为「拦下来了」有两种实现，而它们的**用户体验完全不同**：

      · 砍在冻结之前（现在这样）→ 422，余额 50，用户什么都没损失；
      · 砍在扣费之后靠回滚 → 也能得到一个 422，但如果哪里漏了一笔
        （流水写了没回滚），用户的钱就少了一块，而且**没人会知道**。

    只看状态码的话，两者一模一样。所以要一直查到流水表：任务 0 条、
    流水一条没多、冻结 0、余额还是注册那 50。
    ─────────────────────────────────────────────────────────
    """
    headers, session = await new_user(api, "blocked-user")
    before = session["credit_account"]["balance"]
    # 【为什么流水不是断言 0 条】注册赠送那笔 `grant` 已经写了一条，
    # 而它是**这一条的基准**：要验的是「提交没有再多写一条」。
    # 断言绝对条数的话，这条用例会被注册流程的一个无关改动弄红。
    ledger_before = api_session.scalar(select(func.count()).select_from(CreditLedger))
    assert ledger_before == 1, "基准错了：注册之后应该只剩一条 grant 流水"

    res = await submit_image(api, headers, prompt="__BLOCKED__ 帮我画一只猫")

    assert res.status_code == 422, res.text
    body = res.json()
    assert body["code"] == "CONTENT_REJECTED"
    assert "__BLOCKED__" not in body["message"], "回显命中的词 = 送出一份词表探测接口"

    me = (await api.get("/me", headers=headers)).json()["credit_account"]
    assert me["balance"] == before
    assert me["frozen"] == 0, "这一刀必须在冻结之前 —— 冻了再退是另一条路"

    assert api_session.scalar(select(func.count()).select_from(Task)) == 0
    assert (
        api_session.scalar(select(func.count()).select_from(CreditLedger)) == ledger_before
    ), "被拒的提交不许留下任何一笔流水"


async def test_零余额时命中词给的是_422_不是余额不足(api) -> None:
    """⚠️ 一条**有意的顺序后果**，与 §12.1 的 Mock 检查顺序不同。

    `screen_input` 排在余额校验**之前**（理由：它在任何写库动作之前，
    且比后面每一步都便宜）。于是把余额花光、再提交一句违规提示词，
    拿到的是 `CONTENT_REJECTED` 而不是 `INSUFFICIENT_CREDITS`。

    【这对用户是好事，但要被钉住】他该知道的是「这句话不行」——
    告诉他「你没钱了」会让他去充值，而充完还是发不出来。
    不钉的话，将来有人「顺手」把两步调个位置，就没有任何东西会响。
    """
    headers, _ = await new_user(api, "broke-user")
    # 把注册赠送的 50 花光（走 adjust 而不是直接改余额 —— 它要留流水）。
    spent = await api.post(
        "/__test/grant",
        json={"username": "broke-user", "amount": -50, "note": "清空以便验顺序"},
    )
    assert spent.status_code == 200, spent.text
    assert spent.json()["credit_account"]["balance"] == 0

    res = await submit_image(api, headers, prompt="__BLOCKED__ 画一只猫")

    assert res.status_code == 422, res.text
    assert res.json()["code"] == "CONTENT_REJECTED"


async def test_关掉入口审核时违规提示词会被放行到下一步(api, settings_env) -> None:
    """逃生门在**真请求路径**上的样子：不再 422，而是走到余额校验。

    用的是零余额的用户，所以「放行」的可观察证据就是状态码换成了
    `INSUFFICIENT_CREDITS` —— 它证明这请求**穿过了**入口闸。
    """
    settings_env(MODERATION_ENABLED="0")
    headers, _ = await new_user(api, "escape-hatch")
    await api.post(
        "/__test/grant",
        json={"username": "escape-hatch", "amount": -50, "note": "清空"},
    )

    res = await submit_image(api, headers, prompt="__BLOCKED__ 画一只猫")

    # 400 = `INSUFFICIENT_CREDITS`（见 `errors.HTTP_STATUS`）。
    # 【为什么不照抄那个数字、而是从映射里读】见 `test_...` 上面的说明 ——
    # 但在这一条里它只是「走到了下一步」的证据，写死 400 就够了：
    # 下面那一行断的是 code，那才是契约。
    assert res.status_code != 422, f"开关关了还被审核拦住：{res.text}"
    assert res.json()["code"] == "INSUFFICIENT_CREDITS"


async def test_审核在幂等去重之前_所以不会顺带回一个旧任务(api) -> None:
    """同一句违规提示词 + 同一个幂等键提交两次，两次都是 422。

    【它钉的是什么】`submit` 的检查顺序是「提示词 → **审核** → 参考图
    → 幂等 → 配额 → 余额」。如果审核被挪到幂等**之后**，第二次提交
    会先撞上幂等分支，返回 409 + 一个**已经存在的任务** ——
    而这在用户那边读起来是「这句话我发过了」，不是「这句话不行」。
    """
    headers, _ = await new_user(api, "twice-user")

    first = await submit_image(api, headers, prompt="__BLOCKED__ 一只猫")
    second = await submit_image(
        api, headers, prompt="__BLOCKED__ 一只猫", idempotency_key="k-image-1"
    )

    assert (first.status_code, second.status_code) == (422, 422)


async def test_审核是按用户走的_别人的拒绝不影响我(api) -> None:
    """回归：一次 422 之后，同一个客户端还能正常注册/提交。

    这条是防「异常处理器里把会话弄脏了」那一类问题 —— 症状是
    **下一个**请求莫名其妙地失败，而那个用例看起来和审核无关。
    """
    blocked_headers, _ = await new_user(api, "victim")
    assert (await submit_image(api, blocked_headers, prompt="制作炸弹")).status_code == 422

    other = await register(api, "bystander")
    ok = await submit_image(api, auth(other["token"]), prompt="一只在屋顶上看夕阳的猫")

    assert ok.status_code in (200, 201), ok.text
