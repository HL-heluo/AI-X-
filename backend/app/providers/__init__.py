"""provider 抽象 —— §12.2 的两个 Protocol 之一。

【为什么要在「只有一个假实现」的时候就把接口定下来】
因为真正的成本差异就藏在这一层后面：`fake` 不花钱、`jimeng` 花钱。
把计价（`freeze_amount` / `settle_amount`）和调用（`submit` / `poll`）
一起收进 Protocol，`services/generation.py` 就永远不需要知道
现在连的是谁 —— 切真 provider 时**调用方一行不改**。

（另一个 Protocol 是 `Storage`，见 `services/storage.py`。）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【B7.x：`build_provider()` 为什么长出了 `kind` 这个形参】

上面那句「切真 provider 时调用方一行不改」在本批被**有意地**
破了一次，破的是这一处。原因是出现了**第一个**「图片和视频不是
同一个 provider」的部署形态：

    PROVIDER=fake / jimeng        → 文生图走它
    VIDEO_PROVIDER=minimax        → 其余（图生视频）走它

而 `worker.py` 的一个 tick **只造一个 provider**，然后在
`for kind in TaskKind` 里把它用在所有类型上 —— 所以「谁走哪条路」
这件事必须让 provider 的选择看得见 kind。

【为什么不写一个「按 kind 内部转发」的 RoutingProvider，让调用方
一行不改】因为 `poll(provider_task_id)` **拿不到 kind**。路由器要知道
「该问谁」，只能把答案编进**落库的** `tasks.provider_task_id`
（像即梦那样编 `req_key|id`）—— 而那是句柄格式变更，库里正在飞的
任务会读不出来。按 kind 造就不动句柄。

【改动面】2 个模块、6 个调用点，全部是机械地把**已经在作用域里**
的 kind 传下去。要点是：`kind` 在每一个调用点本来就有
（`generation.estimate_cost(kind, …)` 的形参、`for kind in TaskKind`
的循环变量、`task.kind`），所以这不是新增信息，是让已有的信息
走到它该到的地方。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from app.config import ProviderKind, get_settings
from app.enums import TaskKind
from app.providers.base import (
    GenerationProvider,
    GenerationRequest,
    ProviderCallMeta,
    ProviderFailure,
    ProviderResult,
)
from app.providers.fake import FakeProvider
from app.providers.jimeng import JimengProvider
from app.providers.minimax import MinimaxProvider


def _make(kind: ProviderKind) -> GenerationProvider:
    """把一个配置值变成实例。**只认配置，不认任务。**"""
    if kind is ProviderKind.jimeng:
        return JimengProvider()
    if kind is ProviderKind.minimax:
        return MinimaxProvider()
    return FakeProvider()


def build_provider(task_kind: TaskKind) -> GenerationProvider:
    """按配置**和任务类型**造 provider。

    【`jimeng` 为什么**不再**在这里抛】B6 之前这一支是
    `NotImplementedError`：那时「配置成真 provider 但代码还没写」必须在
    启动那一刻响亮地失败，而不是等某个用户点了生成才炸。

    现在代码写了，但那条纪律**没有丢** —— 它挪到了 `Settings` 的
    `model_post_init`：`PROVIDER=jimeng` 却缺 AK/SK、或缺 `req_key`
    时，进程连启动都起不来。所以这里不再判第二遍，也**不该**判 ——
    「配置对不对」属于配置那一层，两处都判的话，
    第二处的错误消息迟早会和第一处说的不一样。

    【`minimax` 那一支为什么没有「代码还没写」的位置了】它的配置守卫
    在同一个地方（`model_post_init` 判 `VIDEO_PROVIDER=minimax` 必须有
    密钥），外加一条**方向性**的守卫：`PROVIDER=minimax` 直接报错，
    因为 MiniMax 在本仓库只接了视频，拿它当图片 provider 等于配了
    一个不存在的实现。所以下面 `text_to_image` 那一支**不需要**再
    考虑 minimax。

    【路由一行就是全部】`text_to_image` 走 `provider`（图片那一档）；
    **其余一切**走 `resolved_video_provider`（`VIDEO_PROVIDER` 没设时
    它等于 `provider` —— 那是默认形态，也是 2026-10-16 之前唯一的形态，
    所以这次改动对既有部署是零行为变化）。

    ⚠️ **右边必须写 `settings.resolved_video_provider`，不许在这里自己
       写 `settings.video_provider or settings.provider`。**

       第一版就是那么写的，而它**被测试抓了出来**：那两处 `or` 看起来
       一模一样，但 `model_post_init` 判的是属性那一个。于是
       「守卫拿 A 判、运行时用 B」这种错位没有任何东西会报 ——
       而它的表现是「配置里写着 MiniMax，实际却按即梦跑了」。
       `resolved_video_provider` 的 docstring 里那句「必须是**一个属性**
       而不是各处写 `x or y`」说的就是这件事，而这个文件正好是它
       警告的那个地方。
    """
    settings = get_settings()
    if task_kind is TaskKind.text_to_image:
        return _make(settings.provider)
    return _make(settings.resolved_video_provider)


__all__ = [
    "FakeProvider",
    "GenerationProvider",
    "GenerationRequest",
    "JimengProvider",
    "MinimaxProvider",
    "ProviderCallMeta",
    "ProviderFailure",
    "ProviderResult",
    "build_provider",
]
