# 交接说明 · AI 视频创作平台 Flutter App

> 写给**下一轮对话里的我**（也是给你看的项目快照）。
> 最后更新：2026-10-17，F10 之后（**默认连真后端**，见 §13）。
>
> **前端 v1 到这里做完了**：B0–B7 全部落地，`flutter analyze` 零告警、
> **141 个测试全绿**、`flutter build web` 通过，并且在**真实 Chrome** 上
> 从头到尾走过一遍（见 §9）。
>
> ⚠️ **默认值翻过一次（F10）**：`AppConfig.forApp()` 的 `useMock` 默认现在是
> **false**（真后端 @ 本机 8000）。**裸跑 `flutter run` / `flutter build web`
> 连的是真后端**；要全假数据得显式 `--dart-define=USE_MOCK=true`。
> 测试侧**没变**，仍然默认 Mock（那 24 条 live 用例靠它 skip）。
> 与旧文档冲突时以本节和 §13 为准。
>
> 【后端去哪了】2026-10-13 起后端在 `G:\AIVideo\backend\` **独立仓库**里做，
> 已经到 **B7**（12 个端点 + 真排队 + 合规对账 + 即梦适配层 + S3 存储 +
> §15.1 端到端验收，最新 tag `b7-acceptance`）。
> **后端「规格已定」的部分到此为止**：代码、契约测试、真进程验收都齐了，
> 只剩一件**必须由人来做**的事 —— 填 AK/SK、`req_key`、桶名，
> 然后照 `backend/HANDOFF.md` §2.6 那份清单走一遍。
> **要接后端或继续做后端，先读那份 `backend\HANDOFF.md`** ——
> 契约冻结决定与踩过的坑都在那里，本篇往后是前端的活手册。
>
> ⚠️ **B5 / B6 / B7 这三批后端侧一个字都没改响应形状**，所以前端 `lib/` 没动过，
> 需要动的只有 `test/live_contract_test.dart`（覆盖台账 + 两条新触发）。
> B7 更是**只加了一个测试文件**，跨仓 live 的 24 条逐条照样绿（当场重跑过），
> 覆盖台账仍是 43 条。
> B6 带来一个**部署前提**：`PROVIDER=jimeng` / `STORAGE=oss` 真跑起来之前，
> 有一份四步验收清单要人照着走（`backend/HANDOFF.md` §2.6）。
>
> 【F8 是什么】不是 B 系列的一个新批次，是**动一个契约值**：注册赠送 20 → 50。
> 它改了 5 个测试文件、1 个 Mock 常量、2 处文档，并把「积分不足」这条路径的
> 覆盖**重建**了一遍。理由与代价全在 §3.1，不要跳过那节。
>
> **要看「这一轮都干了什么」，读 `交付说明.md`**（同目录）——
> 那是给人看的验收文档，本篇是给下一个我干的活手册。

---

## 0. 一句话状态

地基（契约、数据层、Mock、登录态）+ 全部页面 + 接线/轮询/通知 + 收口
全部就位。**唯一没被验证过的代码是 `DioApiClient`** —— 它没有对手可以打。

**B2b（2026-10-13）把这件事做掉了**：后端 12 个端点已实现，前端的
`DioApiClient` **真的连上过一次**，第二层契约门禁打真后端 43 条全绿
（本节 §3、§5 讲的「一次都没跑过」已经过期，保留改写后的版本当记录）。
**代码全在 `test/` 下，`lib/` 一个字符没碰。**

**B6（2026-10-14）之后是 43 条**（B2b 时是 41）：`live_contract_test.dart`
从 22 条长到 **24** 条 —— 后端 B5 给 fake 与词表各加了一个 ASCII 哨兵词，
于是「提示词命中审核 → 422 且余额一分不动」和「provider 硬失败 → 502 且
余额一分没少」**第一次真的被走过**，它们从「不可达」那张表挪进了覆盖台账。
那条台账现在只剩 `queueSaturated` 一个人，而且它是**唯一一条不会因为
「接了真 provider」或「B7 做完」而变得可触发的** —— 上一版写的「等 B7 就行」
是个会自己过期的假承诺。

**F8（2026-10-13）已把「新用户买不起任何一条视频」这条拍板做掉了**：
注册赠送 20 → 50（§3.1）。那不是修好了，是**把撞墙的位置从「第一次」挪到了
「第二次」** —— 真正解决它要靠 v3 的充值。§3.1 有完整的代价清单。

**2026-10-16：App 第一次跑在「真即梦 + 真桶」上，而且成果真的出现在界面里**
（注册的新号走完文生图 → 首页余额 50→46 → 作品页看得见那张图、AI 角标在）。
顺手把「从 VSCode 按 F5 起真后端」这条路的配置与坑记下来了 —— **§11**。
⚠️ 图生视频**没成**，而原因是**后端账号侧**的一件事（那个产品的并发配额是 0），
**不是 App 的 bug**：凡是看到「生成失败，请重试」，先去后端 HANDOFF
§2.6 的「第四件事」对照错误码，别先改这里。

---

## 1. 下一轮怎么开始

**如果目标是「接真后端」或「继续做后端」**：

```
读 G:\AIVideo\backend\HANDOFF.md，继续做后端。先看 §3（已冻结的契约决定）
和 §4（B2b / B3 的完成记录）；§0 是三十秒版。
```

本篇 §3 和 §5 讲的是**前端侧**要动的地方（`DioApiClient` 与第二层契约门禁
怎么跑）；后端侧的对应内容在 `backend\HANDOFF.md`。

**如果目标是「继续做前端」**（v2 的编辑/模板/分享之类）：先读 §4 铁律，
再把 `交付说明.md` 里「已经拍板过的事」过一遍，别把结论推翻重来。

完整计划在 `C:\Users\Administrator\.claude\plans\nifty-dreaming-puffin.md`
（B0–B7 每一批的条目、风险、文档矛盾清单都在里面）。
需求原文在 `G:\AIVideo\工程文档.md`（v1.0，2026-10-12）。

> ⚠️ 计划文件是**当时**的样子，B5 之后实际做法有几处和它不同
> （最明显的是 `works_polling`，以及「验收脚本要先发积分」那件 ——
> 后者在 F8 之后彻底不需要了，见 §3.1）。以本文件为准。

---

## 2. 进度

| 批次 | 内容 | tag | commit |
|---|---|---|---|
| B0 | 依赖闸门 + git init | `b1-visual-delegacy`（与 B1 合并） | `f8b6351` |
| B1 | 视觉去旧：4 Tab→3 Tab、删课程/接单、两模式、真输入框 | `b1-visual-delegacy` | `f8b6351` |
| — | 删除已裁决作废的旧业务页面 | — | `e5ecd15` |
| B2 | 契约冻结：模型 + 三个常量唯一出处 + 计费文案 | `b2-contract-freeze` | `576806f` |
| B3 | 数据层：`ApiClient` 接缝 + 极简 Mock + 6 个 repository + DI 根 | `b3-data-layer` | `0d5bb80` |
| B4 | 路由 + 登录态分发 + 登录页 | `b4-auth-routing` | `413c7f8` |
| B5a | 我的 + 积分 + 设置（数据通路跑通） | `b5-ui-screens` | `3ce6b4a` |
| B5b | 作品 + 任务详情 + 生成/结果四页 | `b5-ui-screens` | `ce677f0` |
| B6 | 数据接线 + 轮询 + 通知（首页真正接上服务端） | `b6-wiring-polling` | `3e5f76f` |
| B7 | 收口：主线端到端测试 + 守卫 + 产品名统一 | `b7-hardening` | `192e584` |
| B7′ | 浏览器验收发现的**文案假承诺**修掉 | `b7-hardening` | `6b3eb61` |
| F8 | **契约值**：注册赠送 20 → 50，并重建「积分不足」覆盖 + 补 `INVITE_INVALID` | `b8-signup-grant` | 见 §3.1 |
| B2b | **跨仓契约门禁**：`DioApiClient` 第一次真跑（后端 12 端点已实现） | `b2b-live-gate` | 见 §5 |
| F9 | **上传件被打「AI 生成」标**：标识改成跟着 `asset.isAiGenerated` 走 | `f9-badge-per-asset` | 见 §12 |
| F10 | **默认连真后端**：`useMock` 默认 true → false（Mock 改成必须显式说） | `f10-real-by-default` | 见 §13 |

B5 的两半合打一个 tag（`b5-ui-screens`），理由：B5a 结束时 works 还没上，
单独打一个 tag 会让人以为「页面都齐了」。**打 tag 的语义是「这批能回滚到」。**

### 已验证 / 未验证

* ✅ `flutter analyze` 零告警；`flutter test` **141 全绿 / 24 skip**；`flutter build web` 通过。
* ✅ **`DioApiClient` 已在真后端上跑过**（B2b，2026-10-13）：第二层门禁 43 条全绿，
  §15.1 那笔账（余额 22）跨两仓逐字对上。见 §5。
* ✅ **B1 视觉验收已由用户确认通过**。
* ✅ **B4 的功能路径在真实 Chrome 上跑过**（无头 Chrome + CDP 驱动，不是肉眼，见 §6）。
* ✅ **B5/B6/B7 的功能路径同样在真实 Chrome 上从头走了一遍**（注册 → 出图 →
  做成视频 → 积分不足 → 积分页 → 作品页 → 我的 → 登出 → 重新登录 → 刷新掉登录态），
  逐帧截图留证，见 §9。
* ✅ 三条**「故意改坏就会红」**验证过的守卫测试：换账号串号、图形化登录态 key、
  Mock 幂等表（详见 §10）。
* ⏳ **唯一还没做的验收是「人眼看视觉」**：登录/我的/积分/设置四屏，
  以及 B5b 那几张新屏的观感。截图已经在 `G:\AIVideo\_acceptance\` 里，可以直接翻。
* ❌ `flutter build apk --debug` 失败，**与代码无关**，需要你动一下手（见 §7）。

### 现有测试（11 个测试文件 + 2 个公共件）

默认 `flutter test`：**139 条全绿 + 24 条可见 skip**（那 24 条是打真后端的，
默认不该跑 —— 静默通过比没有门禁更危险，所以用 skip 让它们**看得见**）。
打真后端时那 24 条会真的跑，加上 `repository_layer_test` 的 19 条，**共 43 条**。

| 文件 | 守什么 |
|---|---|
| `test/models_test.dart`（45 个） | 模型解析、`available = balance − frozen` 现算、术语守卫、**错误码集合守卫** |
| `test/fake_api_client_test.dart`（27 个） | Mock 这个「假服务端」讲不讲道理：记账、配额、幂等表、流水排序 |
| `test/repository_layer_test.dart`（19 个） | **provider → Remote\*Repository → ApiClient 整条缝**，跑的就是接真后端那天的路径 |
| `test/auth_flow_test.dart`（13 个） | 冷启动分发、注册/登录/登出、错误文案不撒谎、**注册↔登录一来一回**、邀请码无效不说「连不上服务器」 |
| `test/works_polling_test.dart`（11 个） | 轮询退避（5s→15s）、心跳起停（含「登出后自己停」）、作品页两种空态 |
| `test/me_credits_test.dart`（10 个） | 我的/积分/设置：数据通、不串号、无充值入口、分页、失败重试 |
| `test/copy_guards_test.dart`（5 个） | 术语守卫 + **v1 范围守卫**（`lib/` 里不许出现「充值/支付/购买」） |
| `test/create_page_test.dart`（4 个） | 首页：3 Tab、默认创作页、无电商残留、真机尺寸下不溢出 |
| `test/generation_flow_test.dart`（4 个） | **主线端到端**：一句话→图→视频；作品页收得到货；积分不足的解释与出路；**F9 新增**「AI 产物带标、上传件不带标」 |
| `test/widget_test.dart`（1 个） | `AppShell` 冒烟 |
| `test/live_contract_test.dart`（24 个） | **B2b 新增**：跨仓契约门禁 —— 路径漂移、响应形状、错误码不撒谎、覆盖台账。**默认 skip**，只在打真后端时跑（B5/B6 各加了一条真触发） |
| `test/shell_harness.dart` | **不是测试，是公共件**：把 `AppShell` 当已登录渲染（真注册一次）、`unmountAndDrain` |
| `test/live_backend.dart` | **不是测试，是公共件**：按 `--dart-define` 分叉的容器工厂、`/__test/reset` 接线、发积分 |

---

## 3. 接真后端 —— **已接上，这是当时的清单（现在是回归清单）**

**「理论上只改一个 `if` 分支」这句话已经兑现**：B2b 让 `apiClientProvider`
走了一次 `DioApiClient` 那支，全程没改调用方一个字符。

下面这份顺序留着，因为接下去几批（后端 B7 端到端验收，以及要人填凭据的
真即梦 + 真桶）每动一次后端，就该按它回归一遍。**B5（审核 / 隐式标识 /
`provider_calls` 对账）与 B6（即梦适配层 / `S3Storage`）都已经过完了，
`lib/` 一个字没碰** —— 两批都只在后端内部加了执法动作与真外部适配层，
没改任何响应形状。

**B7 / B7.3 以及 2026-10-16 那一轮真跑也过完了**：真即梦 + 真 TOS 桶，
文生图**从本 App 的界面**整条跑通（作品页看得见那张图），图生视频卡在**账号侧**
的产品并发配额（不是 App、也不是后端代码的问题）。`lib/` 仍然一个字没碰。
见 **§11**。

1. **核 `lib/core/network/dio_api_client.dart` 的 `_decode` / `_toException`**
   两个方法。整个 App 对响应体形状的假设（**无信封**、错误码在 `code` 字段）
   就集中在那里。**B2b 已经把这两个方法在真后端上跑通了**（24 条形状/错误码
   断言），所以这一步现在不是「第一次核」，而是「别把它改坏」——
   `live_contract_test.dart` 会盯着。别改调用方。
2. 改 `lib/providers/app_providers.dart` 里 `apiClientProvider` 的分支。
   **F10 之后这一步已经是默认状态了**：裸跑就是真后端（本机 8000），
   不用给任何 `--dart-define`；要 Mock 才显式 `--dart-define=USE_MOCK=true`。
   换远端后端给 `--dart-define=API_BASE_URL=https://...`。
