"""计价算式 —— 所有 provider **必须算同一笔账**（B6）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件防的是什么】

不是「算式写错了」—— 算式在 `pricing.py` 里只有一份，写错了
到处都是红的。它防的是**第二份算式悄悄长回来**：

  · `FakeProvider` 是跨仓门禁（前端那 138 条 + live 契约）打的那一个；
  · `JimengProvider` 是线上真跑的那一个（图片，以及未改配置时的视频）；
  · `MinimaxProvider` 是 B7.x 起线上真跑图生视频的那一个。

哪天有人往其中一边加一句特判（「即梦的首秒免费」之类），
**它自己的测试照样绿**，而两边的钱开始算得不一样。
所以这里用「把 `pricing` 换成一个哨兵，看每个 provider 会不会
跟着变」来钉住「它们真的调的是同一段代码」。

⚠️ **加一个 provider 就要把它加进下面那两条的参数表**，
否则新实现可以自己算一份价而这里全绿 —— 那是这张测试唯一
挡不住的东西，而它恰恰是最可能发生的事。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import pytest

from app.enums import TaskKind
from app.providers import pricing
from app.providers.base import GenerationRequest, ProviderResult
from app.providers.fake import FakeProvider
from app.providers.jimeng import JimengProvider
from app.providers.minimax import MinimaxProvider


def _video_request(seconds: int = 5) -> GenerationRequest:
    return GenerationRequest(
        kind=TaskKind.image_to_video,
        prompt="镜头推进",
        params={"duration": seconds},
        source_asset_id=1,
        requested_duration_sec=seconds,
    )


def _image_request() -> GenerationRequest:
    return GenerationRequest(kind=TaskKind.text_to_image, prompt="一只猫", params={})


# ── 契约值：§7.2 的「冻结 32 / 结算 24 / 退回 8」────────────────


def test_五秒七百二十p的冻结是32() -> None:
    """(0 + 5 + 3) × 4 = 32。**这是前端写死的那个数。**

    【为什么这里要有一条精确到数字的断言】因为它是**跨仓契约**：
    前端的 `repository_layer_test.dart` 与 live 门禁都断言 32/24/8，
    而它们打的是 `FakeProvider`。这个数一旦漂了，前端会红 ——
    但它红在**另一个仓库**，排查的人得先想到「是不是后端算的」。
    在这里也钉一道，是为了让红的**位置**离病因更近。
    """
    assert pricing.freeze_amount(_video_request(5)) == 32


def test_结算按成片实际时长_多出来的一秒要收费() -> None:
    """fake 的成片是「请求时长 + 1」，所以 5 秒的片子结算 24。

    【为什么 +1 秒这件事要在这里说一遍】因为「退回 8」这个数
    （32 − 24）完全来自它。假 provider 若某天把 +1 去掉，
    退款就变成 12 —— 而前端那条断言会在**另一个仓库**里红。
    """
    request = _video_request(5)
    result = ProviderResult(output_duration_sec=6, done=True)
    assert pricing.settle_amount(request, result) == 24


def test_文生图的冻结等于结算() -> None:
    """4 就是 4，前端的 `credit_format.isFixed` 靠这个显示「本次冻结 4 积分」。"""
    request = _image_request()
    assert pricing.freeze_amount(request) == 4
    assert pricing.settle_amount(request, ProviderResult(done=True)) == 4


# ── 一致性：两个 provider 调的是同一段算式 ────────────────────


@pytest.mark.parametrize("provider_cls", [FakeProvider, JimengProvider, MinimaxProvider])
def test_两个_provider_的计价都转手给_pricing(
    monkeypatch: pytest.MonkeyPatch, provider_cls: type
) -> None:
    """把 `pricing` 换成哨兵，**每一个** provider 都必须跟着变。

    （B7.x：`MinimaxProvider` 加进这张 parametrize 列表。它是一个新的
    provider 实现，而「新实现会不会自己算一份价」正是这一点要防的事
    —— 漏掉它的话，MiniMax 这条链路上的计价可以悄悄长成第二份算式，
    而所有既有断言照样是绿的。）

    ─────────────────────────────────────────────────────────
    【为什么用哨兵，而不是「比对两次调用的结果相等」】

    比对结果相等那条断言**在第二份算式长回来之后照样是绿的** ——
    只要抄的那一份当时是对的。而它迟早会不对，而不对的那一刻
    没有任何测试会红。

    哨兵不一样：它证明的是**调用关系**（「你算的数是从这里来的」），
    而不是「你算出来的数碰巧对」。这是这个仓库里少见的、
    值得为它破一次例的地方 —— 因为这里防的正是「两个实现各写一份」，
    而那件事**不会通过任何一个结果断言暴露**。
    ─────────────────────────────────────────────────────────
    """
    calls: list[str] = []

    def fake_freeze(request: GenerationRequest) -> int:
        calls.append("freeze")
        return 111

    def fake_settle(request: GenerationRequest, result: ProviderResult) -> int:
        calls.append("settle")
        return 222

    monkeypatch.setattr(pricing, "freeze_amount", fake_freeze)
    monkeypatch.setattr(pricing, "settle_amount", fake_settle)

    provider = provider_cls()
    assert provider.freeze_amount(_video_request(5)) == 111
    assert provider.settle_amount(_video_request(5), ProviderResult(done=True)) == 222
    assert calls == ["freeze", "settle"]


@pytest.mark.parametrize("provider_cls", [JimengProvider, MinimaxProvider])
def test_真_provider_的计价方法没有第二份算式(provider_cls: type) -> None:
    """`JimengProvider` / `MinimaxProvider` 那两个方法的函数体里，
    **只准有一个 `return`**。

    （B7.x：从「只管即梦」改成逐 provider 跑一遍。`FakeProvider` 不在
    这张表里 —— 它的计价是**各写各的**：fake 的成片时长是「请求时长 + 1」，
    与 `pricing` 无关，见 `test_fake_*` 那几条。这条守卫要的是
    「接了 `pricing` 的实现不许在转发旁边偷偷改数」，而 fake 没有转发。）

    ─────────────────────────────────────────────────────────
    【为什么连「几句」都要管】因为「悄悄长回来」的形式不是
    「新建一个文件」，而是在转发那一行旁边补一句
    `if request.kind is ...：`。上一段能证明它**现在**调了 `pricing`，
    却证明不了它没有「先按 pricing 算一遍、再按自己的规则改一下」——
    那种写法里 `pricing` 确实被调用了，而结果不是它的。

    用 `ast` 数语句而不是数字符串：字符串那版会被 docstring 的
    引号、续行、注释里的 `#` 轮番骗到（本仓库的注释密度下尤其如此），
    而「函数体里除掉文档字符串还剩几个 statement」是一个
    **语法层面**的事实，怎么写注释都改变不了它。
    ─────────────────────────────────────────────────────────
    """
    import ast
    import inspect
    import textwrap

    for name in ("freeze_amount", "settle_amount"):
        source = textwrap.dedent(inspect.getsource(getattr(JimengProvider, name)))
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.FunctionDef)
        statements = [
            stmt
            for i, stmt in enumerate(node.body)
            # 第 0 条如果是裸字符串，那是文档字符串，不是逻辑
            if not (i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ]
        assert len(statements) == 1 and isinstance(statements[0], ast.Return), (
            f"`JimengProvider.{name}` 里不止一句 return —— "
            f"计价算式只能在 `pricing.py` 里有一份：\n{source}"
        )
