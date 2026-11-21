"""测试用的 provider 替身。**不是测试文件**（pytest 不收集它）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个文件里为什么只有类，没有夹具】

夹具（`scripted` / `instant_scripted`）在 `tests/conftest.py` 里。
因为 pytest **只从 conftest 和已注册插件里收夹具** —— 定义在本文件里
的话，`from _providers import scripted` 只是把函数对象搬进用例的
命名空间，pytest 根本不知道它是个夹具，用例会报
「fixture 'scripted' not found」。而 `pytest_plugins = [...]` 写在
非顶层 conftest 里在 pytest 8 已经是硬错误。所以：替身在这儿，
夹具在 conftest。

【为什么不干脆让 `FakeProvider` 可配置】

因为 `FakeProvider` 是**契约的一部分**：前端那 138 条测试里
「冻结 32 / 结算 24 / 退回 8 / 余额 22」写死了，跨仓门禁打的
也是它。给一个契约装置加「想慢就慢、想错就错」的旋钮，
迟早会有人在生产配置里把它打开 —— 而那时它的行为就不再是契约了。

所以替身放在**测试这一侧**：它继承 `FakeProvider`（于是计价逐字
相同，这里不可能算出和契约不一样的数），只覆写「什么时候算完」
和「什么时候报错」这两件与契约无关的事。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from app.providers import GenerationRequest, ProviderFailure, ProviderResult
from app.providers.fake import FakeProvider


class ScriptedProvider(FakeProvider):
    """一个**由测试剧本控制**的 provider。

    它同时扮演两种真实形态：

      · `polls_before_done > 0` 时 = **即梦**：`submit` 只回一张
        带句柄的回执，要问几次才有结果。队列、排队位次、轮询循环
        这些 B3 的主角，只有在这种 provider 下才看得见。
      · `polls_before_done == 0` 时 = **当场就有结果但走了异步接口**
        的 provider（`poll` 第一次就返回成品）。

    【失败为什么是「属性 + 随时可改」而不是构造参数】
    因为一条测试里常常要「先成功一次，把队列撑起来，**再**让下一次
    提交失败」。写成构造参数的话，用例得提前知道整个剧本，
    而剧本里那些顺序正是它要断言的东西。
    """

    name = "scripted"

    def __init__(self, *, polls_before_done: int = 1) -> None:
        self.polls_before_done = polls_before_done
            # 前几次 poll 返回 None。0 = 第一次就问出结果。
        self.submit_failure: ProviderFailure | None = None
        self.poll_failure: ProviderFailure | None = None
        self.submit_count = 0
        self.poll_count = 0
        self.submitted: list[GenerationRequest] = []
            # 记下「到底提交了几次」。重试那条用例靠它断言
            # 「真的又提交了一次」，而不是只看最终状态 ——
            # 只看状态的话，一个**没有重试**但恰好被别的东西
            # 推进到成功的实现也能绿。
        self._pending: dict[str, ProviderResult] = {}
        self._polls: dict[str, int] = {}

    # ── 覆写的两个方法 ─────────────────────────────────────

    def submit(self, request: GenerationRequest) -> ProviderResult:
        self.submit_count += 1
        if self.submit_failure is not None:
            raise self.submit_failure

        self.submitted.append(request)
        final = super().submit(request)
            # 借 `FakeProvider` 算出成片时长 —— 计价与契约逐字一致。

        handle = f"scripted-{self.submit_count}"
        self._pending[handle] = final
        self._polls[handle] = 0
        return ProviderResult(
            output_duration_sec=0,
            provider_task_id=handle,
            provider_url=None,
            done=False,
        )

    def poll(self, provider_task_id: str) -> ProviderResult | None:
        self.poll_count += 1
        if self.poll_failure is not None:
            raise self.poll_failure

        self._polls[provider_task_id] = self._polls.get(provider_task_id, 0) + 1
        if self._polls[provider_task_id] <= self.polls_before_done:
            return None
        return self._pending.pop(provider_task_id, None)
