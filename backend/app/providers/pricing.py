"""计价算式（§7.1 / §7.2）—— **fake 与 jimeng 共用的那一份**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这段算术要单独一个文件，而不是各写在每个 provider 里】

§12.2 把 `freeze_amount` / `settle_amount` 定成了 Protocol 的两个方法，
所以每个实现都得有这两个名字。但**「要有这个方法」不等于「各写一份
算式」** —— 算式是契约的一部分（冻结 32 / 结算 24 / 退回 8 是前端
写死了的数字），而契约只能有一份。

两份的后果不是「其中一份错了」，而是**两份都还是绿的**：

  · `FakeProvider` 的算式变了 → 它自己的测试跟着变，全绿；
  · `JimengProvider` 的那一份没动 → 它自己的测试也全绿；
  · 于是跨仓门禁（打的是 fake）与真环境（跑的是 jimeng）
    开始**算不一样的钱**，而库里没有任何一处能看出分岔。

这正是 B2b / B3 已经吃过两次亏的形态（两个实现各自自洽、合起来不一致），
所以这里把算式抽出来，两边 `import` 同一段代码 —— 它们**不可能**分岔，
因为根本没有第二段。`test_pricing_b6.py` 另外钉着「两个 provider 调的是
这里」这件事，防的是哪天有人把算式又抄回去（那时这个文件会变成死代码，
而两边各自的测试照样绿）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from app.config import get_settings
from app.enums import TaskKind
from app.providers.base import GenerationRequest, ProviderResult


def freeze_amount(request: GenerationRequest) -> int:
    """下单时冻结多少（§7.2 ①②）。

    ```
    图：固定 credits_per_image
    视频：(输入时长 + 请求时长 + 余量) × 每秒单价
    ```

    ─────────────────────────────────────────────────────────
    【图为什么是固定值】文生图没有时长概念，成本固定，所以
    冻结额 = 结算额（前端 `credit_format.isFixed` 靠 `min == max`
    判断，显示成「本次冻结 4 积分」而不是「4~4 积分」）。

    【视频为什么要加余量】因为成片时长由 provider 侧的 Agent 自主
    决定，可能比请求的长。冻结要**保证扣得起**，所以按「请求时长 +
    `duration_slack_sec`」冻，多冻的部分事后退回。

    ⚠️ `duration_slack_sec` 的默认值 3 是**占位值**，真值要等
       §18-2 的即梦实测。改它必须前后端一起改（前端 `_durationSlackSec`）。
    ─────────────────────────────────────────────────────────
    """
    settings = get_settings()
    if request.kind is TaskKind.text_to_image:
        return settings.credits_per_image
    seconds = request.input_duration_sec + request.requested_duration_sec
    return settings.credits_per_sec_720 * (seconds + settings.duration_slack_sec)


def settle_amount(request: GenerationRequest, result: ProviderResult) -> int:
    """按**成片实际时长**该收多少（§7.2 ④）。

    【返回的是「本该收多少」，不是「实际扣多少」】两者在
    「实际时长 > 冻结上限」时会不一样，而那时由调用方钳到冻结额
    （§7.2 ④ 平台自担差额），不在这里做 —— 因为那是**计费策略**，
    不是 provider 的算术。

    【为什么按 `result.output_duration_sec` 而不是请求时长】
    因为用户付的是「拿到了多长的片子」。用请求时长结算的话，
    provider 多给的那一秒是我们自己吞掉的成本，而 §7.2 明说
    少补多退以**实际**时长为准。
    """
    settings = get_settings()
    if request.kind is TaskKind.text_to_image:
        return settings.credits_per_image
    seconds = request.input_duration_sec + result.output_duration_sec
    return settings.credits_per_sec_720 * seconds
