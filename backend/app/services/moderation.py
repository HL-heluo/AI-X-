"""内容审核 —— §10.2 的第①层（平台侧输入闸）与 provider 错误码的映射表。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个模块为什么有两件看起来不相干的事】

因为它们回答的是**同一个问题的两半**：「一句不合规的话，是在哪一步、
以什么身份被挡下来的？」

  · **第①层（`screen_input`）** 在**我们**这边：用户点了生成，
    我们在打给 provider 之前先拦一次。挡下来的身份是
    `AppError(CONTENT_REJECTED)` → HTTP 422。好处是**不花钱** ——
    这一刀砍在冻结之前，provider 那边根本不知道有人试过。
  · **第②层（`classify_provider_error`）** 在**它**那边：我们放了行，
    即梦的审核拦住了它，回一个 `50411` 之类的审计码。这时钱已经花出去了，
    要决定的是「这个任务该记成什么、要不要再试一次」。

两半必须住在一起，因为**它们的判据会漂**：我们这边放行的词，
在那边可能是拒的；反过来也一样。放在两个文件里的话，
「同一类内容在两处各有一套说法」这件事就没有一个看得见的位置。

【它是纯判断，不碰数据库、不碰网络】

所以没有事务、没有 `atomic()`、可以直接单元测试。
唯一的外部依赖是配置（词表开关）和 `AppError`。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from app.config import get_settings
from app.enums import ErrorCode
from app.errors import AppError
from app.providers.base import ProviderCallMeta, ProviderFailure

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 一、provider 错误码 → 我方处置
# ══════════════════════════════════════════════════════════════


class ProviderVerdict(NamedTuple):
    """一个 provider 审计码对**我们**意味着什么。

    【为什么是两个 bool，不是一个枚举】因为它们是**两个独立的维度**，
    见 `handle_failure` 里那段说明：`rejected` 说的是「任务该记成
    哪个终态」（用户看到的是「换个词试试」还是「我们坏了」），
    `retryable` 说的是「要不要再打一次」。审核失败恰好是
    「不可重试**且** rejected」—— 但那是巧合，不是定义。
    """

    rejected: bool
    retryable: bool


# ── 即梦审计码的映射表（§9 / §7.4 / §7.5）────────────────────
#
# ⚠️ 下面的码是**即梦文档里的审计码**（`即梦API接入.md` §9 那张表），
#    不是我们的 `ErrorCode`。它们只进 `tasks.error_code` 与
#    `provider_calls.resp_code`，**从不作为响应里的 code 出现**。
JIMENG_CODE_MAP: dict[str, ProviderVerdict] = {
    # ── 审核类：一律 rejected + 不可重试 ────────────────────
    #
    # 【为什么 50511（输出后审核）也在这一组里 —— 文档在此自相矛盾】
    #
    # §9 的那张表在「可重试」列里给 50511 打了勾，而 §7.4 / §7.5 与
    # 执行卡 C11 说的是「内容审核未通过 → 全额退回 + 任务记 rejected」。
    # 两处冲突，这里取**后者**，理由有两条：
    #
    #  1. 重试一次已经被判不合规的输出，就是**再付一次钱**去买同一个
    #     结果 —— 而「被拒的调用到底计不计费」这件事（§18-4）恰恰
    #     还没确认。在一个成本未知的分支上做重试，是在赌。
    #  2. 这条路径的**用户可感知行为**不因重试而改善：无论重试几次，
    #     用户拿到的东西都一样（一个 422 和一个退回的余额），
    #     只是迟了几十秒。
    #
    # ⚠️ 这是一条**有意的偏离**，用测试钉着（`test_50511...`）。
    #    真接上即梦、§18-4 有了答案之后要复审它。
    "50411": ProviderVerdict(rejected=True, retryable=False),  # 输入图审核未通过
    "50413": ProviderVerdict(rejected=True, retryable=False),  # 输入文本审核未通过
    "50514": ProviderVerdict(rejected=True, retryable=False),  # 输入音频审核未通过
    "50511": ProviderVerdict(rejected=True, retryable=False),  # 输出后审核未通过
    # ── 非审核类：等一下就好 ────────────────────────────────
    "50429": ProviderVerdict(rejected=False, retryable=True),  # QPS 限流
    #
    # 【50430 —— 2026-10-15 真网关实测补进来的一个码】
    #   原文：`{"code":50430,"message":"Request Has Reached API Concurrent
    #   Limit, Please Try Later"}`。它是**并发上限**（这个子账号的
    #   CV 并发是 1），与 50429（QPS 限流）不是同一个数 —— 文档那张表里
    #   只有前者的岗。补进来是为了让它**在对账表里可辨**：`resp_code`
    #   一旦出现 50430，读的人要知道那是并发撞车，不是参数错。
    #   处置与 50429 相同（等一下就好）—— 而未收录的码本来就默认
    #   可重试，所以这一条**不改变行为**，只让码有名字。
    "50430": ProviderVerdict(rejected=False, retryable=True),  # 并发上限
    "50500": ProviderVerdict(rejected=False, retryable=True),  # provider 内部错误
}


# ── MiniMax 的映射表（图生视频那一路）────────────────────────
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 【为什么是**第二张表**，而不是把 MiniMax 的码并进上面那张】
#
# 因为两张表的**键不是同一种东西**。即梦的 `50411` / `50429` 是它自己
# 信封里的 `code`；MiniMax 走的是 **OpenAI 风格的错误体 + 真实 HTTP
# 状态码**，它的内部码是**从 `error.message` 末尾的括号里抠出来的**
# （`... (1026)`），而且**同一类错误在不同端点的数字未必一样**。
#
# 合表的话，一个 `1004`（MiniMax 鉴权）和一个 `1004`（哪天即梦也用了）
# 会互相覆盖，而覆盖是静默的 —— 表现是「同一类错误在一周后变了处置」。
# 键的类型不同就该是两张表。
#
# 【那为什么还放在这个文件里】见下面 `failure_from_code` 的说明：
# 「哪个码算审核」是产品判断，两条通道必须用同一套判断标准。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MINIMAX_CODE_MAP: dict[str, ProviderVerdict] = {
    # ── 审核类：rejected + 绝不重试（§7.4）───────────────────
    #
    # 【为什么只有 1026 一个】它是文档里唯一**逐字给出来**的审核号：
    #   `"video description contains sensitive content (1026)"`，配 422。
    #   即梦那边「输出之后才判不合规」是 50511，MiniMax 大概率也有
    #   一个对应号 —— 但**我们没见过它**。
    #
    # ⚠️ **这里刻意不猜一个号填上。** 猜错的代价是不对称的：
    #   若猜的那个号其实表示「对方服务忙」，我们就会把一个瞬时故障
    #   判成 `rejected` —— 而 `rejected` 在界面上是**「内容违规」**，
    #   等于**平白指控用户发了违规内容**（`tasks.status=rejected` 还会
    #   让它不可重试、直接退款）。宁可让那个号走「未收录 = 可重试」，
    #   最多是白等三次；这个缺口记在 HANDOFF 里，真见着号了再补。
    "1026": ProviderVerdict(rejected=True, retryable=False),  # 输入涉及敏感内容
    #
    # ── 等一下就好 ─────────────────────────────────────────
    #
    # 【为什么只列 1002 一条，而它跟「未收录」的处置又一模一样】
    # 因为 `resp_code` 要能**读出名字**。500 / 529（过载）这两个档
    # 文档写明了会回，但我方没见过它们的内部号，所以它们靠**状态码
    # 那张表**兜底 —— 处置与这里相同，只是对账表里记的是状态码。
    # 一个「猜出来的号 + 处置与默认相同」的条目没有任何收益，
    # 只会让人以为那个号被确认过。
    "1002": ProviderVerdict(rejected=False, retryable=True),  # 限流
    # ── 重试没有意义的一类（**即梦那边没有对应码，本批新引入的判据**）──
    #
    # 【为什么 1004 / 1008 / 2013 必须显式列出来】因为「未收录 = 可重试」
    # 这条保守规则对它们是**错的**，而且错得花钱：
    #
    #   · 1004 鉴权失败：密钥不对，重试三次错三次，最后落在同一个
    #     「生成失败」上 —— 只是慢了 3 倍。响亮失败才有人去修密钥。
    #   · 1008 余额不足：我方账户没钱。重试不产生任何新信息，
    #     而每一次重试都是一次真实的 HTTP 往返。
    #   · 2013 参数错误：请求是**我们**拼的。重试等于把同一个 bug
    #     打三遍 —— 它不该被退避掩盖过去。
    #
    # 这一组是**本批唯一新引入的处置方向**：即梦那条链路上从来没有
    # 「一个非审核错误、却明确不可重试」的码。
    "1004": ProviderVerdict(rejected=False, retryable=False),  # 鉴权失败
    "1008": ProviderVerdict(rejected=False, retryable=False),  # 余额/额度不足
    "2013": ProviderVerdict(rejected=False, retryable=False),  # 参数错误
}

# 按**真实 HTTP 状态码**兜底。文档给的是 400/401/402/422/429/500/529 七档。
#
# 【为什么在码之外还要一张**按状态码**的表】因为内部码是从
# `error.message` 的括号里正则抠出来的 —— 那段文本的格式是**对方的文案
# 约定**，不是契约。哪天它改成正则认不出来的形状，`code` 就是 `None`，
# 而「401 不可重试」这条判断**不该跟着一起失效**：状态码本身
# 就是 MiniMax 明确写进文档的、稳定的东西。
#
# 【两份都在时谁优先】先查码表，查不到再查它。见 `_classify_minimax`。
MINIMAX_HTTP_STATUS_MAP: dict[int, ProviderVerdict] = {
    400: ProviderVerdict(rejected=False, retryable=False),  # 参数错误
    401: ProviderVerdict(rejected=False, retryable=False),  # 鉴权失败
    402: ProviderVerdict(rejected=False, retryable=False),  # 余额/额度不足
    422: ProviderVerdict(rejected=True, retryable=False),   # 输入涉及敏感内容
    429: ProviderVerdict(rejected=False, retryable=True),    # 限流
    500: ProviderVerdict(rejected=False, retryable=True),   # 服务端错误
    529: ProviderVerdict(rejected=False, retryable=True),   # 过载
}

_RETRY_BY_DEFAULT = ProviderVerdict(rejected=False, retryable=True)
"""未收录时的保守答案。见 `classify_provider_error`。"""


def _classify_minimax(code: str | None, http_status: int | None) -> ProviderVerdict:
    """MiniMax 的错误 → `(rejected, retryable)`。**先查码，再查状态码。**"""
    if code is not None and code in MINIMAX_CODE_MAP:
        return MINIMAX_CODE_MAP[code]
    if http_status is not None and http_status in MINIMAX_HTTP_STATUS_MAP:
        return MINIMAX_HTTP_STATUS_MAP[http_status]
    return _RETRY_BY_DEFAULT


def classify_provider_error(
    code: str | None,
    *,
    provider: str = "jimeng",
    http_status: int | None = None,
) -> ProviderVerdict:
    """provider 的错误码 → 我方的 `(rejected, retryable)`。

    【未收录的码为什么保守判「可重试」】同 `ProviderFailure.retryable`
    默认 True 的理由：多试三次的代价是几秒钟，而把一次「本来等一下就好」
    的限流直接判死、还退给用户一个「生成失败」，代价是用户白等一场
    外加一次客服。方向不对称，所以往安全那边倒。

    【为什么 `None` 也走这条路】`None` = provider 没给码（连不上、
    回了个畸形信封）。那同样是「不知道发生了什么」，同样该重试。

    【`provider` 与 `http_status` 都是带默认值的关键字参数】所以
    `jimeng.py` 的调用点与既有测试**一个字都不用改** —— 默认值
    就是它原来的行为。
    """
    if provider == "minimax":
        return _classify_minimax(code, http_status)
    if code is None:
        return _RETRY_BY_DEFAULT
    return JIMENG_CODE_MAP.get(code, _RETRY_BY_DEFAULT)


def failure_from_code(
    code: str | None,
    message: str,
    *,
    provider: str = "jimeng",
    http_status: int | None = None,
    meta: ProviderCallMeta | None = None,
) -> ProviderFailure:
    """按错误码造一个 `ProviderFailure`。**provider 适配层用它。**

    【为什么这个函数在这里，而不是在 `jimeng.py` 里】因为「哪个码算审核」
    是个**产品判断**（它决定退款和用户看到的文案），不是即梦的技术细节。
    放在适配层里的话，将来第二个 provider 接进来时会各写一份，
    而两份的分歧不会报错 —— 只会让同一类错误在两条通道上
    退给用户两个不同的东西。

    【`provider="minimax"` 是 B7.x 加的】上面那张 `JIMENG_CODE_MAP` 的
    注释写的时候还说「将来第二个 provider 接进来时会各写一份」是个
    **反例**；这次真接上第二个，走的就是这里 —— 两张表、一个判断入口。
    """
    verdict = classify_provider_error(code, provider=provider, http_status=http_status)
    return ProviderFailure(
        message,
        code=code or ErrorCode.PROVIDER_ERROR.value,
        retryable=verdict.retryable,
        rejected=verdict.rejected,
        meta=meta,
    )


# ══════════════════════════════════════════════════════════════
# 二、平台侧入口审核（§10.2 第①层）
# ══════════════════════════════════════════════════════════════

# ── 内置词表 ────────────────────────────────────────────────
#
# ⚠️⚠️ **这是一份占位词表，上线前必须换成运营那份。**
#    真实词库是运营资产（要按季度审、要能被投诉倒查），不适合放在
#    代码仓库里跟版本走 —— 它是**内容**，不是**逻辑**。
#    换它的正规途径是 `MODERATION_EXTRA_KEYWORDS`（逗号分隔），
#    或者把它改成从文件/接口加载。
#
# 【为什么仍然要有一份内置的】因为「默认配置」必须是一个**能拦住东西**
# 的配置。默认空表的话，一个照文档部署起来的环境在合规上等于没做审核，
# 而它从外表上看完全正常 —— 这类缺口要等到出事才被发现。
#
# 【为什么那几条写得这么泛】它们代表的是**类目**，不是某一句具体的
# 话。真正的词库当然要比这细得多；这里只要能让「词表接上了」
# 这件事本身可被测到、可被演示，就够了。
DEFAULT_BLOCKLIST: tuple[str, ...] = (
    "制作炸弹",
    "枪支买卖",
    "毒品交易",
    "拐卖人口",
    "儿童色情",
    # ── 哨兵词 ──────────────────────────────────────────────
    # 【它为什么在这里】给测试和跨仓门禁一个**确定性**的触发点。
    # 上面那些词是用来拦真东西的，而测试需要一个「一定不在正常
    # 提示词里、也一定不会被将来换词库删掉」的记号。
    # 纯 ASCII，因为前端的 live 门禁要在 Dart 源码里写死它 ——
    # 中文在那里会因为环境变量/命令行的编码往返而变成另一串字节
    # （本项目在 GBK 上已经踩过一次同源的坑）。
    "__BLOCKED__",
)

# 零宽字符。**它们存在的唯一目的就是绕过关键词匹配。**
# 一个词中间插一个 U+200B，人眼看着一模一样，而 `in` 判不出来。
#
# ⚠️ 用**转义序列**写，不要把这些字符直接打进源码：
#    它们是不可见的，而一个不可见的字符躺在字符串字面量里，
#    下一个读这段代码的人没有任何办法看出里面有几个、是哪几个。
#    改一次「看起来没变」的编辑就可能把它删掉，而测试不一定报错。
_ZERO_WIDTH_CODEPOINTS = (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)
_ZERO_WIDTH = "".join(chr(cp) for cp in _ZERO_WIDTH_CODEPOINTS)


def _normalize(text: str) -> str:
    """比对前的归一化：**统一大小写、去掉所有空白与零宽字符**。

    ─────────────────────────────────────────────────────────
    【为什么这三步一个都不能少】

    关键词匹配是**字符串**匹配，而人写的是**字**。这两者之间的每一种
    差异都是一条绕过路径：

      · `制毒` vs `制毒`（大小写）—— 英文词才有的问题，
        但 `__BLOCKED__` / `__blocked__` 就是靠这一步统一的。
      · `炸 弹`（插空格）、`炸\\n弹`（换行）—— 去掉全部空白。
      · `炸\\u200b弹`（零宽空格）—— 去掉零宽字符。

    ⚠️ **它挡不住的是同音字和变体字**（「炸弹」→「炸蛋」）。
       那是关键词方案的**固有上限**，不是这里漏了一步 ——
       真正的兜底是即梦那边的第②层审核。
       把这条写在注释里，是为了防止下一个人以为
       「再加一个 `replace` 就严密了」。
    ─────────────────────────────────────────────────────────
    """
    cleaned = text.translate(str.maketrans("", "", _ZERO_WIDTH))
    return "".join(cleaned.casefold().split())


def _blocklist() -> list[str]:
    """内置词表 ∪ 配置里加的（都已归一化，空串丢掉）。"""
    extra = get_settings().moderation_extra_keywords
    words = [*DEFAULT_BLOCKLIST, *extra.split(",")]
    return [normalized for w in words if (normalized := _normalize(w))]


def screen_input(text: str) -> None:
    """入口审核。命中就抛 `AppError(CONTENT_REJECTED)`（HTTP 422）。

    ─────────────────────────────────────────────────────────
    【调用点在 `generation.submit` 的哪一步：余额校验**之前**】

    这一步在任何写库动作之前，所以「被拒的提交一个数字都不动」
    是**构造上**成立的，不需要额外回滚。

    代价是一条顺序后果，要如实记着：**零余额 + 命中词的用户拿到 422，
    而不是 `INSUFFICIENT_CREDITS`。** 对用户是好事（他该知道的是
    「这句话不行」，而不是「你没钱了」—— 后者会让他去想办法充钱，
    而充了也发不出来），但它确实与 §12.1 里 Mock 的检查顺序不同，
    所以有测试专门钉着这个顺序。

    【为什么响应里不回显命中的那个词】
    回显等于给了一个**逐词试探词库**的接口：拿一串候选词挨个发一遍，
    看哪个返回 422，就能把词库枚举出来。词库里有什么，
    本身就是一次「怎么绕过它」的地图。
    命中项只写进服务端日志，排查时看得到。
    ─────────────────────────────────────────────────────────
    """
    if not get_settings().moderation_enabled:
        return

    haystack = _normalize(text or "")
    if not haystack:
        return

    for word in _blocklist():
        if word in haystack:
            # 【为什么要记 `word` 而响应里不给】见上面那段。
            # 日志只有我们看得见，而排查「我的提示词为什么被拒」
            # 全靠这一行。
            logger.info("入口审核拦下一次提交（命中词表项 %r）", word)
            raise AppError(
                ErrorCode.CONTENT_REJECTED,
                "提示词包含平台不允许的内容，请修改后重试",
            )


__all__ = [
    "DEFAULT_BLOCKLIST",
    "JIMENG_CODE_MAP",
    "MINIMAX_CODE_MAP",
    "MINIMAX_HTTP_STATUS_MAP",
    "ProviderVerdict",
    "classify_provider_error",
    "failure_from_code",
    "screen_input",
]