3. 先在**保留 Mock 的 latency 模式**下比一比：`--dart-define=MOCK_LATENCY_MS=4000`
   会让 Mock 走真实状态机（`queued → submitted → succeeded`），
   这是唯一能在本地看到「进行中」的办法。
4. 真后端上重跑一遍 §9 的剧本（脚本在 `G:\AIVideo\_acceptance\`，
   坐标要按新界面重算，但流程和断言点可以直接照抄）。
5. §5 那张契约缺口表里，**标 ✅ 已闭的不用再对齐了**（后端已按前端冻结的
   方式实现，且 B2b 门禁锁着）。仍然开放的只有第 5、11、12 条，
   各挂着「等 B0.5 的 Spike」「等数据量上来」「等要不要接推送」。

### 3.1 ✅ 已拍板：注册赠送 20 → 50（2026-10-13，F8）

**这条已经裁决，闭掉了。**

原来那节写的是「新用户买不起任何一条视频，请选 A/B/C」。你选了 **A**，
赠送额从 **20 提到 50**，并且改的是**契约值**（前后端一起改，已写进 §12.1）。

#### 改了什么，没改什么

| | 前 | 后 |
|---|---|---|
| 注册赠送 | 20 | **50** |
| 一图（4）+ 一视频（冻结 32） | 36 > 20，**第一次就撞墙** | 36 ≤ 50，**跑得通** |
| 一图 + 一视频结算后余额 | — | 50 − 4 − 24 = **22** |
| 第二次做视频（再冻 32） | — | 22 < 32，**仍然撞墙** |

**⚠️ 那条死路没有被解决，只是从「第一次」退到了「第二次」。**

这一点必须写清楚，因为很容易被读成「问题没了」：

* 用户现在能完整跑通一轮主线（注册 → 出图 → 转视频 → 播放）——
  这是从 20 提到 50 换来的**真实收益**，也是选 A 的主要理由。
* 但他第二轮做视频时依然会撞上同一堵墙，而 v1 **仍然没有充值入口**（§7.6）。
* 真正解决它的是 **v3 的充值**。F8 没有、也不能解决这件事。

所以 §9.4 那条「假承诺」的修复**必须原样保留**：余额不足时仍然要说清
差多少、为什么冻结比看到的多、并给一个「去看积分」的出口。
F8 做的是**把撞墙的位置往后挪**，不是**把墙拆了**。

#### F8 具体做了什么

| 文件 | 改动 |
|---|---|
| `lib/data/mock/fake_api_client.dart` | `_signupGrant` 20 → 50（类注释里写了为什么，以及那条死路挪到哪去了） |
| `工程文档.md` §12.1 / §15.1 | 注册行改成赠 50；剧本第 2 步「管理员脚本发 50 积分」**删掉**（注册即 50，那一步变多余） |
| `test/*`（5 个文件） | 所有以 20 为基准的账目断言跟着走；`grantMore` 垫款统一减 30，**让 120 − 32 这类算式原样成立** |
| `test/shell_harness.dart` | 删掉 `fundLikeAcceptanceScript`（不再需要演「管理员发积分」） |
| `lib/core/constants/error_codes.dart` | 追加 `INVITE_INVALID`（见 §3.2） |

#### 「积分不足」这条路径的覆盖是**重建**的，不是删掉

这是 F8 最容易做错的一步。原来那条覆盖靠的是「注册送 20 < 冻结 32」这个
**数值关系**，赠送额一改，关系就没了 —— 如果把断言里的数字直接改掉，
`generation_flow_test.dart` 里那条用例就会变成**永远通过**的空壳，
而 B7′ 花了半批功夫修好的「假承诺」也就重新失去了守卫。

改成走**更长的那一档**：10 秒视频冻结 `(10 + 3) × 4 = 52 > 50`。
死路还在，只是退后了一步 —— **这条用例守的从来不是那个数字，
是「余额不足这条路径的界面还在、还说人话」**，所以它必须跟着定价现实走。

现在这条路径有三处守卫，都在跑：

| 测试 | 守的 |
|---|---|
| `fake_api_client_test.dart`「余额不足抛 INSUFFICIENT_CREDITS，且不留下任何痕迹」 | 被拒后余额/冻结/任务/流水**一个都不能动** |
| `repository_layer_test.dart`「积分不足时抛的是 INSUFFICIENT_CREDITS，UI 才能分支」 | 整条缝上传出来的确实是这个码 |
| `generation_flow_test.dart`「新用户选 10 秒视频」 | 界面说人话 + 给出路 + **这一屏不许出现「充值」** |

> 我**没有**为了让演示好看去改 `_signupGrant` —— 这次是你拍的板，
> 而且是**改契约值**（前后端一起改），不是偷偷绕过校验塞积分。
> 前者是决策，后者才是把死路藏起来。

### 3.2 顺手可以在下一批做掉的小事

* 作品页**没有分页**（`/tasks?status=` 不带 `page`，见 §5 第 11 条）。
  作品多了会全量拉，现在数据少看不出来。
* 通知是**App 侧轮询到终态时本地发的**（`lib/core/notifications/`）。
  真后端若接推送，`TaskNotifier` 这个接缝就是替换点 —— 别在页面里直接调
  `flutter_local_notifications`。
* `1080P` 目前被 feature flag 藏起来（§5 第 8 条）。
* **`INVITE_INVALID` 已经加进前端了**（F8 顺手做的，`error_codes.dart`）。
  原因：§6.1 说注册必须带邀请码，那么「邀请码不对」就是注册路上必然会遇到的失败，
  而 §12.3 的码表里没有它 —— 后端一发这个码，前端就认不出，
  注册页会说那句撒谎的**「连不上服务器，检查一下网络再试」**。
  这和 B7′ 修的「请先充值」是同一类：把用户支去解决一个不存在的问题。

  **后端要照着发**：`400 INVITE_INVALID`。
  §12.3 的表还差 `UNAUTHORIZED` / `USERNAME_TAKEN` / `INVALID_CREDENTIALS` / `NOT_FOUND`，
  但这四个**前端已经能用 HTTP 状态码正确分支**（登录页看 401/409，`isUnauthorized` 看 401），
  不补也不会说错话 —— 所以留给 B2 真后端开始发这些码时一起补，那时能拿真请求验，不用凭猜。
  详见 §5 第 4 条。

---

## 4. 铁律（违反任何一条都是事故）

### 安全 / 法律

* **AK/SK 绝不能进前端或 git**。只能在后端环境变量 / 密钥管理器里。开发与生产用不同密钥。
* **AI 生成内容的标识是双向的**（《人工智能生成合成内容标识办法》，2025-09-01 生效）
  —— **法律义务，不是可选项**。两个方向都会出事，而且**方向相反**：
  1. **AI 产物必须有可见的「AI 生成」标识** —— 漏标即违规。组件在
     `widgets/ai_generated_badge.dart`（`AiGeneratedFrame`），
     叠加在 `image_result` / `video_result` / 作品缩略图上。
  2. **用户自己上传的原图不能被标成 AI** —— `assets.is_ai_generated = false`
     （参考图就是这一类）。把人的图标成 AI 同样在这部办法的射程里，
     而且是更难解释的那一侧。**F9 之前这一条是坏的**（恒打标），见 §12。

  【判据只看一件事】**这一格会不会同时出现两种来源。** 结果页（一个任务的产物）
  恒定是 AI，`AiGeneratedFrame.show` 默认 `true` 就是对的；
  而**资产列表是混装点**（作品网格、首页「最近作品」、参考图选择器），
  那里必须跟着资产走 —— `WorkThumbnail.showBadge` 传 `null`（默认）时
  就取 `asset.isAiGenerated`。缺字段时 `Asset.fromJson` 的默认值是 `true`，
  所以**解析不出来时落在「打标」那一侧**，安全方向没变。
  隐式标识（文件元数据）是**后端职责**，App 不碰。
* **v1 没有充值/支付**（§7.6 的充值档位标注「此处为 v3 预留」）。
  `test/copy_guards_test.dart` 有一条守卫扫描 `lib/`，出现「充值/支付/购买」就红。

### 架构

* **绝不要把任务状态存进 App 内存**（§8.4 硬规则）。代码红线：任何 `State` 里
  出现 `Task` / `List<Task>` 字段即违规。`IndexedStack` 只保留 widget 树和滚动位置，
  **不保鲜状态**。
* **provider 产物 URL 绝不能当资产真相**（1 小时过期）——模型中**没有** `provider_url` 字段，
  且在 `Asset` 上被结构性地杜绝。
* **`lib/theme/app_theme.dart` 不得修改**（设计系统冻结 §3.3.1）。同样不得改：
  `app_background.dart`、`glass_card.dart`、`section_title.dart`、`placeholder_body.dart`。
  状态色**复用既有 token**：`sage`=成功/进行中、`amber`=排队中、`danger`=失败。**不新增色值。**
* **绝不在生成按钮下显示确定性的积分数字**（§13.4）。无数据时显示 `计算中…`。
* **页面只 `ref.watch(xxxRepositoryProvider)`**，永远不 new Repository、不直接调 `ApiClient`。
  **接真后端那天的改动量应该只有 `app_providers.dart` 里 `apiClientProvider` 的一个 if 分支** ——
  如果发现要改页面，说明某处绕过了 DI，回头修抽象而不是加特例。

### 术语（§2，代码标识符层面）

用 `credit`（**不是** 算力/点数）、`task`（**不是** order/job）、
`freeze`/`settle`/`refund`、`image_to_video`/`text_to_video`、`asset`（**不是** 素材/产物）、
`balance`/`frozen`/`available`，且 `available = balance − frozen`（**永远现算，绝不存储**）。

> **例外**：`INSUFFICIENT_CREDITS`、`/credits/ledger` 这类 **wire 字符串必须逐字照抄契约**，
> 不受术语约束。已有一个守卫测试扫描 `lib/` 的非注释代码行，禁止
> `算力/点数/订单/素材/产物` 字面量。

---

## 5. 契约缺口

标注 **✅ 已闭**的几条，后端 B2 都按前端冻结的处理方式实现了，**有 B2b 的
真后端门禁钉着**（改坏会红）。不要再把它们当成待确认的事重新纠结一遍。

| # | 问题 | 本项目当前的处理 |
|---|---|---|
| 1 | ✅ 已闭 · **§12.3 没有定义 401**，但 App 必然遇到（JWT 过期） | 前端有 `AppException.unauthorized()` + `isUnauthorized`；**后端补了 `UNAUTHORIZED` / `INVALID_CREDENTIALS`**。401 一律走登录态信号，两边对得上（B2b 实测） |
| 2 | ✅ 已闭 · **§12.1 自相矛盾**：`/uploads/image` 说「返回公网 URL」，`/generation/video` 要的却是 `source_asset_id` | 后端**两个都返回**（`asset_id` + `public_url`），与 Mock 一致；`RemoteAssetRepository.uploadImage` 取 `asset_id` |
| 3 | ✅ 已闭 · **`/generation/cost` 没有约定 query 参数**（§12.1 只给了返回 `{min,max,freeze}`） | 前端冻结的 `GET /generation/cost?kind=&duration=&ratio=` **被后端采纳**，按它实现了 |
| 4 | ✅ 已闭 · **没有「用户名已存在」「密码错误」「邀请码无效」错误码** | 后端发 `USERNAME_TAKEN`(409) / `INVALID_CREDENTIALS`(401) / `INVITE_INVALID`(400)。前两个前端**按 HTTP 状态码**分支（正确，且不撒谎）；`INVITE_INVALID` 前端在 F8 补过枚举，认得出 |
| 5 | ⏳ **仍然开放** · 视频 freeze 预留 **3 秒余量**（`_durationSlackSec`）是占位值 | 前后端现在**两侧都是 3**（后端 `duration_slack_sec`），契约一致、门禁锁着；真值要等 B0.5 的即梦 Spike，届时两仓一起改 |
| 6 | ✅ 已闭 · **流水 `amount` 的方向约定缺失** | 按「**恒为正、方向由 kind 推导**」实现，后端逐字照做（只有 `settle` 减总余额） |
| 7 | ✅ 已闭 · `TaskKind` 的 `ratio` 字段：图片接口用 `aspect_ratio`、视频接口用 `ratio` | 后端**逐字照抄**（同一份契约里两个字段名就是不一样，不许改整齐），对内归一成 `TaskParams.ratio` |
| 8 | **v1 视频清晰度未定**：§14.1 说先上 720P，§7.1 却给了 1080P 定价 | 视频生成页**先只放 720P**，1080P 用 feature flag 隐藏 |
| 9 | §2 说状态有「**7** 个」，§11.3 实际列了 **8** 个 | 以 **8 个**为准，`task_status.dart` 注释标注了文档笔误 |
| 10 | 产品名未定（§18-5） | `core/constants/app_info.dart` 占位（中性描述「AI 视频创作」）。**四处已统一到它**（Dart/`index.html`/`manifest.json`/`android:label`），`isPlaceholderName` 留着钩子；`applicationId` 暂不改，等定名后单独一批 |
| 11 | **`/tasks` 没有分页契约**，而「作品」会越攒越多 | 冻结为 `GET /tasks?status=`（**不带** `page`），照契约实现并在 `remote_task_repository.dart` 注明「它只是恰好把数组放在 `items` 里，不是分页接口」。数据量上来前需后端补 |
| 12 | **通知没有契约**（§11 只说「任务完成要能通知」） | v1 由 App **轮询到终态时本地发**（`core/notifications/`）。若后端要接推送，换掉 `TaskNotifier` 这个接缝即可 |

### `DioApiClient` —— 跑过了（B2b，2026-10-13）

> 这一节原先写的是「**一次都没跑过**，后端不存在，它没有对手可以打」。
> 现在后端有了，它也跑过了。留着改写后的版本，是因为**第一次跑就撞出来的
> 那几件事比结论本身有用**。

`_decode` / `_toException` 那两个假设（**无信封**、错误码在顶层 `code`）
**两条都是对的** —— 后端 125 条测试从它那侧钉住，B2b 让前端亲身走了一遍。

命令（`--concurrency=1` 不能少，理由见后端 `HANDOFF.md` §4）：

```bash
# 后端
cd /g/AIVideo/backend
TEST_MODE=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 前端
cd /g/AIVideo/flutter_application_1
flutter test --concurrency=1 \
             --dart-define=USE_MOCK=false \
             --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

#### 打真后端时暴露出来的一件事（**只有真后端能暴露**）

登录态是 `AuthController._adopt` 装的：**先落盘、再写内存副本**
（`authTokenProvider`，dio 的拦截器同步读它）。

测试如果直接调 `authRepositoryProvider.register(...)`，就**跳过了这一步** ——
容器里没有任何人把 token 装进 `authTokenProvider`，于是后续每个请求都是
**裸奔**的，真后端一律回 401。

**Mock 模式永远暴露不出来**：`FakeApiClient` 是内存假服务端，有自己的一套
登录状态，**根本不看 `Authorization` 头**。

所以 `test/live_backend.dart` 里的 `registeredContainer()` 走的是
`authControllerProvider.notifier.register` —— 也就是**登录页按下按钮走的那条路**。
不要在这里手抄一遍 `_adopt`：抄的话它将来多一句（比如写个时间戳）夹具就悄悄
过时了，而门禁会继续绿。

---

## 6. B4 的浏览器走查（**已在真实 Chrome 上跑过**，2026-10-12）

不是靠肉眼：`flutter build web` → 本地静态服务 → **无头 Chrome**，
用 CDP 发真实鼠标/键盘事件驱动，逐帧截图取证据。

| 验收项 | 结果 | 证据 |
|---|---|---|
| 冷启动落**登录页** | ✅ | 截图里是品牌名 + 登录/注册切换 + 用户名/密码 +「演示模式…」提示；**不是**白屏、也不是 AppShell |
| 注册（邀请码 `MOCK`）→ 进 **AppShell** | ✅ | 填 `MOCK` / `alice` / `pw123456` 提交后落到「开始创作」页，底部 3 Tab 正常 |
| token **真的写进了浏览器** | ✅ | 注册后 `localStorage` 里出现 `FlutterSecureStorage.aivideo.auth_token`（AES-GCM 密文）|
| token **真的读得回来** | ✅ | 刷新后那条 entry **没了** —— 说明 `read()` 解密成功、`GET /me` 被 Mock 判 401、`_forget()` 把它清掉了 |
| 坏 token **不白屏** | ✅ | 刷新后干净地回到登录页，没有落在启动失败页 |
| **重启仍保持登录** | ⚠️ 用当前 Mock 演示不出来 | 见下 |

> ⚠️ **「重启仍保持登录」在浏览器里演不出来，原因在 Mock，不在 B4。**
> `FakeApiClient` 把「发出去的 token → 是哪个用户」存在**实例内存**里
> （`_userIdByToken`）。刷新页面 = 整个 Dart 进程重启 = Mock 忘了自己发过这个
> token → `GET /me` 判 401 → App **正确地**登出。
> 这正是 §8 那句「数据存在本机内存」在登录态上的必然结果，也和登录页上
> **「演示模式：数据存在本机内存」**那句承诺一致 —— 两者没有矛盾。
>
> 拆开看两半：**「写入 / 读回 / 解密」这一半在真实 Web 上已验过**（上表前四行）；
> **「恢复会话」那一半由 `test/auth_flow_test.dart` 的「token 有效 → 直接进主界面」
> 覆盖** —— 那里刻意让同一个 `FakeApiClient` 跨两次容器存活，模拟的正是
> 「服务端活着、App 重启」。接真后端后这两半会合成同一条路。
>
> 【若一定要让浏览器里也能演示】把 `_userIdByToken` 落进 `localStorage` 即可；
> 但那会改掉「Mock 数据存内存」这个定位（并让登录页那句提示变得不准确），
> 要不要做由你定，**不要顺手改**。

> ⚠️ Web 上 `flutter_secure_storage` 走 WebCrypto，**只在安全上下文可用**
> （https 或 localhost）。`flutter run -d chrome` 是 localhost，没问题；
> 但挂到 http 内网地址演示会**抛异常**。那种场景就在 `app_providers` 里
> 换成 `InMemoryTokenStore`（代价：刷新页面要重新登录）。

---

## 7. 已知问题：`flutter build apk --debug` 失败（**不是我们的代码**）

```
:video_player_android:compileDebugKotlin
  Could not close incremental caches ... cacheable/caches-jvm/jvm/kotlin
Caused by: FilePageCache.registerPagedFileStorage   ← 断言失败
```

Kotlin 编译器守护进程关不掉内存映射的 `.tab` 文件（Windows 文件锁）。
它打在该项目**第一个**被编译的 Kotlin 插件上，所以与 `video_player` 本身无关。
**B7 结束时又复现过一次，症状一字不差** —— 这一批没有碰过任何 Android 构建脚本。

**已试过、均无效**（诊断性改动全部已还原，`android/gradle.properties` 与原始状态一致）：
清 `build/`、`./gradlew --stop`、`kotlin.incremental=false`、
`kotlin.compiler.execution.strategy=in-process`。

**还没做的两步（需要你来定）**：

1. 杀掉两个残留 `java.exe`（Gradle 守护进程 + Kotlin 守护进程）。
   **只有你能做** —— 按名字全杀会连带干掉你可能开着的 IDE。
   想做的话跑一下 `tasklist | findstr java` 确认，再杀掉对应 PID，然后让下一轮重试构建。
2. 给 Windows Defender 加排除项：`G:\AIVideo\flutter_application_1\build` 和 `~\.kotlin`。
   这是这个错误**最常见的成因**。

`flutter build web` 不受影响。**但这条不能一直红着**：
`flutter_local_notifications`、`video_player` 都是要在真机上验的，
Web 跑得再绿也不能替代真机。上线前必须把它弄绿。

### 顺带已修掉的一个 B0 漏项

`flutter_local_notifications` **要求开启 core library desugaring**，
否则 `flutter build apk` 直接失败在 `checkDebugAarMetadata`。
B0 时 `flutter pub add` 和 `flutter analyze` 都**不碰 Android 构建**，所以没暴露。
已在 `android/app/build.gradle.kts` 开启。
**教训：依赖闸门必须在写业务代码前真的构建一次 APK。**

---

## 8. 环境事实

| 项 | 值 |
|---|---|
| Flutter / Dart | 3.47.5 stable / Dart 3.13.4 |
| 状态管理 | **Riverpod 3.4.3**（不是 2.x，有破坏性变更） |
| 关键 API | `AsyncNotifierProvider<NotifierT, ValueT>(NotifierT.new)`；`AsyncNotifier<StateT>` 有 `FutureOr<StateT> build()`、`Ref get ref`、`StateT get state`；`NotifierProvider` 同理 |
| 测试容器 | `ProviderContainer.test(overrides: [...])`（Riverpod 3.x 提供，自动 dispose） |
| 依赖 | dio ^5.11.1、flutter_riverpod ^3.4.3、flutter_secure_storage ^11.2.0、flutter_local_notifications ^22.3.1、uuid ^4.6.0、video_player ^2.14.1 |
| 路由 | **不用 go_router**（理由和迁移触发条件写在 `lib/router/app_router.dart` 顶部） |
| Mock 开关（**F10 之后**） | App **裸跑就是真后端**（`http://127.0.0.1:8000`）。要 Mock：`--dart-define=USE_MOCK=true`。换后端：`--dart-define=API_BASE_URL=https://...`。`--dart-define=MOCK_LATENCY_MS=4000` 让 Mock 走真实状态机。**测试侧仍然默认 Mock**，live 门禁照旧要显式给 `USE_MOCK=false` + `API_BASE_URL`（§5） |

### ⚠️ 坑

* **`use_null_aware_elements` lint**：`if (x != null) 'k': x` 必须写成 `'k': ?x`。
  `?` 在**值**前面，不是键前面 —— 写成 `?'k': x` 会报「键不能为 null」。
* **`extension JsonMapReader on Map<String, dynamic>`** 必须**不加前缀**导入
  （`import '../core/json_utils.dart';`）。写成 `as json` 会破坏它。
* **golden 渲染若用 `FontLoader` 加载中文字体，必须包在 `tester.runAsync` 里**，
  否则测试**挂住而不是失败**。
* **极简 Mock（不带 `latency`）下默认「提交即完成」**，所以这几条只能靠
  `works_polling_test.dart` 里**注入时钟**的 `FakeApiClient(latency:, clock:)`
  来验：排队位次、轮询退避、心跳起停。而
  「关掉 App 再打开进行中任务还在」、完成通知、作品页「进行中」分段的**真实观感**，
  仍然只能在开了 `MOCK_LATENCY_MS` 的真机/浏览器上手动看。
* **Mock 的 token 表也在内存里**（`FakeApiClient._userIdByToken`），所以
  **浏览器里一刷新就会「掉登录」** —— 新进程的 Mock 认不出旧 token，判 401。
  这不是持久化坏了（token 确实写进了 `localStorage`、也读得回来），
  是 Mock 没有对手可以比。想演示「重启保持登录」得让 Mock 表落盘，见 §6。

* ⚠️ **Riverpod 3 默认会给失败的 provider 自动重试 10 次**（200ms→6.4s 指数退避，
  见 `ProviderContainer.defaultRetry`）。这对本项目是**害处大于好处**：
  页面上的「重试」按钮会变成假的（用户还没点，背后已经试了 10 次），
  而且 `pumpAndSettle` 会把退避的定时器一路推完，测试的断言时机开始取决于时钟。
  **`app_providers.dart` 里的 `noAutoRetry` 就是关它的**，新的数据 provider 一律
  传 `retry: noAutoRetry`。

* ⚠️ **Riverpod 3 里 `AsyncValue` 没有 `valueOrNull` 了** —— 直接 `state.value`
  就是可空的。2.x 的写法搬过来会编译不过（这个坑在写 `credit_providers` 时踩到过）。

* ⚠️ **Riverpod 3 的 autoDispose 是「排一个零时长 Timer」来 dispose 的**
  （`ProviderScheduler.scheduleProviderDispose`），而 `flutter_test` 是在
  **测试体跑完之后**才拆 widget 树 —— 于是 `await tester.pump()`（不带时长）
  不推进假时钟，直接报「A Timer is still pending even after the widget tree
  was disposed.」。**解法：在测试体内调 `test/shell_harness.dart` 的
  `unmountAndDrain(tester)`**，不要靠 teardown。
  （这个报错看起来像「有个 Timer 泄漏」，实际是**拆卸顺序**问题，很容易查错方向。）

* ⚠️ **`TaskPollingController` 的 5 秒心跳跟着会话走，不跟 widget 树走**
  （`taskPollingProvider` 刻意**不是** autoDispose）。它会自己停：
  某一拍发现活动任务列表空了就停 —— 而**登出**正是这么停的
  （token→null → `activeTasksProvider` 报错 → `.value == null` → 判定不活跃）。
  代价是：**测试里如果留下了一个「进行中」的任务，心跳会比 widget 树活得久**，
  必须在收尾前显式 `container.read(taskPollingProvider.notifier).pause()`，
  否则那条测试会以「Timer is still pending」红。`works_polling_test.dart`
  最后一条就是这么做并写了注释的。

* ⚠️ **「这是谁的数据」的 provider 必须 `ref.watch(authTokenProvider)`**。
  否则 A 登出、B 登录后，B 会看到 **A 的数据**，而且不报任何错。
  原计划是在 `AuthController.logout()` 里 invalidate 一张清单，**B5 改成了依赖**：
  清单会漏（漏的时候什么都不发生，只是某天有人看到别人的数据），依赖不会。
  `test/me_credits_test.dart` 的「换账号」那条守的就是它 —— **故意改坏验证过会红**。

* ⚠️ **`DateTime.toIso8601String()` 的输出长度不固定**（微秒为 0 时只有毫秒），
  所以**绝不能用它按字符串排序**。流水那个「最新在前」就是这么写错的：
  `Z`(0x5A) 比数字大，同一毫秒内的记录顺序会颠倒。实测分页结果是
  `23, 22, 2..19 | 20, 21, 0, 1`。已改成解析成 `DateTime` 比、`id` 兜底。

* ⚠️ **`tester.tap()` 点到屏幕外的 widget 不会报错**，只打一行 warning 就过去。
  测试会「绿」，但什么都没测到 —— 这是最容易骗过自己的假绿。
  按钮在长列表下方时，**先 `await tester.ensureVisible(finder)`**。

* ⚠️ **`find.text(...)` 的期望条数会因为「文案统一」而变**：积分不足那句
  在错误条和弹框标题上**各出现一次**（刻意的，见 §9.4），
  所以断言是 `findsNWidgets(2)` 而不是 `findsOneWidget`。
  写这类断言前先想清楚「这句话在屏幕上应该出现几次」。

* ⚠️ **`AppShell` 的冒烟测试不能再裸 `pumpWidget`**。B5a 之后「我的」页要读
  provider，没有 `ProviderScope` 会直接抛。用 `test/shell_harness.dart` 的
  `pumpLoggedInShell`（它会真注册一个账号 —— `AppShell` 只在登录态下存在）。

---

## 9. B7 的浏览器验收（真实 Chrome，逐帧截图）

> 这一节是 commit `192e584` 和 `6b3eb61` 里都提到的「见 HANDOFF §9」。

### 9.1 怎么跑的

`flutter build web` → `python -I -m http.server 8080 --directory build/web` →
`chrome --headless=new --remote-debugging-port=9222` → 用 CDP 发**真实**鼠标/键盘
事件（`Input.dispatchMouseEvent` / `Input.insertText`）驱动，每步截图。

驱动脚本和截图**刻意放在仓库外面**：`G:\AIVideo\_acceptance\`
（`cdp.mjs` 驱动器、`run-b7.sh` 主线剧本、`run-login-roundtrip.sh` 登录往返剧本、
`01-…` 到 `55-…` 的截图）。理由：它们是**本机一次性的验收脚手架**，
不是工程产物 —— 坐标硬编码、只在 430×900 这一种窗口下成立，进仓库会误导人。

### 9.2 走通的主线（截图号 = 文件名前缀）

| 步骤 | 结果 | 截图 |
|---|---|---|
| 冷启动落登录页 | ✅ | `01-cold` |
| 注册（`MOCK` / `zhangwei` / `pw123456`）→ 首页，**可用积分 20** | ✅ | `20-home-fresh` |
| 首页写「一只猫在沙滩上奔跑」→ 图片生成页，**描述被带过来了** | ✅ | `06-imagegen` |
| 提交出图 → 结果页，**图上有「AI 生成」标识** | ✅ | `21-image-result` |
| 「做成视频」→ 视频页，**参考图已选好、描述也带过来了**，720P | ✅ | `08-videogen`、`09-videogen-bottom` |
| 提交视频 → **「可用积分不足」**（20 < 冻结 32） | ✅ | `22-insufficient` |
| 点「去看积分」→ 积分页：可用 16、3 条流水、**没有充值入口** | ✅ | `23-credits` |
| 回首页，余额已更新 | ✅ | `12-back-home` |
| 作品页：进行中/已完成，缩略图带 AI 标识 | ✅ | `13-works`、`14-works-done` |
| ↑ **⚠️ 这一行的说法在 F9 之后不完整**：当时网格里只有 AI 产物，所以「缩略图带 AI 标识」成立；它**不**等于「每一格都该带标」。混装场景见 §12 | — | — |
| 我的 / 设置：产品名「AI 视频创作」、版本 0.1.0 | ✅ | `15-me`、`16-settings` |
| 退出登录 → 确认框 → 回登录页 | ✅ | `24-logged-out` |
| **`localStorage` 里 token 被删掉了** | ✅ | CDP `eval` 查的，无截图 |
| 密码打错 → 说「用户名或密码不正确」 | ✅ | `26-wrong-password` |
| 正确密码 → 进主界面 | ✅ | `27-login-ok` |
| 用一个**陈旧 token** 刷新 → 清掉它、干净地回登录页 | ✅ | `55-reload-with-stale-token` |

### 9.3 过程中发生的两件事（**都不是 App 的 bug**，但都值得记）

1. **脚本第一版的点击全部错位**：因为 `Page.navigate` 到**当前那个 URL**
   是同一文档导航，浏览器不会真的重载 —— App 停在上一轮结束的页面上，
   后面每一个按坐标算的点击都落到了别处，截图看起来像「步骤全乱」。
   **修法：先 `goto about:blank` 再 goto 目标页。**

2. **「登出后用同一个账号密码登录，被挡在门外」** —— 看上去是个真 bug，
   但**是自动化打字的锅**：截图里那个用户名框写着 `pearpear`（我用 `Input.insertText`
   插了一次 `pear`，字**被插了两遍**）。Flutter web 的输入框聚焦本来就慢一拍
   （memory 里记过），这一版的重复插入是同一个根因的另一副面孔。
   证据：`41-pear-form.png` 里框里就是 `pearpear`。

   > **但「没人测过这条路径」这件事是真的**：原来的用例里，
   > **注册**走的是控制器 API（`authController.register(...)`），
   > **登录**走的才是登录页表单 —— 也就是说
   > 「注册表单里填的那个密码，登录时能不能用」从来没人测过。
   > 所以 B7′ 补了一条 `test/auth_flow_test.dart` 的
   > 「注册表单建的号，登录表单能登进去（一来一回）」，**它一次就绿了**，
   > 正好反证了 App 路径是通的、红的是打字的锅。
   > 这条测试留着 —— 缺口是真的。

### 9.4 B7′ 修掉的那条**假承诺**

浏览器里第一次走到「积分不足」时，错误条写的是 **「积分不足，请先充值」**。

**v1 没有充值**（§7.6，积分页上一个入口都没有，`test/me_credits_test.dart`
专门守着这条）。也就是说：**界面让用户去点一个不存在的东西** ——
比什么都不说更糟，他会去积分页翻三遍，然后来问「充值在哪」。

修法：文案改成 **「可用积分不足」**，动作指向**积分页**（`gen.errorAction`），
并加一条守卫（`test/copy_guards_test.dart`）扫描 `lib/` 非注释行禁止
「充值/支付/购买」。`test/generation_flow_test.dart` 里也钉了一句
`expect(find.textContaining('充值'), findsNothing)`。

> 这条是**只有真的在浏览器里点一遍才会发现**的 —— 所有单测当时都是绿的，
> 因为每一屏单独看都「渲染正确」。**假承诺住在屏与屏之间。**

---

## 10. 我的工作约定（这一路是怎么做的）

* **每批结束跑门禁**：`flutter analyze` 零告警 + `flutter test` 全绿 → commit → 打 tag。
  批次划分就是为了**每批都能回滚**，所以不要跨批合并。
* **写完守卫测试要故意把它改坏跑一遍**，确认它真的会红，再还原。
  一个从没红过的守卫测试没有价值 —— 这条抓到过两个真 bug：
  **Mock 的幂等表从来没被写入过**（防双击保护一次都没生效，会造成真实重复扣费）、
  **`GET /tasks/{id}` 的排队位次被硬编码成 0**。
* **代码注释写「为什么」，不写「是什么」**。尤其要写「**为什么不这么做**」——
  比如为什么 Mock 下沉到 `ApiClient` 而不是 `Repository`、为什么 `idempotencyKey` 是
  必填参数而不是内部生成、为什么登录失败不置 `AsyncLoading`。
* **发现文档自相矛盾时，拍板 + 标注**，不要沉默地选一个。§5 那张表就是这么来的。
* **不要为了让演示好看而伪造数据**（比如在余额不足时绕过校验塞积分、
  把 Mock 的报价改成「确定数字」）。宁可把「这条死路真实存在」写进 §3.1 交给你，
  也不要让上线当天的新用户替你发现。

  > ⚠️ **注意 §3.1 那次改动不违反这条**：改 `_signupGrant` 是**你拍的板**，
  > 而且改的是**契约值**（§12.1 前后端一起改）。这和「偷偷塞积分让演示过得去」
  > 是两件事 —— 前者是决策，后者是把死路藏起来。

---

## 11. 在 VSCode 里按 F5 打真后端（2026-10-16）

这一节记的是「**从编辑器里把 App 起在真后端上**」需要什么 —— 它和 §6 的无头
走查、§9 的真实 Chrome 验收**不是同一件事**：那两条都是 `flutter build web`
之后自己开浏览器，**绕过了 VSCode 的启动路径**，所以 F5 那条路上的坑它们照不出来。

### 11.1 新增了 `.vscode/launch.json`（**未跟踪的文件**）

两条配置：**真后端 (127.0.0.1:8000)** 与 **Mock（离线改 UI 用）**。
真后端那条给的是：

```
-d chrome --web-port 8080
--dart-define=USE_MOCK=false
--dart-define=API_BASE_URL=http://127.0.0.1:8000
```

四个不能省的地方：

* ~~**`USE_MOCK=false` 必须显式给**。`AppConfig.useMock` 的默认值是 **true**
  （`lib/core/env.dart`），不给就是「界面全对、数据全假」。~~
  **F10 之后这条反过来了**：默认就是 false（真后端），裸跑不用给；
  反倒是 **Mock 那条必须显式 `USE_MOCK=true`** —— 不给的话它会连真后端，
  而名字还写着「Mock」。这份 launch.json 里两条**都显式传**，是故意的：
  env.dart 的默认值以后再变，这份配置仍然说得清自己想连谁。
* **`API_BASE_URL` 必须跟它一起给**。`env.dart` 里有一条快速失败：
  `!useMock && baseUrl.isEmpty` 直接 `throw StateError`。**只给一半不是
  「回退到 Mock」，是应用起不来**（白屏 + 控制台一条 StateError）。
* **`--web-port 8080` 是钉死的**：后端的 CORS 白名单、以及 TOS 桶上那条
  CORS 规则都按这个 origin 配。换端口不会报错，只会让「图片全都不显示」
  这种最难查的症状重新出现（见 11.3）。
* **不要往 launch.json 里塞 `--web-browser-flag=--remote-debugging-port=9222`**。
  `-d chrome` 让 Flutter 自己起浏览器并**自己挑一个 CDP 端口**（实测 55888、
  57868，每次都不同），塞进去的那条和它自己那条会打架。要连 CDP 的话，
  从 `chrome.exe` 的命令行里把它实际用的端口捞出来，别写死。

### 11.2 顺手修掉的一个坏文件（**这不是 Flutter 的问题**）

`lib/main.dart` 里 `overrides:` 后面**丢了一个 `[`** —— 5 个 VSCode 报错全是
同一个字符的后果。已按最小改动补回（`git diff lib/main.dart` 现在为空，
与上一个 tag 逐字节相同），`flutter analyze lib/main.dart` 零告警。
**`lib/` 的其他部分仍然是一个字符没碰**（B2b 之后第五次）。

### 11.3 「F5 之后到底连的是谁」怎么验（**不花一分钱**）

Mock 模式**一个 HTTP 请求都不发**。所以：

1. 在登录页**故意输错密码**提交一次；
2. 去**后端的 access log** 里看有没有 `OPTIONS/POST /auth/login`；
3. 有 → 真后端（而且失败会留下一个 401，正好当探针）；没有 → 还在 Mock。

更省事的一种（F10 那次就是这么验的）：在页面里数请求。
`performance.getEntriesByType('resource')` 里指向 `:8000` 的条目数，
Mock 是 **0**。顺带还能看出登录后真的走了哪五个端点
（`/auth/login`、`/me`、`/assets`、`/tasks`、`/generation/cost`）。

界面上那条「用户名或密码不正确」两种模式下都会出现，**所以它证明不了任何事**。

### 11.4 图不出来的那件事：桶的 CORS（**App 的代码没问题**）

后端把桶设成匿名可读之后，**App 里那张生成好的图仍然不显示**，只有一个
加载占位 —— 而同一个地址 `curl` 拿到的是 200。原因是 Flutter web
（CanvasKit）的 `Image.network` 走 **XHR/fetch**、不是 `<img>`，
所以需要对象响应带 `Access-Control-Allow-Origin`（桶上加一条 CORS 规则即可）。

**排查入口在浏览器里，不在后端**：

```js
performance.getEntriesByType('resource').filter(e => e.name.includes('heluo'))
// 坑的形状：{ status: 0, transferSize: 0, initiatorType: 'xmlhttprequest' }
```

**「桶里有图」和「页面能显示」是两件事。** 完整经过（含规则内容与回退方式）
写在**后端 HANDOFF §2.6 的第四件事 ③** —— 那是这两个仓库里唯一记着它的地方。

### 11.5 这一轮验到的（真数据，可复算）

用 `DEMO2026` 从**界面**注册的新账号，走完「文生图」：
首页余额从 50 → **46**（结算 4 积分），作品页「已完成」里**看得见那张图**、
**AI 角标在**。图生视频**没成**，而卡点在后端那侧（账号里那个产品的并发配额
是 0），**不是 App 的问题** —— 后端 HANDOFF §2.6 第四件事 ② 有全部证据。

> ⚠️ `devtools_options.yaml` 与 `.vscode/launch.json` 都是**未跟踪**文件
> （前者是 Dart/Flutter 扩展自己生成的，后者是 11.1 那个）。
> **要不要入库由项目所有者决定** —— 入库的话注意 `.vscode/` 里别带本机路径。

---

## 12. F9：上传的参考图戴着「AI 生成」角标（**已修**）

### 12.1 怎么撞出来的

2026-10-17，后端把图生视频换成 MiniMax H3-Max 之后第一次**真网关跑通**
（后端 HANDOFF §2.7 有完整证据），从**前端界面**看成果时撞见的：

作品页「已完成」里摆着两格 —— 一格是生成出来的视频（该带标），
另一格是**用户自己上传的那张参考图**，而它**也戴着「AI 生成」**。
去库里对：`assets.is_ai_generated = 0`，`task_id` 是 `NULL`。
**数据层是对的，画面上是错的。**

### 12.2 根因：一个设计好、填好数据、**从来没接线**的字段

`work_thumbnail.dart` 那一行是唯一的决定点：

```dart
return AiGeneratedFrame(
  show: showBadge,          // 而 showBadge 的默认值是 true
```

而 `Asset.isAiGenerated` **在 `lib/` 里没有任何 widget 读过**
（`grep -rn isAiGenerated lib/` 只剩注释）。更刺眼的是：
**这个字段本来就是为这件事建的** —— `models/asset.dart` 写着
「将来可能有『用户上传的原图』混进资产列表（比如参考图），那些**不该**打标。
留一个字段，那天到了不用改数据结构」；Mock 的 `_uploadImage` 也一直
如实填 `false` 并写了注释。**只有画这一格的地方没接线。**

### 12.3 为什么原来那条测试不但没抓住，还把它钉住了

`generation_flow_test.dart` 里原有一条
「作品页：完成的作品出现在网格里，**且每一格都带 AI 标识**」——
它只造了一件 AI 产物，网格里只有一格，于是「每一格都带标」恰好成立，
**把「恒打标」这个 bug 当成不变量写进了用例名字里**。
这是「测试写成了对实现的复述」的典型样子：断言的不是规则，是当时的输出。

### 12.4 改了什么

只改一个文件、一行判断（`lib/widgets/work_thumbnail.dart`）：

| | 之前 | 之后 |
|---|---|---|
| 形参 | `bool showBadge = true` | `bool? showBadge`（**`null` = 跟着资产走**） |
| 判断 | `show: showBadge` | `show: showBadge ?? asset.isAiGenerated` |

**为什么缺省是 `null` 而不是「改成 `bool = false`」或「干脆去掉形参」**：
`= true` 分不清「调用方明确要标」和「调用方没传」，而这两件事的正确答案不同 ——
`null` 才把两种意图分开。去掉形参则是**砍掉调用方的发言权**，
而 `AiGeneratedFrame` 那句「宁可多打标，不能少打」在某些位置仍需要显式保证。

**为什么改这一处就够**：`WorkThumbnail` 是三个界面共用的一格 ——
作品页网格（`work_grid.dart` ← `works_page.dart`）、首页「最近作品」
（`recent_works_section.dart`）、参考图的选择器与已选槽位
（`video_gen_page.dart`）。全部**都没传** `showBadge`，所以三处一起好了。

**刻意没动的地方**：`image_result_page` / `video_result_page` 里那两处
`AiGeneratedFrame` 保持默认 `show = true`。那两页画的是**一个任务的产物**，
按构造就是 AI —— 在那里改成读服务端字段，等于给自己开一个
「服务端字段回错了 → 法律要求的标识消失」的口子。**混装点是资产列表，
不是结果页。**

### 12.5 守它的测试

`generation_flow_test.dart` 新增一条：造一件 AI 产物 + 从**同一条 repository**
真上传一张图，进作品页后**逐格**断言「有标 ⟺ 它是 AI 产物」。

* 为什么是逐格对、而不是数个数：数个数（「恰好一格有标」）在将来多一件资产时
  会变成假红，而真正该永远成立的是每一条资产都满足那个等价关系。
* 为什么从 repository 上传：上传记录的 `is_ai_generated=false` 是**数据层**的事，
  已经由 `fake_api_client_test.dart` / `models_test.dart` 钉住了；
  这条只需要证「画面上读不读那个字段」。
* 该条用例的**名字也改了**（去掉「每一格都带 AI 标识」那个错误的不变量）。

按 §10 的约定**故意改坏跑了两次**，两个方向都确认会红：

| 改坏成 | 红在哪 | 说明 |
|---|---|---|
| `show: showBadge ?? true` | `isAiGenerated=false 的那一格（1007）标识对不对` | 恒打标（原 bug 形状） |
| `show: showBadge ?? (asset.isAiGenerated && false)` | `isAiGenerated=true 的那一格（1006）标识对不对` + 另一条用例的 `AI 生成` 文字找不到 | 一个标都不打 |

### 12.6 浏览器上验过（真后端 + 真 MiniMax + 真 TOS 桶）

账号 `mm67826`（§2.7 那次真跑留下的）：网格里正好两格 ——
上传的 `ref.jpg`（`is_ai_generated=0`）+ 生成出的 `out.mp4`（=1，带播放键）。

| 界面 | 修之前 | 修之后 |
|---|---|---|
| 首页「最近作品」 | 两格都带标 | 视频格带标、上传格**干净** |
| 作品页「已完成」 | 两格都带标 | 视频格带标、上传格**干净** |

> ⚠️ **改完 `lib/` 重新验的时候，一定要真刷新到新 bundle**：
> `flutter build web` 之后直接 `location.reload()`，浏览器会拿**HTTP 缓存里的旧
> `main.dart.js`**，于是「修了但看起来没修」。判据是
> `performance.getEntriesByType('resource')` 里 `main.dart.js` 的 `transferSize`
> —— 是 `0` 就说明**吃的是缓存**，得先 `fetch('/main.dart.js',{cache:'reload'})`
> 再 reload。（本机没有注册 service worker，所以不用清 SW。）

---

## 13. F10：默认连真后端（Mock 改成必须显式说）

### 13.1 为什么要翻

起因只是一句「前端总是默认跑 mock 后端」。查下去发现这不是不方便，
是一个**会静默换掉整个世界的默认值**：

| 默认 | 忘带参数时你得到 | 能不能当场发现 |
|---|---|---|
| `useMock = true`（旧） | **全假数据**，而界面和真的**长得一模一样** | **不能**。§12.6 那次就被它咬过：代码改完了，浏览器里还是旧行为 —— 因为那一次连的是 Mock |
| `useMock = false`（新） | 一条看得懂的网络错（连不上 8000） | 能 |

当初立 `true` 的理由写在 `env.dart` 里：「因为本轮后端还不存在」。
后端 B0–B7.4 做完、图生视频真网关也跑通了，这个理由没有了，代价还在付。

### 13.2 改了什么（`lib/core/env.dart`）

一个 `AppConfig` 拆成**两个工厂**，共用**同一段装配**（`_read`），
只在两个 `defaultValue` 上不同：

| 工厂 | 谁用 | `USE_MOCK` 默认 | `API_BASE_URL` 默认 |
|---|---|---|---|
| `AppConfig.forApp()` | `main.dart`（也就是所有真实运行） | **false** | **`http://127.0.0.1:8000`** |
| `AppConfig.forTests()` | `test/live_backend.dart`（也就是 live 门禁） | **true** | **没有**（`USE_MOCK=false` 却没给地址 → 当场 `StateError`） |

两件**看起来可以合并、但不能合并**的事：

* **测试侧必须仍然默认 Mock。** `USE_MOCK` 这一个开关同时兼着两个职责：
  「这个包里连的是谁」和「这次 `flutter test` 是不是在打真后端」。
  后者撑着 24 条 live 用例的 skip。翻成真后端的话，裸跑 `flutter test`
  会去打真后端 —— 而那 24 条**每条用例前都清库**。
* **两边必须共用 `_read`。** `live_backend.dart` 存在的全部意义就是
  「走 `main.dart` 走过的那条配置路径」；各写一份装配，测的就变成测试自己了。

`defaultValue` 必须是**编译期常量**，形参不满足 —— 所以那两行
`fromEnvironment` 只能一个工厂一份。这也正是两个默认值能被分开的原因，
不是重复代码。

### 13.3 两个靠旧默认值「静默工作」的消费者

它们不会报错，只会换一个世界 —— 所以两个都改成**显式传**：

* `.vscode/launch.json`（**未跟踪的文件**）的 Mock 那条：不传
  `USE_MOCK=true` 的话，它会连真后端，而名字还写着 Mock。
  真后端那条也照旧传全两个 define，env.dart 以后再变都不会漂。
* `scripts/build-web.sh`：它默认 `MODE=mock`，而 Mock 那一支原来什么都
  不传 —— 于是打出来的是**真后端包**，但 zip 名字和 `BUILD-INFO.txt`
  都写着 Mock。这种包到客户手上就是「演示时连不上」，没人会想到是打包参数。

### 13.4 两条守卫（`test/copy_guards_test.dart`）

| 守什么 | 怎么断 | 它什么时候会红 |
|---|---|---|
| App 裸跑连真后端 | 直接调 `AppConfig.forApp()`（裸跑 `flutter test` 时那些参数就是没给的） | 有人把默认翻回 `true` |
| 测试裸跑仍走 Mock | **读源码**切出 `forTests` 的工厂体，看 `defaultValue` | 默认被翻成 false，或有人给它补了 `API_BASE_URL` 默认值（会把 live 门禁那条快速失败废掉） |

第二条只能读源码：测试进程自己就是带着参数编译出来的，它没法伪造一个
「命令行什么都没给」的世界去调 `forTests()` —— 能观测到的只有「这次运行
实际拿到了什么」，那是个同义反复，永远不会红。

§10 的规矩照走：两条都故意改坏过，确认各自会红再还原。
第一次还原时我的脚本**只匹配到了 `forTests` 那段**（两个块长得像），
把 `forTests` 还原成了 false、`forApp` 留在了 true —— 结果两条守卫同时红。
这反而证明了它们互相独立，但也是「恢复操作本身要验」的一个实例。

### 13.5 真验过（两件事，都不花一分钱）

**① 裸跑就是真后端。** `flutter build web --release`（**一个 define 都不给**）
→ 静态服务器 + 无头 Chrome → 用真账号 `mm67826` 登录：

| 证据 | 值 |
|---|---|
| 产物里的地址 | `main.dart.js` 里 `http://127.0.0.1:8000` 出现 1 次 |
| 页面发出的请求 | `/auth/login` `/me` `/assets` `/tasks` `/generation/cost` —— 全 `[200]` |
| 登录后余额 | **30 积分** |
| 首页最近作品 | 两格：视频格带 AI 标、上传格干净（§12 的修复在真数据上仍然成立） |

余额这一条是**决定性的**：Mock 的用户是进程内内存（新开一个浏览器根本登不进去），
而且 Mock 注册送 **50**，不是 30。

**② Mock 仍然在，只是要显式要。** `--dart-define=USE_MOCK=true` 重新打包：

| 证据 | 值 |
|---|---|
| 注册页脚注 | 「演示模式：数据存在本机内存，邀请码填任意内容即可」 |
| 注册后余额 | **50 积分**（Mock 的注册赠送） |
| 发往 `:8000` 的请求数 | **0** |

两条合起来才说明「默认是 real」和「显式 mock 仍然可用」**同时**成立 ——
只验第一条的话，一个把 Mock 分支删掉的改动也能通过。

### 13.6 顺手撞见的一个打包坑（**没修，先记着**）

有一次 `flutter build web` 之后，`build/web/assets/` **整个是空的** ——
没有 `FontManifest.json`、没有 `MaterialIcons-Regular.otf`。页面能起来，
但**所有图标变成豆腐块**，`assets/FontManifest.json` 回 404。

* **没能复现**：紧接着的重建、以及在已有 `build/web` 上再建一次，都正常。
  唯一不同的条件是**当时有个静态服务器正指着 `build/web`**。不写成结论。
* **但 `build-web.sh` 的体检抓不住它**：它只 `[[ -e "build/web/assets" ]]`，
  **目录存在、里面是空的，检查照样通过**。
* 要补的话是一行：把 `assets` 换成 `assets/FontManifest.json`（或者断非空）。
  **这一条没进本批** —— 它是既有漏洞，不是 F10 引入的，
  按「每批可回滚」的规矩应该单独一批，或由你点头后再动。

### 13.7 没做什么

* **没动计费、没动契约**：一个字符串没改。
* **没动 live 门禁的命令**：测试侧仍然要显式 `USE_MOCK=false` +
  `API_BASE_URL`。这是刻意的，理由见 13.2 和 `test/live_backend.dart` 的注释。
* **`.vscode/launch.json` 仍然未跟踪**：它改过了（Mock 那条补了
  `USE_MOCK=true`），但和 §11.1 一样停在「你本地的编辑器配置」这个位置，
  没有进 git。
