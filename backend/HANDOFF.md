# 后端交接文档

**写给下一个会话：你没有任何上下文。这份文件是让你不用重新推导就能开工的东西。**
先读完这一页，再动手。

最后更新：2026-10-17 · 进度 **B0–B7.4**（B7.4 = 图生视频换 MiniMax H3-Max，
**✅ 已过真网关**，2026-10-17，一次就成、零重试，证据见 §2.7）·
后端测试 **402** 条 · `check_deps` **18/18** ·
跨仓 **live 24 条 / 覆盖台账 43 条**
（live 模式下 `flutter test` 共 **163** 条：**139** 全部通过 + 24 条 live 用例由 skip 变绿）
⚠️ **B7.4 只动后端 `app/` 与 `tests/`，前端 `lib/` 和 `test/` 一个字符没改** ——
所以那些条数是**当场重跑**确认没被带坏的（见 §2.7 的判据）。
（`139` 那个数是 **F9** 加的：真跑那一轮撞出的「上传件被打 AI 标」，
前端 `lib/` 改了一行、`test/` 加了一条，**与本仓无关**，见前端 HANDOFF §12。）
**B5–B7 都没碰前端 `lib/`**（B2b 之后第四次）。B5/B6 动的是前端 `test/`：把
`contentRejected` / `providerError` 从「本轮触发不了」挪进「真触发过」，
各补了一条打真后端的用例（为什么这两条 B5/B6 才能真触发，见下面 B5 的触发词那段）。
**B7 连前端 `test/` 都没动** —— 它只加了 `tests/test_acceptance_b7.py` 一个文件，
`app/` 一行没改，所以上面那 24 条是**当场重跑**确认没被带坏的。

⚠️ **真即梦已经打过一枪，而且它当场推翻了 B6 的一条前提**（2026-10-15，`b7.3` 修）：
文生图在真网关上**跑通了**（`submit` 回 `10000` + 真 `task_id`、`poll` 回 `done`、
121 KB 的真 JPEG 就在响应体里），而我们把它判成了 `failed` + 全额退款 ——
因为 `jimeng_t2i_v31` **不给产物地址，把字节内联在 `binary_data_base64` 里**。
那段经过、以及「为什么修法是落 spool 文件而不是加一条字节通道」，见 §2.6 的
「撞到的第三件事」。**桶那一侧（`STORAGE=oss`）也是真打过的**（见 §2.6 的第二件事）。

⚠️ **2026-10-16 又往前走了一格**（详见 §2.6 的**第四件事**，那一节整段是新的）：

- **文生图整条进了前端界面**：浏览器注册 → 提交 → worker 转存 → 真桶 →
  **作品页看得见那张图**（任务 14、用户 `b7verify`、`t/14/out.jpg`、
  139537 字节、`is_ai_generated=1`、结算 4 积分）。这一格补的正是上一枪
  **缺的那一段** —— 上一枪的判据里自己写着「没有经过 worker → 转存 → S3 →
  标识写入那一段的真外部验证」，这次经过了一遍。
- **桶还缺一条 CORS 规则**（这一条只有「用浏览器看」才会暴露）：
  Flutter web 的 `Image.network` 在 CanvasKit 下走 **XHR**、不是 `<img>`，
  所以「桶匿名可读」**不够**，对象响应必须带 `Access-Control-Allow-Origin`。
  症状是**桶里有图、`curl` 也 200、页面上只有一个加载占位**。规则已新增（可逆）。
- **图生视频一步都没成，而卡点已经不在这个仓库里**：
  即梦那边那个产品的**并发配额是 0**，要人或钱去解（§8.2 第 11 条）。

⚠️ **2026-10-17：图生视频换了通道，而且真跑通了。**（`b7.4-minimax-video`，详见 §2.7）
图生视频整条从即梦换到 **MiniMax H3-Max**，**文生图留在即梦不动** ——
因为上面那条「卡点不在这个仓库里」是个商业动作，而「能不能出片」不该跟着一起等。
新增 `VIDEO_PROVIDER` 开关（留空 = 跟随 `PROVIDER`，所以既有部署零行为变化），
`build_provider()` 因此长出了 `kind` 形参（**本批唯一一处偏离那条纪律的地方**，
理由见 §2.7）。**计费契约与前端 `lib/` 一个字没动。**

**密钥由项目所有者填好之后，真链路当场走了一遍：图生视频一次就成、零重试**
（任务 19：提交 200 → 两次轮询 → 成片 2.0 MB / 1344×768 / h264+aac、
转存进桶、AI 标识在、作品页可播放、余额按 20 结算）。
**上面那条「图生视频一步都没成」至此不再成立** —— 但它**不是被修好的**，
是**换了条路**：即梦那个产品的并发配额**仍然是 0**（§8.2 第 11 条）。
清单一整遍的证据在 §2.7。

⚠️ **仍然没被真东西碰过的**：`DURATION_SLACK_SEC` 的真值（要一条**成片比请求长**
的视频 —— 实测这一次「请求 5 → 成片 5」，恰好没有余量压力）、
即梦那一路的图生视频、以及**即梦**能不能取到我们给的参考图
（MiniMax 那一格 2026-10-17 关掉了，判据是「成片首帧与我们那张图逐像素一致」）。

---

## 0. 三十秒版

两个独立仓库，各自打 tag：

| 仓库 | 路径 | 状态 | 最新 tag |
|---|---|---|---|
| 前端 Flutter | `G:\AIVideo\flutter_application_1\` | **v1 完成并冻结**（B5–B7 只动了 `test/`，`lib/` 没碰） | `b6-providers`（前端侧那一笔） |
| 后端 FastAPI | `G:\AIVideo\backend\` | B0–B7.4 完成，**12 个端点 + 真队列 + 真字节 + 合规与对账 + 即梦/S3 适配层 + §15.1 端到端 + MiniMax 视频那一路（**已过真网关**，2026-10-17）**；外加真即梦的两轮修正 | `b7.4-minimax-video` |

**后端已经能跑了，而且前端真的连上过一次**：`/auth/*` `/me` `/credits/ledger`
`/uploads/image` `/generation/{image,video,cost}` `/tasks*` `/assets*` 全部实现。
`provider=fake` 时提交即完成、积分当场结清（契约一个字没变，有测试钉着）。

**B3 把「跨时间的真排队」做出来了**：`tasks` 表自己当队列、`worker.py` 是
一个后台线程的轮询循环（§8.3 的六条职责逐条落位），闸门满了是**排队**
而不是报错。**并且这条队列在真进程里被手工验过**（一条 `queued` 任务在
0.4 秒内被 worker 自己推到了 `succeeded`，全程没有任何 HTTP 请求碰它）。
详见 §2.4。

**B4 让字节真的存在了**：上传的参考图落进 `media_root`、fake provider
真的产 PNG / MP4、`ffmpeg` 真的抽帧成 1280×720 的封面、`/media/<key>`
真的取得到那些字节。在此之前，每一个 `public_url` 背后都是**空的**。
**并且这条链路在真进程里手工验过**（真 uvicorn + 真 TCP + 真磁盘，
§2.5）。**响应形状一个字段都没变。**

**B5 把「合规」和「成本」补上了，并且这两件事到今天为止一行代码都没有**：

- **隐式标识**（《人工智能生成合成内容标识办法》要求的**法律义务**）：产物落盘前
  就把标识写进文件元数据 —— 图片 EXIF `ImageDescription`/`UserComment` + 一个 XMP 包，
  视频 MP4 `title`/`comment`/`description`。走容器字节拼接 / `-c copy`，**一个像素、
  一个码流比特都不动**（有 `image_digest` / `video_stream_digest` 逐字节证明）。
- **入口审核**（§10.2 第①层）：`screen_input` 挡在**任何写库动作之前**，
  `casefold` + 去空白 + 去零宽 —— 漏任何一步都是一种绕过。
- **`provider_calls` 对账**：这张表 B1 就建好了，到 B5 之前**一行都没被写过**。
  现在每次 `submit` / 每次 poll 都留一行，**包括被回滚掉的那一次**
  （事务外独立会话冲，见 README「B5 定的几件事」）。

**B6 把「真外部」那两件东西写完了 —— 但一个真字节都没发出去过**：

- **即梦适配层**（`providers/jimeng.py` + `jimeng_sign.py`）：两段式
  `CVSync2AsyncSubmitTask` / `CVSync2AsyncGetResult`、Volcengine 签名 V4、
  审核码 → 处置的映射、产物地址与时长提取。**每一个字段名、每一个 `req_key`
  都是猜的**，用合成上游（`httpx.MockTransport`）证的是「给定这种响应我们处置对」，
  不是「即梦真会这么回」。**验收清单在 §2.6，填完 AK/SK 与桶名照着走。**
- **`S3Storage`**（`services/storage.py`）：boto3 走 **S3 协议**，
  阿里云 OSS / 腾讯云 COS / MinIO / R2 都通，差别只有端点与寻址风格。
  `url_for` 给的是**永久地址**（不是预签名 —— 那会过期，见 §3.14）。
  顺带修掉一个**只有换 OSS 才会暴露**的 bug：`_create_assets_for` 原来调的是
  模块级的 `public_url_for`，把 `/media/` 写死在路径里。
- **外加两件本就该一起做的**：`req_key` 编进 `provider_task_id`（不占进程内存，
  见 §3.15）、计费算式从两个 provider 里抽到 `providers/pricing.py`（一份，
  有 `ast` 守卫钉着「不许长回第二份」）。

**B7 把 §15.1 那条剧本变成了两条可重复的命令**（`tests/test_acceptance_b7.py`
六条用例 + 一次真进程手工验收），并且**顺手闭上了 B5 留下的那个口子**：
「取回 `public_url` 读得出标识」以前只在测试进程里验过，现在是**真 uvicorn
+ 真 TCP + 真磁盘**验过的，还顺带验了「重启之后那条任务还在、资产还取得到」。
**细节全在下面 `### B7` 那一节**（这一批只加了一个测试文件，`app/` 一行没改）。

**B7.3 是真凭据那一侧的第一次实弹**（`b7.3-inline-artifact`，2026-10-15/16）。
它做的三件事，都不是「新功能」，是**真外部把我们的假设打回来之后的重修**：

1. **凭据本身是错的类型。** `.env` 里那对 `JIMENG_AK/SK` 是 60 位 base64 味 +
   158 位 base64url —— **不是火山 IAM 凭据的形状**（IAM 是 `AKLT` + 43 位，47 字符）。
   网关对它的回答是 `InvalidAuthorization`。**这条花了一整轮排查**，因为
   四种失败（形状错 / 签名实现错 / `req_key` 错 / 能力没开）在那个错误码上长得一样。
   分开它们的办法是**逐条做减法**，见 §2.6 第三件事的开头。
2. **`Host` 必须进签名**（`jimeng_sign.py`）—— 第一版收了这个参数却忘了并进
   待签头集合。**这一条不是真缺陷，是规范偏离**：改完之后真网关的答案一个字没变
   （真正的原因还是第 1 条），但它是按规范该改的，且现在有测试钉着。
3. **产物可能是内联的字节，不是一个地址**（`jimeng.py`）—— 真正让文生图
   从「成功却判失败」变成能交付的那一条。

**B7.4 是「换一条通道」而不是「修一个 bug」**（`b7.4-minimax-video`，2026-10-17）：
图生视频整条从即梦换到 **MiniMax H3-Max**，文生图留在即梦不动。理由在头部那段
（卡点是个商业动作，而「能不能出片」不该跟着一起等）。新增 `VIDEO_PROVIDER`
开关、`build_provider(kind)`、`providers/minimax.py` + 49 条测试。
**计费契约与前端一个字没动。⚠️ 这一批没有真调用过 MiniMax。**

**下一步：验收清单有两份了，都是「填完密钥照着走」那种形态。**

| 清单 | 管哪一路 | 状态 |
|---|---|---|
| **§2.6** | 即梦（文生图 + 图生视频） | ① 过、② 过、③ **只过了文生图那半**（图生视频整条没成）、④ 只跑到「写/读回/删」 |
| **§2.7** | MiniMax（图生视频） | ✅ **2026-10-17 已走过，图生视频整条通了**（一次就成、无重试、作品页看得见） |

两份清单里**都**有一个形状相同的空位：**provider 到底能不能从它自己的机房
把我们桶里那张参考图下下来**。即梦那边四次提交全死在闸门前面所以没看见；
MiniMax 那边连提交都还没发生过。

⚠️ 「B0.5 留到项目收尾时再填 AK/SK」那条调度决定**已经作废** —— 密钥填了、
真调用打过了（§8.1 里有说明，别照着旧的那段去「不要催」）。

契约的权威出处是 `G:\AIVideo\工程文档.md`，有歧义时**以冻结的前端为准**。

---

## 1. 开工前必须知道的四件事

### 1.1 每条命令都要带 `PYTHONIOENCODING=utf-8`

这台机器是中文 Windows，系统区域编码 **GBK**。不带这个环境变量，
**往控制台打中文就会崩**。

```bash
cd /g/AIVideo/backend
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest
```

### 1.2 `.ini` / `.cfg` 里不许写中文

同理：这些文件被 configparser 之类按**系统区域编码**读。
一句中文注释会让工具在读配置阶段抛 `UnicodeDecodeError`，
**报错位置和病因完全无关**（已经踩过一次，见 `alembic.ini` 里的记号）。
中文说明一律写进 `.py` 文件 —— Python 源码按 UTF-8 读，安全。

### 1.3 两个门禁，每批都跑

```bash
# 依赖闸门：证明每个依赖不只是「装上了」，而是「真的能用」
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/check_deps.py

# 测试
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest
```

外加**每个批次都跑一次前端回归**，证明后端改动没碰坏前端：

```bash
cd /g/AIVideo/flutter_application_1 && flutter test    # 应 139 全绿（F9 之后）
# ⚠️ 这个数会随前端批次变，**别把它当契约** —— 认的是「全绿」，
# 不是「等于某个数」。变了就去前端 HANDOFF §2 看是哪一批加的。
```

### 1.4 夹具在 `tests/conftest.py`，先读它

里面有 `make_app`（按需覆盖环境变量后造 app）、`db`（临时库）、
`session`，以及 **B2 新加的 `api`**：一个打**临时文件库**的 httpx 客户端
（`ASGITransport`，不经过网络），每次取用它先 `POST /__test/reset`，
所以每条用例都从空库 + 邀请码 `MOCK` 开始。

**B3 又加了三个，用之前先看它们的注释**：

- **`api_session`** —— 一个绑在 **`api` 那个库**上的会话，用来直接摆数据。
  ⚠️ 它和上面那个 `session` 是**两个不同的临时文件**：往 `session` 里插
  `user_id=7` 的任务，`api` 那个库根本没有这个用户，外键当场报错
  （而恰好没外键的表会变成「查不到数据」这种像业务 bug 的东西）。
  它依赖的是 `api` 而不是 `api_app`，为的是把「先 reset 再建会话」的顺序钉死。
- **`scripted`** —— 把 `build_provider(kind)` 换成 `tests/_providers.py` 里的
  `ScriptedProvider`（继承 `FakeProvider`，所以计价逐字相同，只覆写
  「什么时候算完」和「什么时候报错」）。
  ⚠️ **B7.4 起它接过 `kind` 但逐 kind 返回同一个替身** —— 这是故意的：
  既有的 40 多条用例验的是「任务怎么走」，不是「按 kind 路由」，给它们
  一个按 kind 变化的替身会把那些用例变成「碰巧还是绿的」。
  路由本身由 `test_minimax.py` 单独钉。- **`instant_scripted`** —— 上面那个 `polls_before_done=0` 的版本：
  「走异步接口、但第一次问就有结果」。它把**「任务会不会经过队列」**
  和**「谁把它推到终态」**分开验，混在一起的话一条用例红了看不出是哪条坏了。

**`get_settings()` 带 `lru_cache`** —— 想测「某个环境变量
取另一个值时行为如何」，必须依次做三步：改环境 → `get_settings.cache_clear()`
→ **`reset_engine()`** → 建 app。漏掉 `cache_clear` 那步，测的是上一次的
配置，而测试**照样是绿的**；顺序反了（先 `reset_engine` 后 `cache_clear`）
也一样测错。这个夹具里为这两点各写了一段注释。

契约测试**全是 async** —— 这不是风格选择：httpx 0.28 的 `ASGITransport`
只有异步接口（见 §5）。

---

## 2. 已完成的具体边界

### B0 `b0-skeleton`

- `app/main.py`：入口很薄，只有建 app、挂 CORS、`/health`、挂 `/__test/*`
- `/health` 返回 `{status, version, env, provider, storage}` —— 后两个是**刻意暴露**的，
  接错环境时最先要看它
  ⚠️ **B7.4 起多一个 `video_provider`**（`provider` 键**没动**，有两条契约测试钉着）。
  现在「两路各是谁」只有这一个证据面，接错环境时先看它 ——
  只看 `provider` 会把「图片即梦、视频 MiniMax」读成「全在即梦」
- `/__test/*` 受 `TEST_MODE` **硬门禁**：关着时这些路径**在路由表里根本不存在**
  （不是「存在但返回 403」）。它们能凭空造积分、能删库
- `scripts/check_deps.py` 15 项，**15 项全过**（2026-10-13 ffmpeg 那项转绿，见 §6.1）
- 每一个依赖检查都做一次**真动作**而非 `import`；三条是**反证**
  （缺 `JWT_SECRET` / 选即梦无 AK/SK / 弱密钥，都必须启动失败）

### B1 `b1-schema`

7 张表，`alembic/versions/e211cfb31c17_b1_initial_7_tables.py`：

| 表 | 列数 | 关键点 |
|---|---|---|
| `users` | 11 | 多一列 `username_canonical`（见 §3.6） |
| `invite_codes` | 9 | 邀请制是**花钱的闸门**（§7.5） |
| `credit_accounts` | 4 | `user_id` 是主键；**没有 `available` 列**，现算 |
| `credit_ledger` | 9 | `amount` 恒正，方向靠 `kind` 推导 |
| `tasks` | 26 | 兼队列；`UNIQUE(user_id, idempotency_key)` |
| `assets` | 13 | `is_ai_generated` 是**法律义务**字段 |
| `provider_calls` | 12 | 成本对账；**绝不存 AK/SK 或请求头** |

- `alembic check` **零差异**（模型与迁移一致），upgrade→downgrade→upgrade 可逆
- 8 个任务状态与前端 `lib/core/constants/task_status.dart` **逐字对齐**，有测试钉死

### B2 `b2-endpoints`

§12.1 的 12 个端点全部实现（**13 条路径** —— 文档把资产的查与删写在一行，
实际是 `GET /assets` 与 `DELETE /assets/{asset_id}` 两条），加上记账、
fake provider 与 `/__test/*`。**本批没有新迁移**，B1 的 7 张表装得下全部字段。

| 文件 | 是什么 |
|---|---|
| `app/errors.py` | `AppError` + 三个处理器（AppError / 请求校验 / 兜底）→ 顶层 `{code,message}` |
| `app/security.py` | bcrypt（用 `bcrypt_rounds`，测试里调到 4）+ JWT 签发/解码 |
| `app/deps.py` | `get_db`（复用 `database.get_db`）、`get_current_user` |
| `app/schemas.py` | **响应形状的全部断言依据**，每个 `fromJson` 字段逐条对照着写 |
| `app/services/credits.py` | `grant` / `freeze` / `settle_and_refund` / `refund_frozen_all` / `charge_frozen` / `adjust` |
| `app/services/generation.py` | 提交（校验 → 幂等 → 配额 → 建任务 → 冻结 → 推进到终态）、问价、取消 |
| `app/services/assets.py` | 参考图落库（分块读，超 20MB 在门口就拒）、资产查询/删除 |
| `app/providers/{base,fake}.py` | §12.2 的 Protocol + **永久测试夹具**（复现 32/24/8/22） |
| `app/routers/*.py` | 8 个文件、13 条路径。**这一层很薄，校验全在 services** |
| `tests/test_*_b2.py` | 7 个文件、125 条用例 |

跑过的验收（§9.1 的「人工跑一次」）：

```bash
TEST_MODE=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8123
```

- `/health` → `provider: fake`、`storage: local`
- `/docs` / `openapi.json` → 14 条路径 = 13 条业务 + `/health`；
  **`TEST_MODE` 关着时 `/__test/*` 不出现**（两种状态都实测过）
- curl 走完 注册 → 上传参考图 → 出图 → 转视频 5 秒 → 看积分，
  **余额落在 22、冻结回 0**，流水是 `grant 50 / freeze 4 / settle 4 /
  freeze 32 / settle 24 / refund 8`（§15.1 的剧本，逐字对上）

### B2b `b2b-live-gate`

跨仓契约门禁。**功能代码全在前端仓库的 `test/` 下，后端本次一个字符没改** ——
本仓库这次只改了文档（§3.12 那处错误说法 + §4 的记录）。**两仓都打了
同一个 tag**，这样「B2b 回滚到哪儿」在两个仓库里是同一个答案。

- 前端 `DioApiClient` **第一次真的被执行**（在此之前它只是「写完了、没跑过」）
- 第二层门禁打真后端 **41 条全绿**；默认 Mock 套件 138 条全绿 + 22 条可见 skip
- 13 个端点与后端路由表两个方向比对一致；9 个前端错误码全部交代过
- 交付物、四组门禁的分工、以及**第一次跑就撞出来的五件事**见 §4

### B3 `b3-queue`

跨时间的真排队。**没有新迁移** —— B1 那 7 张表装得下全部字段
（`ix_tasks_status_queued_at` 那条索引 B1 就建好了，当时的注释写的就是
「worker 扫『该提交的』和『该轮询的』」）。

| 文件 | 是什么 |
|---|---|
| `app/services/queue.py` | 入队（`enqueue`，唯一入口）/ 出队（`claim_next`）/ 位次（`position_of`）/ 闸门（`has_free_slot`）/ 退避（`requeue_for_retry`） |
| `app/worker.py` | 后台轮询循环：`run_once`（可测的逻辑）+ `run_forever`/`start_background`（调度） |
| `app/services/generation.py` | 状态机被**拆成两个入口共用一套收尾**：`dispatch` / `poll_once` / `finish_succeeded` / `handle_failure` / `expire_stale` |
| `app/providers/base.py` | `ProviderResult.done`（回执 vs 成品）+ `ProviderFailure`（带 `retryable` / `rejected`） |
| `app/main.py` | `_start_worker`：按配置起线程；**`TEST_MODE=1` 强制不起** |
| `app/logging_setup.py` | **新增**。修掉「应用日志在真进程里一个字都打不出来」，见 §2.4 的第 2 件事 |
| `tests/test_queue_b3.py` / `test_worker_b3.py` / `test_logging_b3.py` | 8 + 9 + 6 条 |
| `tests/_providers.py` | `ScriptedProvider`：**测试侧**的替身（继承 `FakeProvider`，所以计价逐字相同） |

设计上的取舍、以及「为什么队列就是 `tasks` 表」都写在 `services/queue.py`
的文件头 —— 那是算术（即梦并发 1–2 且平台共享 → 只要一道信号量），不是品味。

#### 这一批补上的两件事，是**真进程**里发现的，测试看不见

这是 §9.1「人工跑一次」那条约定**第二次**抓到东西（第一次是 B2b 的
401 假象）。两件都不是单元测试能发现的，因为它们恰好都发生在
「pytest 已经替你配好的那个环境」和「生产环境」的差别里。

**① 后台 worker 从没被执行过 —— 而它是对的。**
`run_forever` / `start_background` 在任何测试里都不跑（测试只调 `run_once`，
那是有意的：线程 + sleep 的测试不稳定）。所以「真起一个进程的时候，
那个线程到底会不会被拉起来」这件事**一行测试都没有**。
手工验收的判别法很便宜，而且**决定性**：

> 手工往库里摆一条 `queued` 任务（连冻结一起做，见下面的剧本），
> 然后**一个请求都不发**，看它会不会自己变成 `succeeded`。

实测：`queued_at` 到 `finished_at` 相隔 **0.4 秒**，`submitted_at` 是 worker
自己写的，余额 46 / 冻结 0，流水 `grant 50 / freeze 4 / settle 4`。
如果 worker 没起来，这条任务会**永远停在 queued** —— 所以这个判别法是
二值的，没有中间状态。

**② 应用自己的日志在真进程里全都打不出来。**
uvicorn 的默认日志配置**不给 root 挂 handler**（只给 `uvicorn` /
`uvicorn.error` / `uvicorn.access` 三个）。而应用这棵树
（`aivideo`、`aivideo.worker`）propagate 到 root，root 上没有 handler ——
于是**除了 WARNING 以上会被 `logging.lastResort` 兜到 stderr（无格式、
无时间戳）之外全部丢弃**。

后果比「日志少几条」严重：`main.py` 的 `lifespan` 里那段**启动横幅**，
存在的全部意义就是「扫一眼就知道连的是 fake 还是 jimeng」
（那是 B0 特意写的防误连生产事故的措施），**而它从来没被打印出来过**。
B3 加上 worker 之后更贵：`worker 启动`、每轮 tick 摘要、重试与过期的
warning 全在日志里，而 worker 是那种「不看日志就完全查不出问题」的东西。

**测试为什么看不见**：pytest 的 logging 插件在 root 上装了捕获 handler，
所以 `caplog` 一切正常、日志也「看着没问题」。**只有真跑一次进程才看得见。**

修法：`app/logging_setup.py` + `create_app()` 的第一行调用。规则是
**root 上已经有 handler 就什么都不做**（pytest / systemd / 云日志 agent
都算「已经有人配过」），只给 `aivideo` 挂一个 StreamHandler。
`tests/test_logging_b3.py` 六条钉住它，其中两条要说明一下：

- `propagate` **必须保持 True** —— 关掉它是一个「看起来在做好事」的改动
  （「自己都挂了 handler，再往上传不就重复了吗」），而代价是 `caplog`
  静默失灵 + 部署平台收不到日志，生产里用 stderr 看日志的人却完全看不出
  区别。有一条用例专门守它。
- 「root 空着」那条分支在 pytest 里**构造不出来**（插件在每个阶段重挂
  handler，测试里清掉会被立刻盖回去，实测撞过）。所以判据抽成了
  `root_is_configured()`，用替身验 —— 而那一条恰恰是**生产唯一会走的分支**。

#### B3 手工验收剧本（可复用）

```bash
# 1. 一个**不是** TEST_MODE 的库（TEST_MODE=1 会强制关掉 worker！见 §3.4）
cd /g/AIVideo/backend
mkdir -p .b3accept
DATABASE_URL="sqlite:///G:/AIVideo/backend/.b3accept/aivideo.db" \
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m alembic upgrade head

# 2. 种邀请码。⚠️ 没有官方脚本（见 §6），用一次性内联脚本
#    （直接插 invite_codes 一行，照 models.py 的字段）

# 3. 起服务：**TEST_MODE=0 + WORKER_ENABLED=1**
DATABASE_URL="sqlite:///G:/AIVideo/backend/.b3accept/aivideo.db" \
  PUBLIC_BASE_URL="http://127.0.0.1:8124" WORKER_ENABLED=1 TEST_MODE=0 \
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8124
# 日志里应该看到启动横幅 + "worker 启动（巡检间隔 2.0 秒）"

# 4. 摆一条 queued 任务（**冻结也要做**，否则结算时会扣一笔没冻过的钱）
#    → 然后什么都不发，几秒后 GET /tasks/{id} 应该已经是 succeeded
# 5. 过期兜底：TASK_TIMEOUT_SEC=1 重启，摆一条 **pending** 任务
#    （pending 是入队那步挂了的形状，claim_next 不捞它，只有超时能救）
#    → 期望 expired + error_code=TASK_TIMEOUT + settled_amount 是 **null 不是 0**
```

⚠️ `PROVIDER=fake` 下**造不出** `queued` 任务（提交即完成，闸门立刻释放），
所以前 4 步必须手工摆数据。~~要端到端看排队，得等 B7 的真 provider ——~~
✅ **B7 收掉了，而且是绕开的**：真排队不需要真 provider，需要的是
**能被推着走的时钟**（`worker.run_once(session, now=…)` 直接把 10 秒的轮询
窗口迈过去）+ 一个「先回执、后完成」的替身（`ScriptedProvider`）。
于是它从「手工摆数据」变成了**每次跑 pytest 都在走**的一条剧本，
见 `tests/test_acceptance_b7.py`。
⚠️ 这行原来那句「等 B7 的真 provider」是个**假承诺** —— 真 provider 至今
没接上（凭据有意留到最后），而排队早就验掉了。凡是「等接上真 X 就能验」
的句子，先问一句：**验它真的需要那个 X 吗？**

### B4 `b4-bytes`

**交付**：`storage.py`（Protocol + `LocalStorage`）、**新增** `transcode.py`
（Pillow 探针 / ffprobe / ffmpeg 抽帧 / 占位封面）、**新增** `transfer.py`
（`file://` 与 `http(s)::` 取件 + 魔数校验 + 转存流水线）、
`generation.finish_succeeded` 加转存段（**同步路径与 worker 路径的失败
处置不同**）、`worker` 加 ②.5「重试转存」相位、`assets` 上传真落盘 /
删资产真删文件、`fake` 产真字节。**不动数据库结构**，所以**没有新迁移**。

**判据**：`/media/<key>` 真的取得到字节；产物资产带真实 `size_bytes`
与宽高；上传的参考图落盘；转存失败的处置符合 §9.3 与已冻结的 §3.6。
**响应形状一个字段都没变。**

#### ⚠️ 四条口径，别「顺手改成整齐的样子」

1. **同步路径上转存失败 = 终态失败（502 `PROVIDER_ERROR`），不是「留在
   `submitted` 等重试」。** 理由是 `TEST_MODE=1` 的实例**根本不启动
   worker**（`main.py`），而那正是跨仓门禁的配置 —— 留在 `submitted`
   等于让用户**永远**等一条不会有人推进的任务。这条有**两条**守卫：
   一条不可重试的失败，一条**可重试**的失败（后者才真的测到 `sync`
   这个开关；前者的半个条件 B4 之前就存在）。
2. **上传是「宽松校验」。** 只硬查 ≤20MB；解得出尺寸就校验 ≤4096×4096，
   **解不出也照收**（宽高 `null`）。这是**用户拍板**的口径，理由写在
   `test_uploads_b4.py::test_非图片字节也照收`：冻结前端的契约测试传的
   参考图就是 `List<int>.filled(1024, 0)`（1024 个 NUL）。严格校验会让
   跨仓门禁因为**夹具**变红。
   ⚠️ 但「解不出」**不许**吞掉炸弹：68 字节、声称 6 万×6 万像素的 PNG
   必须报 `IMAGE_TOO_LARGE`（两条不同的代码路径各有一个样本钉着）。
3. **`assets.width/height` 用探针探出来的真值，`duration_sec` 用
   `task.output_duration_sec`。** 看着不一致，其实是两条不同的理由：
   尺寸探出来正好等于契约值（1024×1024 / 1280×720），而时长按文件算是
   **另一个数**（编码器时间基），换成它会让 B2 那条 `duration_sec == 6`
   因为一个与契约无关的原因变红。见 `_create_assets_for` 的说明。
4. **转存成功后清空 `provider_url`。** 它只活 1 小时，是搬运用的中转，
   不是资产真相；留着只会在下一次有人读它时给出一个失效的地址。
   （它**也**永远不进响应 —— 有一条 `FORBIDDEN` 扫描盯着。）

#### 本批新加的一处守卫：**桶里的 68 字节炸弹**

`_helpers.mini_png()` 造的是「结构完整（IHDR + 假 IDAT + IEND）、
数据是假的」PNG。只给 IHDR 的话 Pillow 会当成**截断**文件、报
`undecodable` —— 那样它就走「解不出也照收」那条宽松路径了，测不到
`too_large`。多两个块才让 Pillow 认为这是「读得出尺寸、只是数据坏了」。
两个样本（5000×5000 / 60000×60000）分别走「边长比较」和 Pillow 的
炸弹保护，删掉任一条都会红。

#### 真进程手工验收（§9.1，已跑过）

```
注册 → 传参考图 → 出图（同步）→ 转视频（带 source_asset_id）→ 取 public_url 的字节
```

期望与实测（2026-10-14，真 uvicorn + 真 TCP + 真 `media_root`）：

| 看点 | 实测 |
|---|---|
| 参考图落盘 | `media/u/1/1/ref.png`，与请求里的字节**逐字一致** |
| 出图 | PNG，5339 字节，1024×1024 |
| 视频 | MP4，3298 字节，ffprobe 读出 1280×720 / 6.0s |
| 封面 | JPEG，**正好 1280×720**（契约值） |
| `GET /media/<key>` | 200，同样的字节，且带 `X-Content-Type-Options: nosniff` |
| 响应里 | 没有 `provider_url` / `storage_key` / `params_json` / `available` |
| 余额 | 50 → 46 → 22（§15.1 的 46 / 22 逐字对上） |

⚠️ 这次用的是**默认** `MEDIA_ROOT`（`backend/media/`）。跑完记得把库和
两个存储目录清回原样（dev 库里原样是 **0 用户**），否则下一批的人会怀疑
「这个 `b4验收…` 用户是哪来的」。

### B5 `b5-compliance`

**交付**：**新增** `services/moderation.py`（provider 码表 + `screen_input` +
词表归一化）、`services/provider_audit.py`（事务外 best-effort 冲刷 + 脱敏）、
`services/marking.py`（标识内容与策略）、`transcode.py` 加四个写入器/读取器
（`write_image_marker` / `remux_with_tags` / `probe_video_tags` /
`read_implicit_marker`）、`fake.py` 加两个失败触发词、
**新增** `scripts/create_invite.py`。**不动数据库结构，没有新迁移。**

**判据**：违规提示词 → 422 且**一个数字都不动**；产物从 `public_url` 取回来
读得到标识；被回滚掉的那次 provider 调用在 `provider_calls` 里留得下。
**响应形状一个字段都没变。**

#### ⚠️ 本批最容易被下一个人「顺手改整齐」的四件事

1. **`create_invite.py` 是补出来的运维缺口，不是可选项。** 在此之前
   `scripts/` 里只有 `check_deps.py`，于是**一个非 TEST_MODE 的新库连一个用户
   都注册不出来**（§6.2 记了很久）。B7 的真进程验收也依赖它。已端到端验证过：
   种码 → 真注册 201 → `used_count` 0/5 → 1/5 → 停用 → 注册 400。
   ⚠️ 它**没有** `created_by`（`invite_codes.created_by` 是循环外键，
   CLI 里没有操作者）—— 这是有意的，别「顺手」塞一个 1 进去。
2. **`50511` 判 `rejected` + 不可重试是对 §9 的偏离**，理由与改法见
   README「B5 定的几件事」。有一条测试专门钉住这个偏离**本身**，
   所以它不是「没人注意到的笔误」。
3. **`provider_calls` 的审计行是事务外写的。** 看着像「没跟业务事务对齐」，
   其实是这张表唯一有意义的写法。同事务插 = 被回滚的那次调用恰好不留痕。
4. **标识写入的钩子在 `transfer.transfer_artifact` 里（`_sniff` 之后、
   `put_file` 之前），不在 `generation` 里。** 换到别处的话，
   `size_bytes` 记的会是**标记前**的大小 —— 而库里那个数从此和桶里的对象
   差几百字节，且没有任何东西会响。上传路径**结构上**不经过这里，
   所以参考图天然不带标识（有一个守卫测试钉着这一点）。

#### 本批的验证手段：**把「没碰过」变成可证明的**

B5 的核心声明是「标记不改内容」。这件事没办法靠断言写下来说服人，所以加了
三个**仅测试与验收用**的辅助函数（都在 `transcode.py`，因为 Pillow 与 ffmpeg
只在那一个文件里被调用）：

| 函数 | 它证什么 |
|---|---|
| `image_digest(path)` | 解码后 RGB 像素的 sha256 —— 标记前后**逐像素相同** |
| `video_stream_digest(path)` | `-map 0:v:0 -c copy -f md5` —— 只改容器元数据时**码流哈希不变** |
| `encode_webp(...)` | 让 WebP 那条标记路径**可达**（今天没有任何生产路径产 WebP） |

`video_stream_digest` 比逐帧比较更强：`-c copy` 之后它必须是**同一串字节**。

#### 真进程手工验收（部分已跑过）

- `create_invite.py` 的完整闭环（种码 → 注册 → 用量 → 停用）**已跑过**，
  见上面第 1 条。
- ~~⚠️ **「取回 `public_url` 读得到标识」这一条只在测试进程里验过**，
  还没在真 uvicorn + 真磁盘上手工走过一遍 —— B7 的真进程验收里会补。~~
  ✅ **B7 已补**：真 uvicorn + 真磁盘取回 `public_url` 的字节，图片读出
  `ImageDescription` 与 XMP、视频读出 MP4 tag，**重启进程后同一个地址仍然读得出**。
  见下面 `### B7` 的验收记录。

---

### B6 `b6-providers`

**交付**（**不动数据库结构，没有新迁移**）：

| 文件 | 是什么 |
|---|---|
| `providers/pricing.py` | **新增**。冻结/结算算式**唯一的一份实现**，fake 与 jimeng 都转手给它 |
| `providers/jimeng.py` | **新增**。两段式适配层（提交 / 查询）、状态机、审核码路由、句柄编解码 |
| `providers/jimeng_sign.py` | **新增**。Volcengine 签名 V4。文件头写明**未经真实网关验证** |
| `services/storage.py` | 加 `S3Storage`；`build_storage()` 的 oss 分支从 `NotImplementedError` 变成真实现 |
| `services/generation.py` | `_create_assets_for` 改走 Storage 实例的 `url_for`；`source_url` 打通到 worker |
| `worker.py` | 搬运的 IO **挪到事务外**（`defer_io=True`，见 §3.16） |
| `config.py` · `requirements.txt` · `.env.example` | `req_key` / S3 两组配置；`boto3==1.35.90` |
| `scripts/check_deps.py` | 15 → **18** 项（boto3 真往返、OSS 缺配置、即梦缺 req_key） |
| `tests/test_{jimeng,storage,pricing,txn_boundary}_b6.py` | 60 条新用例 |

**判据**：`check_deps` 18/18；后端 333 条全绿；跨仓门禁 162 条全绿
（live 24 条）；每一条守卫都**故意改坏跑过一遍**并确认变红（见下面那张表）。

#### ⚠️ 本批最容易被下一个人「顺手改整齐」的六件事

1. **`url_for` 给的是永久地址，不是预签名。** 看着「预签名更安全」，
   但 `public_url` 在契约里是**永久**的：预签名会过期，表现是
   「昨天生成的作品今天全裂了」，而且**只在时间过去之后**才出错 ——
   本地怎么测都是好的。判据写成了「**同一个 key 调两次要一模一样**」，
   卡在预签名的定义性特征（带时间）上。见 §3.14。
2. **搬运的 IO 挪到事务外，但只挪了 worker 那一条路。** 同步路径的 IO
   **仍然在事务里**，那是故意的：`test_transfer_b4.py` 那条「整笔不留痕」
   靠的正是回滚。一刀切会让「被拒的提交」变成 200 + 一条永远 `submitted`
   的任务（`TEST_MODE=1` 下不起 worker，而跨仓门禁正是这个配置）。见 §3.16。
3. **`perform_transfer` 的签名里连 `Session` 都没有** —— 有一条
   `inspect.signature` 守卫钉着它，不是洁癖：只要它能拿到会话，
   「在事务里做 IO」就会在某次重构里悄悄长回来。
4. **`req_key` 编在 `provider_task_id` 里，不是记在 provider 实例的字典里。**
   后者是「任务状态放在进程内存里」的一种形式 —— 重启即丢，而丢了的表现是
   所有在途任务的查询都拿不到正确的 `req_key`。见 §3.15。
5. **计费算式只能在 `pricing.py` 里有一份。** 两个 provider 各写一遍的后果不是
   「算式错了」，而是**分岔之后两边测试都还是绿的**。有一条 `ast` 守卫数
   `JimengProvider` 那两个方法体里的语句数（必须只剩一句 `return`）。
6. **`50511` 判 `rejected` + 不可重试**（B5 定的）、**标志位默认开**、
   **`create_invite.py` 不带 `created_by`** —— B6 一条都没改，别在这里顺手改。

#### 合成上游能证什么、不能证什么（**这条要一直挂着**）

即梦那 33 条用例跑的是 `httpx.MockTransport` —— **协议是我们自己编的**：

- **能证**：信封解析顺序（先 `code` 后 `data.status`）、状态机、
  码 → 处置映射、重试分类、产物地址/时长提取、请求体带没带 `req_key`/prompt、
  `Authorization` 以 `HMAC-SHA256` 开头且**不含密钥明文**、缺配置启动即失败。
- **不能证**：签名能不能过火山网关、请求 JSON 的字段名对不对、
  `req_key` / 模型 id 对不对、产物字段名对不对、这个子账号开通了没有。

存储那 18 条不一样：**boto3 全程是真的**（真序列化、真 SigV4 签名、
真拼地址），只有发出去那一步被 `before-send.s3.*` 截下来。所以
「put/get/head/delete 真的走通」「路径风格下桶名在路径第一段」是真的验过。
**仍然不能证**：真桶接不接受这个桶名/区域/权限。

#### 本批的验证手段：**六条守卫，逐条改坏 → 确认变红 → 还原**

（改坏脚本是一次性的，跑完已删 —— 留在库里会有人拿它当「可以改坏代码」的许可。
下面这张表本身就是那条脚本的替代品：**改什么、该红哪条**。）

| 改坏成 | 变红的 |
|---|---|
| `url_for` 后面拼 `?X-Amz-Date=...&X-Amz-Signature=...` | `test_storage_b6.py` 里那三条（往返不变、两次调用相同、无 `X-Amz-*`）|
| `_create_assets_for` 改回**模块级** `public_url_for` | 那条 CDN 端到端（`public_url` 里出现了 `/media/`）|
| 信封先看 `data.status` 再看 `code` | `test_非成功码即使带着_status_done_也算失败`（`DID NOT RAISE ProviderFailure`）|
| OSS 缺桶名也放行 | `check_deps.py` → `❌ 2/18`，红的正是新加的那两项 |
| `PROVIDER=jimeng` 缺 `req_key` 也放行 | 同上 |
| `exists` 吞掉所有 `ClientError` | `DID NOT RAISE ClientError`（403/500 会被读成「文件不在」）|

⚠️ 跨仓那两条哨兵（`__BLOCKED__` / `__FAIL__`）也改坏验过一次：
把 dart 里那两个字符串**同时**改掉 → 两条新 live 用例当场红
（「这次请求本该失败（期待一个 AppException），但它成功了」）→ 还原 → 24 条绿。
**这就是那两条用例真的走进去了的证据**，而不是「碰巧也返回了 422」。

#### §2.6 真凭据验收清单（**填完 AK/SK 与桶名照着走**）

⚠️ **原文写的是「这一整节今天一条都没跑过」—— 那是 B6 当时的状态。**
2026-10-15/16 起 ①② 已经跑过，③ 只跑通了**文生图那一半**，
④ 现在**四项全过**（写 / 读回 / 删 / 匿名 GET），
下面**四件事**就是跑出来的（**第四件事是 2026-10-16 新加的**）。
**每条的状态见括号里的标注。** 下面每一条都是「照着做，不通就照着改」，
不需要再读代码：

```bash
cd /g/AIVideo/backend
# ① 先把 .env.example 里那两组填上（key 名照抄，值从控制台抄）
#    JIMENG_AK / JIMENG_SK / JIMENG_REQ_KEY_IMAGE / JIMENG_REQ_KEY_VIDEO
#    S3_ENDPOINT_URL / S3_BUCKET / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY /
#    S3_PUBLIC_BASE_URL / S3_FORCE_PATH_STYLE
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/check_deps.py   # 期望 18/18
#    ✅ 已过（真凭据在场时 18/18）—— 见下面第一件事

# ② 先只验签名与信封，不花钱：把 req_key 随便填一个，然后
#    PROVIDER=jimeng 起一次 uvicorn，发一条文生图。
#    · 回 "不支持的 req_key" → 签名**是对的**（网关认了请求，只是能力没开）
#      → 去控制台把真的 req_key 抄回来
#    · 回 "签名错误 / InvalidCredential" → 签名实现有问题，
#      对 `jimeng_sign.py` 的文件头（那里写了每一步的来源与猜测）
#    · 回 404 / 域名解析失败 → JIMENG_HOST / REGION 写错了
#    ✅ 已过，而且**这一步的失败信息不够用**：`InvalidAuthorization` 有四种成因
#       长得一模一样，见第三件事 ① 的那张减法表 —— 拿一把已知有效的凭据当对照组
#       是最快的一刀

# ③ 能力开好之后，走一遍 §15.1 的剧本（文生图 → 图生视频），
#    盯三件事：
#    · 产物字段名 —— 若 poll 一直没结果，看 provider_calls 里的
#      resp_message（脱敏后的原文），字段名就在里面
#    · 参考图公网可达 —— image_urls 里那个地址必须在**外网**打得开
#      （所以 PUBLIC_BASE_URL 不能是 localhost，要有域名或隧道）
#    · 时长偏差 —— 真值决定 DURATION_SLACK_SEC 该不该改（§18-2）
#      和「退回差额」有多少
#    ◐ **文生图那半跑过了**（2026-10-15），而且第一条子项已经改口径：
#      真病因不是「字段名不对」而是**「它可能根本不是一个地址」**，
#      见第三件事 ④
#    ✅ **2026-10-16：文生图整条从前端界面跑通了** —— 见第四件事 ①
#      ⚠️ 但「盯三件事」**只关掉了一件**：产物字段名 ✅（第三件事 ④）；
#        参考图公网可达 ◐（地址那一侧够了，即梦究竟取没取到**没验**，见第四件事 ④）；
#        时长偏差 ❌（要一条**真视频**，所以它一直在等图生视频）
#    ❌ 图生视频那半一步都没成，**但卡点已经从「我们的代码」移到了
#      「账号里那个产品的并发配额」** —— 见第四件事 ②

# ④ 换 STORAGE=oss 再走一遍，确认 public_url 在浏览器里打得开、
#    且**不带任何 X-Amz-* 查询参数**（带了就是预签名混进来了）
#
#    在此之前先跑这个（**不花钱、不碰用户数据**，只是写一个几十字节的
#    探针文件、读回、匿名 GET、删掉）：
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/check_storage.py
#    ✅ 写 / 读回逐字节一致 / 删 / **匿名 GET 200** 全过（桶现在是匿名可读），
#       `public_url` 也真的在浏览器里打得开了 —— **但补了一条 CORS 规则才成**：
#       匿名可读**不足以**让 Flutter web 显示图片。见第四件事 ③
```

##### ⚠️ 走这份清单撞到的第一件事：闸门自己会红五条（2026-10-15 实测，已修）

`①` 期望的是 18/18，而**把 `.env` 填好之后第一次跑，出来的是 13/18**：

```
❌ 5/18 项没过：
   · pydantic-settings: 默认必须是离线可跑的 fake
   · provider 必填:     配了 jimeng 却没给密钥，居然构造成功了
   · httpx:             /health 回的 provider 是 jimeng
   · oss 配置必填:      配了 oss 却没给桶名，居然构造成功了
   · req_key 必填:      配了 jimeng 却没给 req_key，居然构造成功了
```

**这五条全是假红，洞在闸门自己身上，不在应用上。** 根因一句话：
`Settings` 的取值顺序是「init 参数 > 环境变量 > `.env`」，而那几条反证
只往 init 里塞了一个字段（`Settings(provider="jimeng")`），**把 `.env` 留着**——
于是 `jimeng_ak` 照样从 `.env` 读到真值，「这个人忘了配密钥」根本模拟不出来。
`.env` 还是空的时候它们全绿，是因为**恰好没有东西可漏**。

三件事值得记住：

1. **失败信息读起来像安全漏洞**（「配了 jimeng 却没给密钥，居然构造成功了」），
   而实际上四道防线都在 —— 单独验过：关掉 `.env` 再问一次，
   `jimeng 缺 AK/SK` / `jimeng 缺 req_key` / `oss 缺桶名` / `缺 JWT_SECRET`
   四条**全部照常起不来**。别照着这种信息去改 `config.py`。
2. **最坏的时机**：闸门唯一真正该跑的时刻，就是**配好凭据的那台机器**。
   一个只在零配置机器上绿的闸门，等于没有。
3. **同一处还藏着第二个洞**：`httpx` 那一项会 `create_app()`，而它会
   按配置**真的起一个后台 worker 线程**。以前 provider 恒为 fake 所以无害；
   配成 jimeng 之后，那条线程会**真的花钱**（它会把库里 `queued` 的任务
   出队交给真网关）—— 一个本该只读的依赖闸门，顺手把钱发出去了。
   修法是在构造 app 前后把 `WORKER_ENABLED=0` 临时打开并清一次
   `get_settings` 的 lru_cache。

修完（`b7.1-gate-env-isolation`）之后的判据是：**真凭据在场时 18/18**。
反证本身也重新验过一遍「真的会红」—— 四种改坏各红一条：

| 改坏 | 应变红 |
|---|---|
| 拿掉 `config.py` 里「配了 jimeng 必须有 AK/SK」 | `provider 必填` |
| 拿掉「配了 jimeng 必须有 req_key」 | `req_key 必填` |
| 拿掉「配了 oss 必须有桶名」 | `oss 配置必填` |
| 把 `_env_file=None` 从反证里拿掉（= 退回修之前的写法） | `provider 必填` 重新红 |

最后一条是这次的**承重证明**：它说明那个修法不是装饰，拿掉就退回假红。

##### ⚠️ 撞到的第二件事：真桶验出来三条，其中一条**推翻了我们自己的文档**

对着 TOS 真桶打（`scripts/check_storage.py`，2026-10-15）：

**① `S3_FORCE_PATH_STYLE` 的那个「关」，原本在真桶上是空的。**

对着同一件事打三种寻址风格，把**实际发出去的 URL** 打出来看：

| `addressing_style` | 实际请求 | 结果 |
|---|---|---|
| `auto`（= 代码里 `False` 时映射的那个） | `PUT {endpoint}/heluo/_probe/x.txt` **路径风格** | ❌ `InvalidPathAccess` |
| `virtual` | `PUT heluo.{endpoint}/_probe/x.txt` | ✅ 写、删都通 |
| `path` | 同 `auto` | ❌ `InvalidPathAccess` |

也就是说 `S3_FORCE_PATH_STYLE=0` **并没有**给出虚拟主机风格，而 botocore 的
`auto` 在自定义 endpoint 下自己选了路径风格 —— 这个布尔是个**假二分**：
名字上只有两种取值，行为上有三种，而第三种恰好等于第一种。
`.env.example` 里那句「代码默认 0 = 交给 boto3 自己判」是**错的**，
已改成明确的 `virtual`。

⚠️ 顺带纠正另一条**没验过就写下的**猜测：原文说「选错的表现是 DNS 解析失败」。
那只对**一个方向**成立：

- 该 virtual 却给了 path → `InvalidPathAccess: Forbidden path to access server`
  （TOS 实测；**没有一个字**提到寻址风格）
- 该 path 却给了 virtual → 才是那个只有桶名的 DNS 解析失败

**② 桶能读写，但还不是公共读。** 匿名 GET 那个 `url_for` 拼出来的地址
回的是 `403 AccessDenied`（**不是** `NoSuchKey` —— 对象确实在，是权限拒的）。
这是 `url_for` 永久地址那条设计的**前提**，不是可选优化：桶不公共读的话，
所有作品点开都是 403，而生成、扣费、落库**全都正常**。
解法二选一：把桶设成公共读，或者挂一个带自己鉴权的 CDN。

**③ `S3_PUBLIC_BASE_URL` 填的形状是对的。** 唯一没验的是「外网真能打开」，
而它被 ② 挡住了 —— 所以**别把「地址形状对」读成「地址能用」**。

##### 一条小教训（值得单独记）

`tests/test_storage_b6.py` 里那条断言 `addressing_style == "auto"` 的用例，
是**照着实现抄的**，不是照着事实写的 —— 于是它和实现一起错了整整一批，
全程绿。凡是断言**我们自己挑的一个字符串常量**的地方，都要问一句：
这个字符串在真东西上验过吗？验不了的，就在注释里标明「未验」。

##### ⚠️ 撞到的第三件事：真即梦打了一枪，文生图栽在「它不给地址，给字节」

2026-10-15，项目所有者授权跑**一次**真文生图（`b7.3-inline-artifact`）。
结果是一条**完整的因果链**，值得整段记下来 —— 因为其中前两步都会把人引向
错的方向，而真正的病因在第四步。

**① `InvalidAuthorization` 有四种成因，长得一模一样。**
第一枪回的是 `400` + `InvalidAuthorization`。它同一个错误码可以是：
签名实现写错 / AK 形状不对 / `req_key` 不对 / 这个能力没开通。
**这四件事的修法完全不同，而错误信息一个字都不区分。** 分开它们靠的是
「逐条做减法」，其中**最省时间的一刀是拿一把已知有效的凭据当对照组**：

| 试探 | 网关的回答 | 排除掉什么 |
|---|---|---|
| 拿**火山官方 SDK** 的 `SignerV4` 对同一个请求算一遍 | 与我们的签名**逐字节相同**（`82719ea1d008ecdfa074dd76…`）| 「我们签错了」——整个假设空间 |
| 故意把签名改成一串垃圾 | 与真签名**同样的错** | 「网关会比签名」——它压根没比 |
| 一把**形状合法但不存在**的 AK（`AKLT` + 32 个 `0`）| `401 InvalidAccessKey` | 「凭据格式能不能解析」这一关**能过** |
| `.env` 里那对（60 位 base64 味 + 158 位 base64url）| `400 InvalidAuthorization` | **格式解析这一关就没过** |
| 同一份 `.env` 里的 **TOS 那把**（47 位 `AKLT`）| 业务信封 `50200 req_key not supported` | 凭据**已经过了**，问题在 `req_key` |

⚠️ 最后两行放在一起就是结论：**`.env` 里填的那对根本不是火山 IAM 凭据**
（IAM 的形状是 `AKLT` + 43 位 = 47 字符，SK 60 字符）。今天 `.env` 里
`JIMENG_AK/SK` 与 `S3_ACCESS_KEY_ID/SECRET` 是**同一份值** —— 那是**有意借的**，
不是一个好设计，见 §8.2 第 10 条。

⚠️ **另一个教训（这条是花钱买的）**：探针脚本里我写过一句
「这个请求没有 prompt，**结构上不可能真的提交一个生成任务**」——
**错**。网关照单全收，回了一个真 `task_id`，于是**即梦那边多了一条我们
没有跟踪的任务**。凡是往**计费接口**发的请求，先假设它会成功。

**② 两个 `req_key` 都是真的，§18-2 那一格在文生图这侧已经有答案。**
`jimeng_t2i_v31` 回 `10000` + 真 `task_id`；另一个候选
（`pippit_iv2v_v20_cvtob_with_vinput`）回 `50430 Request Has Reached API
Concurrent Limit` —— **那是并发撞车，不是「不支持这个 req_key」**，
说明它同样被网关认了。所以 §8.2 第 8 条从「两个都要去控制台抄一遍」
缩小成「图生视频那一条只差一次真的跑」。

**③ `Host` 原先不在待签头集合里。** `jimeng_sign.py` 把 `host` 收成了参数
却忘了并进 `signed_headers_in` —— 于是我们算的规范请求比网关重算的少一个头。
**修了，但真网关的回答一个字没变**（因为病因是第 ① 条）。
仍然要留着这个修法：它是规范偏离，且现在有测试钉着
（改坏 → `test_签名里必须带上_host` 变红）。

**④ 真正的病因：`jimeng_t2i_v31` 不给产物地址，把字节内联在响应体里。**
任务在即梦那边**成功**了，`data` 原文是：

```json
{"status": "done",
 "image_urls": null,                              ← URL_LIST_KEYS 找这里，是 null
 "video_url": "",                                 ← URL_KEYS 找这里，是空串
 "binary_data_base64": ["/9j/4AAQSkZJRgABAQ…"],   ← 161672 字符 → 121252 字节的真 JPEG
 "resp_data": "{\"PreviewImage_121\": [\"uri://binary_data?index=0\"],
                \"comfyui_cost\": 6.6782}",
 "aigc_meta_tagged": false}
```

而 B6 的 `poll` **只找地址**，找不到就判 `failed` + 全额退款 ——
**即梦真的生成并计了一次费，我们这边一张图都没留下**。
修法（`app/providers/jimeng.py`）：

- 拿不到地址时走 `_materialize_inline`：解 base64 → 原子写进
  `provider_spool_root/jimeng/<即梦 task_id>.bin` → 回一个 `file://` 地址。
- **为什么落文件、而不是给 `ProviderResult` 加一个字节字段**：产物要**跨进程
  活得下去**（转存在 `defer_io` 之后做，可能发生在重启之后，而 worker 的补转存
  扫的正是库里的 `tasks.provider_url`）。加字节字段就要加一列 + 一次迁移 +
  每一行变胖。落 spool 则是 `fake` **已经在用**的那条路，于是转存层的
  `_local_path_for_file_url` 包含性检查是**被使用**，不是被放宽 ——
  **没有新的信任边界**。
- 下标从 `resp_data` 的 `uri://binary_data?index=N` 里读（今天就是 0，
  但取第 0 个在「它指认第 1 个」的那天会**静默交付错的那张图**）。
- 上限**在解码前后各判一次**：base64 是 4:3 展开的，只判解码后的长度的话，
  一个远超 200MB 的字符串会先被完整解进内存、再被判死刑。

⚠️ 顺带纠正一句 B6 文档里的说法：那里写「产物字段名是猜的，若 poll 一直
没结果就看 `provider_calls` 里的 `resp_message`」。**这次证明猜错的方式不是
「字段名不对」而是「它可能根本不是一个地址」** —— 换任何键名都修不了，
漏掉的是那个**前提**。

**⑤ `50430` 补进了审核码表**（`app/services/moderation.py`）。
它是**并发上限**（这个子账号的 CV 并发是 1），与 `50429`（QPS 限流）
不是同一个数，而文档那张表里只有后者的岗。处置相同（等一下就好）——
所以这一条**不改变行为**，只让 `resp_code` 里的 `50430` 在**对账表里可辨**。

**⑥ 顺带修掉一个真缺陷：`>= 400` 的响应体没有被记录。**
第一次打真网关，四次提交全回 `HTTP 400`，`provider_calls` 记了四行 ——
一切「正常」，除了**我们不知道它在抱怨什么**：四行的 `resp_message` 全是 `NULL`，
因为那条分支只记了状态码、正文压根没读。也就是说**对方明确告诉我们病因的
那一类响应，恰恰是唯一不记录的一类**。已修（`_with_body`）：认
`{"code","message"}` 与网关的 `{"ResponseMetadata":{"Error":{...}}}`
两种信封，都不是就原样留一段文本。⚠️ 它只进 `provider_calls`
（落库前还会被 `sanitize_message` 剥 URL + 截断），**不进用户的响应体**。

###### 这一批的守卫（改坏 → 确认变红 → 还原，逐字对过文件）

| 改坏 | 变红几条 | 是哪一条 |
|---|---|---|
| `_inline_payload` 无视 `resp_data` 的下标、恒取第 0 个 | 1 | `test_resp_data_指认的那个下标才算数` |
| 拆掉解码前后的两道 `max_artifact_bytes` 闸门 | 1 | `test_内联产物超过上限就不落盘` |
| 把 `host` 从 `signed_headers_in` 里拿掉 | 1 | `test_签名里必须带上_host` |
| 拿掉 `_with_body`（4xx 正文不记了） | 4 | `test_jimeng_b6.py` 里那四条 |

###### 判据

`check_deps` 18/18；后端 **351** 条全绿（B6 时 333 → 这次 +7 条内联用例、
+1 条 `host` 用例，中间那批 339→344 是别的批次加的）；
**真响应**上验过一遍完整的交付链（不花钱）：

```
provider_url      = file:///…/spool/jimeng/realgw.bin    ← 落盘
转存层的包含性检查 = 放行                                  ← _local_path_for_file_url
字节数            = 121252（与网关给的那份逐字节相同）
_sniff            = ('image/jpeg', '.jpg')
```

⚠️ **仍未验**（当时）：真跑一条**穿过 app 的 HTTP 接口**、落到真桶、匿名打得开的
完整交付。上面那一步是从网关响应直接进了 provider 的交付链，
**没有经过** worker → 转存 → S3 → 标识写入那一段的**真**外部验证
（那一段有 `fake` + 本地 spool 的自动化覆盖，但没在真桶上跑过）。
→ ✅ **2026-10-16 补上了**，就是下面的第四件事 ①。

##### ⚠️ 撞到的第四件事：真跑两条链 —— 文生图整条通到前端界面，图生视频一步没成（2026-10-16）

这一轮的目标不是「再验一遍后端」，是**用浏览器当用户走完一遍**：
真 uvicorn（`PROVIDER=jimeng` + `STORAGE=oss`）+ `flutter run -d chrome`
（`USE_MOCK=false`）+ 一个用 CDP 驱动的无头浏览器点真实操作。
结果一好一坏，而**坏的那一条的病因不在这个仓库里**。

**① 文生图整条通了 —— 包括上一枪没走过的那一段。**

任务 14（用户 `b7verify`，用 `DEMO2026` 从**界面**注册，注册即 50 积分）：

| 环节 | 证据（全部来自真库，可复算） |
|---|---|
| 提交 | `provider_calls`：`submit` · HTTP 200 · `resp_code 10000` · 1 行 |
| 轮询 | `query` · HTTP 200 · `10000` · 2 行（真·两段式，不是「提交即完成」）|
| 记账 | 流水 `freeze 4`（余额 50→46、冻结 4）→ `settle 4`（冻结归 0、余额 46）|
| 转存 | `tasks.transfer_state='done'`，`provider_task_id='jimeng_t2i_v31\|11530402786048815474'` |
| 产物 | `assets` 一行：`t/14/out.jpg`、**139537 字节**、`image/jpeg`、`is_ai_generated=1` |
| 界面 | 作品页「已完成」里**看得见那张图**（AI 角标在），首页余额 46 |

⚠️ 这条链**一共成了三次**（任务 12 / 13 在 `tester01` 上、任务 14 在 `b7verify` 上，
流水都是 `freeze 4` → `settle 4`），所以它不是偶然。
**③ 那「盯三件事」现在的账**：产物字段名 ✅（第三件事 ④ 已答）、
参考图 ◐（地址那一侧够了，见下面 ④；**即梦到底取没取到没验**）、
**时长偏差 ❌ 仍然空着** —— 它要一条**真视频**，而真视频卡在 ② 那堵墙上。

**② 图生视频：15/16/17 回 `50430`，18 回 `50400`。这两个码不是一回事，
而分清它们就是这一轮的收获。**

四条任务、**16 次提交全被拒**、**四条全部全额退款**（每条 `freeze 32` →
`refund 32`，`frozen_after` 归 0，余额全程 46）。**失败路径的记账是对的 ——
这是这一轮虽然没成、但确实验到了的东西。** 四条 `error_code` 都是
`PROVIDER_ERROR`，意思是**即梦拒了，我们这侧没有异常**。

关键在**最后一条换了另一个 `req_key`**（一次对照实验，试完已改回 `.env` 原值）：

| 任务 | `req_key` | HTTP | `resp_code` | 原文 |
|---|---|---|---|---|
| 15 / 16 / 17 | `pippit_iv2v_v20_cvtob_with_vinput`（`.env` 里配的）| **429** | **`50430`** | `Request Has Reached API Concurrent Limit, Please Try Later` |
| 18 | `jimeng_i2v_first_v30`（第三方文档里推荐的那个）| **401** | **`50400`** | `Access Denied: Access Denied` |

**这两个码的分工就是排查图生视频的那把刀：**

- **`50400 Access Denied` = 开通/权限这一关没过。** 任务 18 用的偏偏是**文档里
  那个 `req_key`** —— 所以那份文档推荐的产品线**在这个账号上根本没开**。
  （这也是对第三件事 ① 那张减法表的补充：`InvalidAuthorization` 有四种成因，
  而**开通与否有一个自己的码，`50400`，不用去猜**。）
- **`50430` = 权限过了、撞在并发闸门上。** 同一个 `req_key` 被一致地回 `50430`
  而**不是** `50400`，形状上说明它**是被认的**、只是**这个能力自己的并发配额是 0**。

⚠️ **不确定性要照实标**：`50430` 也可能来自一个**网关级的限流器**、先于权限检查，
所以「`pippit_…` 就是图生视频的正确 `req_key`」这句**仍然只是更强的猜测**，
不是结论。**但它是目前能拿到的最强证据**，而且与项目所有者在控制台上看到的
那一屏**互相印证**：`已开通API列表` 里「智能生视频Agent-Seedance 2.0 fast
720p 有参考」的**并发是 0**、「即梦AI-图片生成」是 **1**
（后者恰好解释了文生图为什么一路顺）。

**所以现在的卡点是一个商业动作，不是一个代码改动**：把那个产品的**并发买到 ≥1**。
**在那之前别再试了** —— 每试一次就是一条失败任务 + 一次真网关调用
（钱没真花掉，失败全额退了，但 `provider_calls` 会一直涨，而这一轮已经涨了 16 行）。
要人等的那件事见 §8.2 第 11 条。

**③ 桶还缺一条 CORS 规则 —— 而它只有「用浏览器看」的时候才暴露。**

`check_storage.py` 在 2026-10-15 报的是**匿名 GET ❌ 403**；这一轮桶已经是
匿名可读（`curl` 拿得到 200），于是**后端这一侧每一条都正常**：
生成成功、`public_url` 永久、`GET /media` 200、对象就躺在桶里。
**而页面上那张图就是不出现**，只有一个加载占位。

病因不在桶的读权限，在**浏览器怎么读**：Flutter web（CanvasKit）的
`Image.network` 走 **XHR/fetch**、不是 `<img>` —— 所以「匿名可读」**不够**，
对象响应必须带 `Access-Control-Allow-Origin`。诊断入口是**应用自己的**
performance 表，不是后端的日志：

```js
performance.getEntriesByType('resource').filter(e => e.name.includes('heluo'))
// → { status: 0, transferSize: 0, initiatorType: 'xmlhttprequest' }   ← 坑的形状长这样
```

`status: 0` + `transferSize: 0` + `initiatorType: 'xmlhttprequest'` **三件同时出现**，
就是「浏览器把整个响应挡掉了」。修法是桶上 `put_bucket_cors`
（**纯新增**，`delete_bucket_cors` 即回退；原来的状态是 `NoSuchCORSConfiguration`）：

```
AllowedOrigins ['*'] · AllowedMethods ['GET','HEAD'] · AllowedHeaders ['*']
ExposeHeaders [ETag, Content-Length, Content-Range, Content-Type] · MaxAgeSeconds 3600
```

⚠️ 三点记住：**① 边缘节点是渐进生效的**（同一个 URL 连打几次，
`ACAO` 一会儿有一会儿没有，几分钟后才稳定 —— 「刚配完还是 `None`」别急着当失败）；
**② 放通 `*` 不额外暴露任何东西**（对象本来就是匿名可读的）；
**③ 顺序**：先看应用 performance 里那条 `status`，再看对象的 `ACAO` ——
反过来会一直在后端和桶权限上绕圈。

**④ 顺带一个方向性修正：`STORAGE=oss` 之下，「参考图公网可达」不需要域名。**

§6.2 的 B6 第 2 条、以及 §8.2 里记着「本项目决定用公网 IP + 端口，没有域名」。
**在 `STORAGE=oss` 之下那条路不用走了**：`source_url_for`
（[generation.py:278](G:/AIVideo/backend/app/services/generation.py#L278)）取的是
`Asset.public_url`，而 OSS 下它就是 `{S3_PUBLIC_BASE_URL}/{key}` —— 一个
**匿名打得开**的桶地址。也就是说「我们要有一个公网地址」这件事**已经满足**，
图生视频真正缺的那一环是**产品并发**（② 条）。

⚠️ 但**别把这条读成「参考图那件事验完了」**：`source_url` 只是**我们发出去的那个
字段**，**即梦到底能不能取到它，要等一次真提交过了闸门才知道**（这一轮四次提交
全死在闸门前面，所以那一格**仍然空着**）。而且这条**只对 `STORAGE=oss` 成立**；
`STORAGE=local` 下仍然需要隧道或公网 IP（那种配置下 `PUBLIC_BASE_URL` 根本没填，
`.env` 里它是注释掉的）。

###### 这一轮留下的操作事实（下一个会话要用）

| 项 | 值 |
|---|---|
| 测试账号 | 请用演示邀请码注册新测试账号。 |
| 后端进程 | `PROVIDER=jimeng` + `STORAGE=oss` 的 uvicorn 占着 `127.0.0.1:8000`（PID 328）。**是谁起的、谁就要负责关**，别让它一直挂在后台 |
| 前端进程 | `flutter run -d chrome --web-port 8080` 占着 `:8080`（PID 2716，真身是它拉起来的 `dartvm`）。⚠️ **它不随会话结束而退出**，而 8080 被占着的时候再按 F5 只会得到一个起不来的 App |
| 更早留下的孤儿 | `:8011`（PID 19672）与 `:8012`（PID 19528），**2026-10-13 那轮留下的 uvicorn，一直没关、也没人批准去关**。它们不占 8000，所以不挡事，但**它们连的是同一份 `aivideo.db`** |
| 怎么查/怎么关 | `Get-NetTCPConnection -LocalPort <n> -State Listen` 拿 PID → `Stop-Process -Id <pid>`。⚠️ 停后台任务（`TaskStop`）**只杀外层 shell**，`dartvm` / `uvicorn` 会活下来继续占端口 —— 上一次就是这么被绕进去的，得按 PID 杀 |
| 这一轮改过的外部状态 | 只有一处：桶 `heluo` 上**新增的 CORS 规则**（③ 写明了怎么回退）。`.env` 现在是**原值**（`JIMENG_REQ_KEY_VIDEO=pippit_iv2v_v20_cvtob_with_vinput`，已核对），任务 18 那次对照实验换的 `req_key` **已经换回去了** —— 怎么换的没留痕（进程环境变量或临时改文件都说得通），所以**别去 `.env` 里找 `jimeng_i2v_first_v30`，它不该在那儿** |

#### 真进程手工验收

**有（2026-10-15/16，`b7.3-inline-artifact`）** —— 就是上面那第三件事。
⚠️ 原文写的是「没有」，那是 B6 当时的状态；**别把它当成今天的状态**。

**2026-10-16 又来了一轮真进程验收** —— 就是上面的**第四件事**，
而且这一轮是**从浏览器界面**走的（真 uvicorn + `flutter run -d chrome` +
CDP 驱动），比上一轮更接近「用户真的在用」。结论：**文生图通、图生视频卡在账号侧**。

### B7 `b7-acceptance`

**交付**（**只加了一个测试文件，`app/` 一行没改**）：

| 文件 | 是什么 |
|---|---|
| `tests/test_acceptance_b7.py` | **新增**。§15.1 的那条剧本，六条用例共用**一份**剧本（`_run_15_1`）|

**判据**：后端 **339** 条全绿（333 → +6）；`check_deps` 18/18；跨仓门禁
**43** 条（24 live + 19 repository layer）；Mock 138。五条守卫逐条改坏验过
（见下）。**这一批没有动 `app/`，所以「改坏」全都是改 `app/` 里的东西
去证伪测试**，不是改测试去将就实现。

#### 这条剧本长什么样

```
注册（送 50）→ 文生图（冻 4、结 4）→ 从 /assets 挑那张图 → 图生视频
（冻 32、结 24、退 8）→ 余额 22、冻结 0
```

两条任务都不是在请求路径上完成的 —— **是 worker 一轮一轮推过去的**，
所以这条剧本同时是「跨时间」的。它跑的是 `ScriptedProvider`
（`tests/_providers.py`）：一个只改「什么时候算完」的替身，计价仍逐字
来自 `FakeProvider`，所以它算出来的账必须和前端那 138 条里写死的数一样。

#### 六条用例各守什么

1. **账**：流水逐笔对（freeze 32 / settle 24 / refund 8），**连快照一起对**。
2. **跨重启**：拿同一个 id 从**另一条连接**再取一次 —— 状态在库文件里，
   不在进程内存里；顺带钉住 `provider_url` 被清空、三个时间戳都在。
3. **字节与标识**：拿响应里那个 `public_url` 真取一次，再从**取回来的那份**
   里读回标识（图片 EXIF+XMP、视频 MP4、封面也有）。
4. **对账表**：`provider_calls` 里 submit 一次、query 至少两次 ——
   **「问了还没好」那几次必须被记下来**（一条真视频会问几十次，
   只记拿到结果的那次，对账表会显示「每条只问了一次」）。
5. **契约守卫**：这条剧本里出现过的所有响应里没有那四个键。
6. **剧本形状**：见下，它是唯一一条「守别的用例会不会静默失效」的。

#### ⚠️ 两条最容易「顺手改整齐」的地方

**（a）冻结那一行的 `balance_after` 是 46，不是 14。** 这是 §7.2 的设计：
`balance` 只有**结算**才动，冻结动的是 `frozen`，用户看到的可用是现算的
`balance − frozen`。实测的输出是：

```
freeze 32 | balance_after 46 | frozen_after 32    ← 可用 14
settle 24 | balance_after 22 | frozen_after 0
refund  8 | balance_after 22 | frozen_after 0     ← 余额不动，钱从冻结里回来
```

把 46 改成 14（也就是让冻结也扣余额）会**同时**和前端
`available = balance − frozen` 那句话对不上。

**（b）第 6 条用例守的是「剧本形状」，不是账。** 它存在的理由是**实测**出来的：
把 `ScriptedProvider.submit` 改回「直接给成品」（让它退化成 fake 的形状），
红的是**整个文件** —— 但红的理由是**剧本里那两句内联断言**
（`assert image_task["status"] == "submitted"`），不是前面五条各自的断言。
也就是说，这个文件对剧本形状的防护全押在那两三句话上，而它们是最容易
被「先容忍两种形状吧」放松掉的。第 6 条把形状单独钉一遍，并且钉到内联
断言**看不见**的粒度：两条任务各提交一次、各被问两次。

#### 本批的验证手段：**五条改坏，逐条确认变红**

| 改坏成 | 变红的 |
|---|---|
| `ScriptedProvider.submit` 直接返回成品（退化成 fake） | 整个文件 6 条 —— 但**理由**是剧本开头那两句内联断言（见上面 (b)） |
| 不记「问了还没好」那一次调用 | **只有**第 4 条（对账表）—— 最锋利的一条 |
| 转存成功后不清 `provider_url` | 第 2 条，报出来的正是那个 `file:///.../spool/generated/...png` |
| `settle_and_refund` 里不写退款那一段流水 | 第 1 条。⚠️ **同一条用例最后那句「余额 22 / 冻结 0」照样绿** —— 差额本来就靠 `frozen`/`balance` 体现，退款那行只是**账本**。所以只看余额的话，「用户被退了多少」在库里不可查 |
| 图片类产物不写隐式标识 | 第 3 条（图片与封面一起丢） |

改坏脚本是一次性的，跑完已删（同 B6 的理由）。

#### 真进程手工验收（**跑过了**，2026-10-14）

复用 B3 那套做法，但这次要的是一条完整剧本。关键是**不能用
`TEST_MODE=1`**（那个配置下 `/__test/*` 才存在，而生产的库里要的是
用 `create_invite.py` 种码 —— 那才是真部署的形状）：

```bash
cd /g/AIVideo/backend
# ① 一个**不是** TEST_MODE 的库
export DATABASE_URL="sqlite:///<tmp>/acc.db"
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m alembic upgrade head
# ② 种邀请码（B5 才有的脚本 —— 在这之前，新库连一个用户都注册不出来）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/create_invite.py \
    --code B7ACC --uses 0 --note "B7 acceptance"
# ③ 起真服务：TEST_MODE=0 + WORKER_ENABLED=1
DATABASE_URL=... TEST_MODE=0 WORKER_ENABLED=1 PROVIDER=fake STORAGE=local \
  MEDIA_ROOT=<tmp>/media PUBLIC_BASE_URL=http://127.0.0.1:8100 \
  .venv/Scripts/python.exe -m uvicorn app.main:app --port 8100
# ④ 一个**真 TCP 客户端**走完 §15.1，然后拿 public_url 取字节、读标识
```

验到的东西（逐条都有输出）：

- 启动横幅里 `测试接口 : 关`，且 `POST /__test/reset` 是 **404**
  —— 「关着的时候这些路径在路由表里根本不存在」这句话在真进程上也成立；
- `worker 启动（巡检间隔 2.0 秒）` 那行确实打了出来；
- 注册 **201**、余额 50 → 文生图 `succeeded`（1024×1024、6361 字节）
  → 图生视频 `succeeded`、结算 24 → **余额 22、冻结 0**；
- 流水 6 条，形状与 §15.1 逐字一致（含上面那个「冻结 46/32」的快照）；
- **三个资产的 `public_url` 都真取得到**（200、字节数与 `size_bytes` 一致），
  而且从**取回来的那份字节**里读得出标识：
  · 图片 → `AI-generated | AI Video Platform | task=1 | kind=text_to_image | 2026-…`
  · 视频 → `AI 生成（AI-generated） · AI Video Platform · task=2 · kind=image_to_video`
  · 封面 → 同图片那种（它也是 AI 生成的一帧）
- **重启之后再验一遍**：进程杀掉重起，用**重启前签发的** token
  取 `/tasks/2` → 仍是 `succeeded` / 24，`/me` → 22/0，`/assets` → 3 件，
  三个 `public_url` 仍然 200 且标识仍读得出。

⚠️ **这一节和 §2.6 那份清单的分别**：这一节跑的是 `fake` + `local` ——
它证明的是**我们这条链路自己走得通**（含真进程、真磁盘、真静态挂载、
真重启）。它**不证明**签名能过火山网关、也不证明真桶能读写。后者只有
§2.6 那份清单能做到 —— 而那份清单**从 2026-10-15 起开始跑了**
（② 已过、③ 只过了文生图那半、④ 只跑到「写/读回/删」，见 §2.6 里
每条后面的 ◐ 标注）。

⚠️ 还有一件真进程验收**没覆盖**的：`PROVIDER=fake` 时提交即完成，
所以那条剧本里的 worker 其实**没有事可做**（真排队那一段由第 2、4、6 条
用例在 pytest 里用注入时钟验）。要看真进程里的排队，得按 §2.4 那个
B3 剧本手摆一条 `queued` 任务，或者接上真 provider。

---

### B7.4 `b7.4-minimax-video`（**下文与别处简称 §2.7**）

**一句话**：图生视频整条从即梦换到 **MiniMax H3-Max**，文生图留在即梦不动。
**这是一次「换谁在跑」，不是「改产品」** —— 计费契约一个字没动，
前端 `lib/` 一个字没动。

**为什么做它**：上一节第四件事 ② —— 图生视频一步都没成，而卡点**不在这个
仓库里**（那个产品的并发配额是 0，要人或钱去解，§8.2 第 11 条）。
这一批换一条**不依赖那个配额**的通道，把「等商业动作」和「能不能出片」
解耦开。

#### 交付

| 文件 | 改动 |
|---|---|
| `app/providers/minimax.py` | **新增**。适配层（本批主体）。提交体是**多模态 `content` 数组**（不是即梦那种「一个 prompt + 一个 image_urls」）|
| `app/providers/__init__.py` | `build_provider(kind)`；`minimax` 分支。**见下「唯一一处偏离」** |
| `app/config.py` | `ProviderKind.minimax`、`video_provider`、4 个 `minimax_*` 字段；`model_post_init` 改成**按解析出来的两路各判一次** |
| `app/services/moderation.py` | `PROVIDER_CODE_MAP` → **`JIMENG_CODE_MAP`**（改名，行为不变）+ 两张 `MINIMAX_*` 表 + 两个函数加 `provider` / `http_status` 关键字参数 |
| `app/services/generation.py` | `:124` / `:346` 把作用域里**本来就有**的 `kind` 传下去 |
| `app/worker.py` | 三个相位各按 `task.kind` / 循环变量取 provider（`_provider_for`）|
| `app/providers/base.py` | 只改 `ProviderCallMeta.req_key` 的**注释**（从「即梦的能力路由键」改成「provider 侧决定单价的那个标识」）|
| `app/main.py` | `/health` **新增** `video_provider` 键（不改 `provider` 键）+ 启动横幅多打一行 |
| `tests/test_minimax.py` | **新增 49 条** |
| `tests/{conftest,test_transfer_b4,test_jimeng_b6,test_pricing_b6,test_moderation_b5}.py` | 跟着改：`lambda kind: provider`、`build_provider(TaskKind.text_to_image)`、计价参数表加 MiniMax、表名改名 |
| `.env.example` / `README.md` / 本文件 | 占位与说明 |

**前端 `lib/` 一个字符没改**，`flutter test` 仍 138 全绿。

#### ⚠️ 唯一一处偏离「切真 provider 时调用方一行不改」

那句话是 `providers/__init__.py` 文件头写的纪律，而**这一批把它破了一次**：
`build_provider()` 长出了 `kind` 形参。

理由一句话：**`worker` 的一个 tick 只造一个 provider**，然后
`for kind in TaskKind` 里用在所有类型上 —— 一个 provider 表达不了
「图片走一家、视频走另一家」。

**为什么不用一个 `RoutingProvider` 内部转发**（那样调用方真的可以一行不改）：
因为 `poll(provider_task_id)` **拿不到 kind**。路由器要知道「该问谁」，
只能把答案编进**落库的** `tasks.provider_task_id`（像即梦那样编
`req_key|id`）—— 而那是句柄格式变更，**库里正在飞的任务会读不出来**。
按 kind 造就不动句柄。

改动面：2 个模块、6 个调用点，全部是机械地把**已经在作用域里**的 kind
传下去。真正的实质改动只有 `worker.py` 的 `_provider_for`。

路由一行就是全部：

```python
if task_kind is TaskKind.text_to_image:
    return _make(settings.provider)            # 图片那一档
return _make(settings.resolved_video_provider) # 其余一切
```

⚠️ **右边必须是 `settings.resolved_video_provider` 这个属性，
不许在这里自己写 `video_provider or provider`。** 第一版就是那么写的，
而被测试抓了出来 —— 那两处 `or` 今天算出来是同一个值（所以任何行为断言
都是绿的），但 `model_post_init` 判的是属性那一个。「守卫拿 A 判、
运行时用 B」的后果是**配置里写着 MiniMax、实际按即梦跑**，账单月底才知道。
现在有一条 `ast` 守卫钉着（`test_build_provider_不自己写一遍解析逻辑`）。

#### 配置：`PROVIDER` 管图片，`VIDEO_PROVIDER` 管视频

| 变量 | 语义 |
|---|---|
| `PROVIDER` | **图片**（文生图）。语义变了，**默认值没变**（仍是 `fake`），所以现存部署不用改任何东西 |
| `VIDEO_PROVIDER` | **视频**。`None`（缺省）= **跟随 `PROVIDER`** —— 那是 2026-10-16 之前唯一的形态，所以对既有部署是**零行为变化** |
| `MINIMAX_API_KEY` | 视频那一路解析成 `minimax` 时**必填**，否则**启动就失败** |
| `MINIMAX_API_HOST` / `_VIDEO_MODEL` / `_VIDEO_RESOLUTION` | 默认 `api.minimax.cn` / `MiniMax-H3-Max` / `768P` |

**两条新的启动守卫**（`model_post_init`）：

- `VIDEO_PROVIDER=minimax` 却没 `MINIMAX_API_KEY` → 炸。同「配了真 provider
  却没密钥要在启动那一刻失败」那条纪律。
- **`PROVIDER=minimax` → 炸**，消息里指出路。MiniMax 在这个仓库**只有视频**
  （文生图是另一套接口 `POST /v1/image_generation`，v1 没接），而即梦那条
  文生图**已经被真外部验过**（第四件事 ①）。静默回退的话，一个以为
  「全平台换 MiniMax」的部署会看到文生图照常出图 —— 只是出的是假的。

⚠️ **`req_key` 那条守卫的判据变成「每路只要求自己那一个」**：图片那一路用
即梦就要 `JIMENG_REQ_KEY_IMAGE`，视频那一路用即梦就要 `JIMENG_REQ_KEY_VIDEO`。
以前是「哪一路用即梦就要两个都有」。改的理由：本批的推荐配置
（`PROVIDER=jimeng` + `VIDEO_PROVIDER=minimax`）以前会因为缺
`JIMENG_REQ_KEY_VIDEO` **起不来** —— 而视频那一路根本不用那个键。
**要求一个用不上的键，只会让正确的配置起不来，并把病因指向一个无辜的字段。**

#### ⚠️ 四处最容易「顺手改整齐」的地方

1. **`content` 必须是一个数组，而且 `text` 一定得在里面。** 即梦是
   「一个 `prompt` 字段 + 一个 `image_urls` 数组」，MiniMax 是
   **图像与文本平级的多模态数组**（靠 `type` / `role` 区分用途）。
   文档明写「**所有场景都需包含一个非空 `text`**，缺失会返回参数错误」——
   只发图不发字的请求是 400。「把 text 挪出去做成一个顶层字段」看起来更整齐，
   而它是错的。
2. **图生视频的 `ratio` 恒为 `adaptive`，用户传的 16:9 被有意忽略。**
   文档说它由输入图决定、传别的值「不报错但会被忽略」。把参数原样发过去
   是个**无害的谎**：它让下一个人以为那个值有用。
3. **`provider_task_id` 是**裸** `task_id`，不编前缀。** 即梦要编
   `req_key|id` 是因为 `GetResult` 要求把 `req_key` 再传一遍；MiniMax 的
   查询接口**只要 task_id**。抄一份前缀过来的话，查询会带着一个它不认识的
   前缀打过去 —— 而 `tasks.provider_task_id` 是**落库的**，编错了改不回来。
4. **没有 spool 子目录**（即梦那种 `JIMENG_SPOOL_SUBDIR`）。即梦要落盘是因为
   它实测**不给地址、把 121KB 的真 JPEG 塞在 `base64` 里**（第四件事 ④ 之前
   的第三件事）；MiniMax 的产物**永远是 `content.url` 一个地址**。
   「既然即梦有，MiniMax 也预先建一个吧」是纯多余的，而且它会让人以为
   那条内联通道存在。

#### 这一批新引入的一个处置方向

`MINIMAX_CODE_MAP` 里有三个码是**即梦那条链路上没有对应物**的：
`1004`（鉴权）/ `1008`（余额）/ `2013`（参数）→ **不可重试**。

既有规则是「未收录的错误码一律保守判可重试」，而它对这三个**是错的**：
密钥不对重试三次错三次、账户没钱重试不产生新信息、请求是我们自己拼的
（重试等于把同一个 bug 打三遍，还会被退避掩盖过去）。

⚠️ 这些码是**从 `error.message` 末尾的括号里正则抠出来的**
（`"... sensitive content (1026)"`），而那段文本是**对方的文案约定**，
不是契约。所以另有一张**按真实 HTTP 状态码**的兜底表 —— 哪天抠不出来，
「401 不可重试」这条判断不该跟着一起失效。

⚠️ **表里刻意没有猜的条目。** 文档里**逐字给出**的审核号只有 `1026`；
即梦那边「输出之后才判不合规」是 `50511`，MiniMax 大概率也有一个对应号 ——
**但我们没见过它**。猜错的代价是不对称的：若猜的那个号其实表示「对方服务忙」，
我们会把一个瞬时故障判成 `rejected`，而 `rejected` 在界面上是**「内容违规」**
—— 等于平白指控用户发了违规内容（还会让它不可重试、直接退款）。
**这个缺口留在下面「仍然空着的格子」里。**

#### 判据

- `check_deps` **18/18**（`req_key` 那条的判据变了，重跑过）
- 后端 **402** 条全绿（351 → +49 条 `test_minimax.py`、+2 条
  `test_pricing_b6.py` 的参数化）
- `flutter test` **138** 全绿（**前端一行没改**）

#### 本批的守卫：**21 条改坏，逐条确认变红 → 还原**

| 改坏成 | 变红的 |
|---|---|
| `ratio` 不再写死 `adaptive` | `test_用户的_ratio_进不了请求体` |
| `content` 里少了 `text` | `test_提交体_的字段与形状都对` |
| 句柄编上模型名前缀（抄即梦） | `test_句柄是裸_task_id_不编前缀` |
| 「还没好」被判成失败 | `test_还没好是_None_不是失败` |
| `422`/`1026` 不再判 `rejected` | `test_敏感内容是判拒绝且绝不重试` |
| `401/402/400` 退回「未收录=可重试」 | `test_认不出内部码时靠状态码兜底` |
| 时长守卫删掉 | `test_时长越界在提交前就响亮失败` |
| 缺 `source_url` 时不再拦 | `test_图生视频缺参考图地址_响亮失败` |
| 文生图也放行 | `test_文生图交给它_响亮失败` |
| `succeeded` 缺 url 时静默返回 | `test_succeeded_却没有地址_不可重试` |
| `build_provider` 不再看 `kind` | `test_build_provider_按_kind_路由` |
| `resolved_video_provider` 忽略 `VIDEO_PROVIDER` | 同上 |
| `build_provider` 自己写一遍 `or` | `test_build_provider_不自己写一遍解析逻辑`（**这条守卫是改坏时补的**，见上面） |
| `MINIMAX_API_KEY` 守卫删掉 | `test_配了_minimax_视频却没有密钥_启动就炸` |
| `PROVIDER=minimax` 硬拒删掉 | `test_拿_MiniMax_当图片_provider_启动就炸` |
| `_provider_for` 把注入顶掉 | `test_worker_按_kind_取_provider` |
| `submit` 传死 `text_to_image`（路由断了） | `test_端到端_两条路各走各的` |
| 计价不转手 `pricing`，自己写一份 | `test_两个_provider_的计价都转手给_pricing` |
| 对账摘要里不记模型名 | `test_提交时的_req_key_用的是配置里的模型名` |
| 出错的正文不读（**重演第三件事 ⑥ 那个坑**） | `test_出错的响应正文被记进摘要` |
| 未知 `status` 静默返回（不留 warning） | `test_没见过的_status_当成还没好而且记一条警告` |

⚠️ **有两条第一次跑是绿的，而这正是这一步的价值**：

- 「`build_provider` 自己写一遍 `or`」—— 它就是上面那条 `ast` 守卫的**来由**。
  两条 `or` 今天同值，行为断言永远绿；会漂的是**将来**。
- 「`queued`/`running` 判成失败」—— 第一版的改法是「把那个分支删掉」，
  而删掉之后它们落到「未知状态」分支上，**照样返回 `None`**，测试因此still绿。
  改成「在那个分支里抛失败」才红。所以那条用例守的是**行为**（这两种状态
  不能判死），它守不住「这一支是显式写的」—— 那件事写在用例的注释里，
  由下一个人负责。

#### §2.7 真凭据验收清单 —— **2026-10-17 已走过一遍，图生视频整条通了**

```bash
# ① 在 G:\AIVideo\backend\.env 里加两行（那文件已在 .gitignore 里）✅ 已填
#    → VIDEO_PROVIDER=minimax
#    → MINIMAX_API_KEY=<你的密钥>
#    ⚠️ PROVIDER 保持原值（现在是 jimeng）—— 文生图那条路**不动**。
#    ⚠️ 密钥来源：MiniMax 开放平台 → 账户管理 → 接口密钥。
#       H3 / H3-Max 需要先在那个平台上**按量购买 API**，否则第一次提交
#       会拿回一个 402 / 1008（余额·额度类）。**⚠️ 实测：这个账号已经买过了**
#       —— 第一次提交就回了 200 + 真 task_id，没有撞到任何额度闸门。

# ② 先确认启动没炸，并看清两路各是谁 ✅
cd /g/AIVideo/backend
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
#    · 启动横幅两行都在：AI provider: jimeng / 视频 provider: minimax
#    · GET /health → {"provider":"jimeng","video_provider":"minimax","storage":"oss"}

# ③ 走一遍界面剧本 ✅（驱动器不在这里，见 §9：G:\AIVideo\_acceptance\）
#    真 uvicorn（PROVIDER=jimeng + VIDEO_PROVIDER=minimax + STORAGE=oss）
#    + flutter build web（USE_MOCK=false）+ 无头 Chrome 走 CDP

# ④ 提交一条图生视频 5 秒，盯那四件事 ✅ 四件全过，见下表
```

**这一次的证据**（任务 19 / 用户 `mm67826` / 2026-10-17）：

| 判据 | 实测值 |
|---|---|
| `tasks.provider` | **`minimax`** ✅ |
| `tasks.provider_task_id` | `453079128834306` —— **裸 id，没有 `\|` 前缀** ✅（§3.15 那条） |
| `provider_calls` | 3 行：`submit` / `query`（还没好）/ `query`；`req_key='MiniMax-H3-Max'`、`http_status=200` ✅ |
| 提交延迟 | 1448 ms（一条视频的提交；轮询 245~251 ms） |
| 重试 | `retry_count=0` —— **一次就成**，没有撞任何闸门 ✅ |
| 成片 | `t/19/out.mp4`、2 005 678 字节、**h264 + aac**、1344×768、24fps、真实时长 **5.184 s** ✅ |
| 封面 | `t/19/thumb.jpg`、1280×720 mjpeg（ffmpeg 抽帧） ✅ |
| AI 标识（视频） | 容器 `description`/`title`/`comment` 三条都是我们的标识文案 ✅ |
| AI 标识（封面） | EXIF `ImageDescription` + XMP + comment ✅ |
| 计费 | 冻结 32 → 结算 **20** → 退回 **12**；余额 50 → 30，`frozen=0` ✅ |
| 前端 | 作品页看得见、**AI 角标在**、点开可播放、详情页写「本次消耗 20 积分，已退回 12 积分」 ✅ |

⚠️ **结算 20，不是 mock 那个 24。** mock 把成片时长模拟成「请求 + 1 秒」（=6 秒 → 24），
真 MiniMax 回的 `task.duration` **就是 5**（真实容器 5.184 s，取整到 5）。
两个数都对，它们回答的是不同的问题。**别拿 mock 的 24 去对真链路的账。**

⚠️ **这个「第一次就回 200」推翻了 §8.2 第 12 条的乐观程度**：不需要先买额度
就已经能跑了（那个账号买过）。但它**不能推广**到别的账号 —— 新账号第一次
提交仍可能是 402 / 1008。

⚠️ **一个真缺陷：MiniMax 取到我们的参考图了 —— 这一格关掉了。**
判据不是「提交回了 200」（那只证明它收下了 URL），而是**成片的首帧就是我
们那张图**：我们把参考图做成一张带橙色对角线与白色方块的渐变图，
成片 `f_0.png` 与它逐像素一致，而后续帧的平均像素差 0 → 13.35 → 29.46 → 30.97
单调变化 —— 即「**以我们的图为首帧，然后真的动了起来**」。
（即梦那边同一个空位**仍然空着**，见 §6.2 的 B6 第 2 条。）

#### 仍然空着的格子（**别把它们读成已验证**）

| # | 格子 | 2026-10-17 之后的状态 |
|---|---|---|
| ~~1~~ | ~~MiniMax 能不能把我们桶里的参考图下下来~~ | ✅ **关掉了**，判据见上（首帧逐像素一致）。 |
| ~~2~~ | ~~文档里的字段名与实际是否一致~~ | ✅ **提交体与查询响应都对上了**（`task.content.url`、`task.duration`、`status` 五态里见过 3 个）。⚠️ **仍然没见过的**：`failed` / `cancelled` 的响应形状、`error.message` 末尾那个内部码的正则、以及文生视频的 `ratio` 分支 —— 这三样只有撞上才知道。 |
| 3 | **MiniMax 那个「输出后审核」的码是多少** | **仍然不知道**（见上面「新引入的一个处置方向」）。今天它落到「未收录 = 可重试」，也就是**会白试三次**。真见着号了再补进 `MINIMAX_CODE_MAP`。 |
| 4 | **`schemas.VideoGenIn.duration` 在接口层仍然没有上下界** | **没变**。H3-Max 只吃 5~15 秒，而 `{"duration": 4}` 在接口层合法 —— 本批只在 provider 里响亮失败，**没有**加 `ge=5, le=15`（那是契约变更，要前后端一起动）。 |
| 5 | **`DURATION_SLACK_SEC=3` 的真值** | **仍然没定**。真链路这一次「请求 5 → 成片 5」，恰好没有余量压力；而**即梦那边仍然没有一条视频**。要定这个数得看到「成片比请求长」的样本。 |

⚠️ **前端侧一个新撞出来的真缺陷 —— ✅ 2026-10-17 已在另一个仓库修掉（F9）**

**上传的参考图在作品页上戴着「AI 生成」角标**，而库里 `assets.is_ai_generated = false`。
根因是 `AiGeneratedFrame` / `WorkThumbnail.showBadge` **默认 `true` 且从不读
`asset.isAiGenerated`** —— 那个字段在 `lib/` 里**没有任何 widget 读过**
（`grep isAiGenerated lib/` 只剩注释）。mock 在 `_uploadImage` 里特意把它设成
`false` 并写了一段注释解释「用户自己上传的原图不该打 AI 标识」，
**但那件事从来没被实现**。
方向与铁律相反：铁律管的是「AI 产物必须有标」，这一条是「**人的照片被标成 AI**」。
判据：作品页「已完成」里上传的那张（无播放键的那一格）带角标。

**修法**（`G:\AIVideo\flutter_application_1`，tag `f9-badge-per-asset`）：
`WorkThumbnail.showBadge` 从 `bool = true` 改成 `bool?`，
`show: showBadge ?? asset.isAiGenerated` —— **一行判断**，
三个界面（作品页网格 / 首页「最近作品」/ 参考图选择器）共用这一格，一起好了。
截图判据：同一个账号的网格里，视频那格带标、上传那格干净。
**完整的根因与「为什么原来那条测试反而把它钉住了」写在前端 HANDOFF §12**
（那里还记着一个坑：改完 `lib/` 重验时必须真刷新到新 bundle，
否则浏览器吃 HTTP 缓存里的旧 `main.dart.js`，看起来「修了但没修」）。
本仓的对外行为**没有任何变化**，所以后端测试与 `check_deps` 不受影响。

#### 不做什么

- **不改计费**（`pricing.py`、`credits_per_*`、`duration_slack_sec` 一个字不动）。
  H3-Max 的真实单价与「4 积分/秒」的差额是一个**定价决策**，单独一批。
- **不删即梦**（`jimeng.py` / `jimeng_sign.py` / `JIMENG_*` 全部保留，
  仍是一等公民，而且**已经过真网关**）。
- **不接 MiniMax 文生图**（那是 `/v1/image_generation`，另一套接口）。
- **不改前端 `lib/`**。
- **不动 `provider_max_concurrency` 的按 kind 计数方式**（它现在是一个全局数，
  图片和视频各按自己的 kind 数量比它 —— MiniMax 与即梦因此**共用视频那一档
  配额**。这是既有设计，本批不改，但换通道之后它是下一个该看的数）。

---

## 3. 已经冻结的契约决定 —— **不要重新推导，也不要「顺手改整齐」**

原则一句话：**前端已冻结，所以是后端去适配前端，不是反过来。**

### 3.1 三条硬约束（读前端代码确认的）

1. **所有 ID 必须序列化成 JSON 整数。** 前端四个模型的 `fromJson` 都走
   `requireInt(json['id'])`，字符串会抛。所以主键一律 `INTEGER PRIMARY KEY`，
   **不要用 UUID**。
2. **`available` 绝不能出现在响应里**（前端现算 `balance − frozen`）。
   **`provider_url` 绝不能出现在响应里**（有守卫测试盯着）。
3. **`settled_amount` 未结算时必须是 JSON `null`，不是 `0`**；
   **`queue_position` 只在 `status == "queued"` 时有值**，其余为 `null`。

### 3.2 响应形状

- **没有信封**。体就是对象本身（`{"id":1,...}`），不是 `{"code":0,"data":{...}}`。
  加任何统一包装的中间件都会一次性打断所有接口
- 错误：顶层 `{"code", "message"}`；重复提交额外在体里带 `task`
- `Authorization: Bearer <token>`
- `idempotency_key` 是**请求体字段**，不是请求头
- 注册返回**完整会话** `{token, user, credit_account}`（注册即登录）——
  §12.1 只写了 `{token}`，前端要的更多

### 3.3 错误码

§12.3 的八个 + 补齐的五个，**唯一定义处在 `app/enums.py` 的 `ErrorCode`**：

| 码 | HTTP | 备注 |
|---|---|---|
| `INSUFFICIENT_CREDITS` | 400 | |
| `INVALID_PROMPT` | 400 | |
| `IMAGE_TOO_LARGE` | 400 | |
| `DUPLICATE_REQUEST` | 409 | **体里带已有 task**，见 §3.4 |
| `RATE_LIMITED` | 429 | |
| `CONTENT_REJECTED` | 422 | |
| `PROVIDER_ERROR` | 502 | |
| `QUEUE_SATURATED` | 503 | |
| `UNAUTHORIZED` | 401 | 补齐 |
| `NOT_FOUND` | 404 | 补齐 |
| `USERNAME_TAKEN` | 409 | 补齐 |
| `INVALID_CREDENTIALS` | 401 | 补齐。登录失败用它 |
| `INVITE_INVALID` | 400 | 补齐；前端 F8 已加对应枚举 |

⚠️ **每一处 raise 都必须引 `ErrorCode` 常量，不许写字面量。**
打错一个字母，前端就认不出来，而认不出来的表现是那句撒谎的
**「连不上服务器，检查一下网络再试」**。

### 3.4 幂等：409 是故意的

`idempotency_key` 重复时返回 **409 + `code:"DUPLICATE_REQUEST"` + 体里带已有 `task`**。

【为什么不是「200 + 返回已有任务」】因为契约先冻结了，前端
`_submitOrReuse` 就是按这个写的。这是自觉的偏离，别「顺手修正」。

### 3.5 `aspect_ratio` vs `ratio` —— 逐字照抄，不许改整齐

图片接口读 `aspect_ratio`，视频接口读 `ratio`。对内统一归一成 `params.ratio`。

### 3.6 其余缺口的拍板

| 缺口 | 决定 |
|---|---|
| 用户名已存在 | 409 `USERNAME_TAKEN`；登录失败 401 `INVALID_CREDENTIALS` |
| `/generation/cost` 参数 | 冻结为 `?kind=&duration=&ratio=`，`duration` 秒（默认 5） |
| 720P / 1080P | v1 **只有 720P**。1080P 在契约上**没有字段**，所以结构上不可达 —— 这是文档矛盾，别默默「修好」 |
| 状态是 7 个还是 8 个 | **8 个**（前端枚举和 Mock 都是 8；§11.2 表格里的「7」是笔误） |
| `/tasks` 分页 | 返回**全部**（`items` + 无害的 `page/page_size/total`）。前端只读 `items` 且不发分页参数，**默认分页会让用户静默丢任务** |
| 流水/作品分页 | `page`（从 1 起）+ `page_size`（默认 20）→ `{items,page,page_size,total}`；**流水最新在前** |
| `credit_ledger.amount` 方向 | **恒为正**，方向由 `kind` 推导；`balance_after`/`frozen_after` 才是权威快照 |
| §9.3 的「成功但转存失败」 | **不自造第 9 个公开状态**（前端遇未知状态会抛）。内部用 `transfer_state` 三列；重试期间公开状态仍是 `submitted`，重试耗尽 → `failed` + `error_code="TRANSFER_FAILED"` |
| 通知 | **不建接口**。v1 通知留在客户端（轮询到终态本地发） |
| 产品名 | 不进接口，后端无动作 |

### 3.7 计价与账本算术（§7.2，必须复现）

1 积分 = ¥0.10。图 = 4 积分固定。720P 视频 = **4 积分/秒**。

```
冻结 freeze = (输入时长 + 请求时长 + DURATION_SLACK_SEC) × 每秒单价
            = (5 + 3) × 4 = 32        ← 5 秒 720P
结算 settle = ceil((实际输入 + 实际输出) × 单价)
            = (5 请求 → 6 实际) → 24
退回 refund = freeze − settle = 8
```

**这五个数字（32 / 24 / 8 / 22 / 50）前端测试里写死了**，
后端复现不出来，第二层契约测试就过不了。§15.1 的余额算式：
`50（注册赠送）− 4（图片）− 24（视频）= 22`。

**事务纪律（§7.3）**：`settle` 与 `refund` 必须在**同一个事务**里完成，
不能出现「扣了钱没记录」或「任务成功了但冻结没释放」。

### 3.8 注册赠送 = 50

F8 从 20 上调（原值低于 32，新用户第一次做视频必然撞墙，而 v1 没有充值入口）。
契约值在 `app/config.py` 的 `signup_grant`，与前端 `_signupGrant` 逐字一致。

### 3.9 事务边界的落点：**service 层**，不在 `get_db`

`app/database.py` 的 `get_db` 只负责关会话，**事务边界是业务决定的**。
所以写路径（注册、提交生成、取消、上传、删除资产）在 `services/*` 里
自己 commit，统一走 `atomic()` 上下文（正常 commit、抛异常则 rollback）。

两条硬纪律：

1. **校验走在任何写之前。** 「先冻结再校验余额」必须杜绝 —— 前端有一条
   断言（`repository_layer_test.dart` 的「积分不足」）要求：被拒之后
   余额、冻结、任务、流水**一个都不能动**。有测试逐项验了这一点。
2. **不要写 `with session.begin()`。** `get_current_user` 会先 SELECT
   一次，SQLAlchemy 2.0 在那里自动开启了事务，随后 `begin()` 抛
   `InvalidRequestError`。用 `atomic()`。

⚠️ 还有一个坑：`atomic()` 回滚时 SQLAlchemy 会 **expire 掉所有 ORM 对象**。
所以「抛 `DUPLICATE_REQUEST` 时体里要带已有 task」那条，必须在
**回滚之前**先把 `TaskOut` 序列化成 dict（`_duplicate_error` 的注释写了）。

### 3.10 fake provider 的「提交即完成」

`POST /generation/*` 在**同一个事务**里走完
`pending → queued → submitted → succeeded` + 结算 + 退回 + 落资产 + 写流水，
响应直接是 `status:"succeeded"` 的 task，`queue_position` 恒为 `null`。

这不是偷懒：它对齐 Mock 的「极简模式」，也正是前端
`repository_layer_test.dart` 要求的（提交完余额就是 46 / 22）。

> ### ⚠️ 一处**预测落空**，B3 落地时实测出来的 —— 记在这里免得下次又这么想
>
> B2 写这段时留了一句话：「跨时间的真实排队是 B3 —— 届时换掉的是
> `provider.submit` 的语义，**调用方那一层不用改**，这正是 §12.2 把
> provider 收成 Protocol 的意义。」
>
> **前半句对，后半句不对。** Protocol 确实让「换 provider」不用动调用方，
> 但 B3 引入的是**第二种语义**，而调用方**必须**能分辨这两种：
>
>   · 分辨不出来 → 要么把一张「已受理」的回执当成品结算（钱扣错、
>     产物是空的），要么对当场就完成的 fake 白跑一次网络往返。
>
> 所以落地时加的是 `ProviderResult.done` —— 由 **provider 自己说**
> 「这是成品还是回执」。**Protocol 能挡住的是「实现换了」，挡不住
> 「这一定义在实现之间分岔了」。** 那一处的判断在
> `generation.dispatch` 里，就是一行 `if not result.done: return`，
> 而它是 B3 最贵的一行（漏掉的表现见 §5）。
>
> 教训：**「收成 Protocol 就万事大吉」是一种容易让人少想一步的直觉。**

顺带一个后果：**B2 里造不出「未结算」的任务**，所以
`settled_amount` 为 `null` 那条只能不走 HTTP 地测（模型层），
`test_contract_shapes_b2.py` 里专门有一段注释说明。
B3 之后失败/过期/取消都会留下 `settled_amount IS NULL` 的终态，
但**这些路径同样不是「提交后停在半路」**——「未结算的 succeeded 任务」
在契约上依然是不可达的，那段注释仍然成立。

### 3.11 资产 URL 是**拼出来的** —— ~~背后没有文件~~ → **B4 起背后有真的字节**

> ⚠️ **这一节在 B4 被改写了。** 下面留的是改写前后的对照，因为「B2 的
> `public_url` 是空头支票」这件事在 B7 接真 provider 时还会再遇到一次
> （那次是**跨主机**的空头支票）。

**B2–B3 的样子**：`public_url` 指向 `/media/...`（`STORAGE=local` 时由
`StaticFiles` 挂在根路由上），但不写任何字节 —— 产物的 `size_bytes`
是 `null`，浏览器里图是裂的、视频放不了。这与当时 Mock 的
`mock-oss.local` 行为一致，且前端 `Asset.sizeBytes` 是 `int?`
（`asIntOrNull`），两边解析出来都是 null。

**B4 起**：`/media/<key>` 底下**真的有一份文件**，`size_bytes` /
`width` / `height` 都是真实值，上传的参考图也落盘。于是
「`public_url` 是一张空头支票」这个**只在 B7 才会重现**的坑，现在有了
一条可执行的判据：

```bash
# 任何一次「字节链路」的改动，都拿这个当验收
curl -s "$(curl -s -H "Authorization: Bearer $T" /assets | ...public_url)" | wc -c   # 不是 0
ls media/                                                                            # 看得见文件
```

⚠️ **`public_url` 的路径形状不变**（`/media/<storage_key>`），因为前端
从不假设它 —— `Image.network` 全带 `errorBuilder`。所以「字节从假的
变成真的」对前端测试**既不变红也不变绿**。

⚠️ **连用户上传的参考图也没落盘。** `store_reference_image` 把字节
按块读过一遍，**只为了量出大小**（超 20MB 当场拒），量完就丢 ——
`media_root` 是空的，那台机器上没有任何文件。
所以：`public_url` 全是 404、`size_bytes` 是真实的、宽高是 `None`。
（宽高留给 B4 的缩略图流水线填：那里本来就要解码，顺便记下来是免费的；
现在解码等于给「上传一张畸形图」多开一条崩溃路径。）

**后果要说清楚**：B2 的 `source_asset_id` 能校验「存在且属于你」，
但真 provider（B7）**拿不到那张图的字节**。B4 落盘之后这条才闭合 ——
这也是 B4 不能跳过、必须排在 B7 前面的原因。

⚠️ **接后端那天看到「缩略图全裂、上传的图 404」，那不是 bug，是 B4 没做。**
写在这里，免得有人从应用层一路查到存储层。

另外 `public_url` 的**主机来自 `PUBLIC_BASE_URL`**（默认
`http://127.0.0.1:8000`）。所以用 `--port 8123` 起服务时，返回的 URL
仍然写着 `:8000` —— 连真机/真域名时**必须改这个配置**，写成 localhost
的话 App 拿到的地址指向它自己。

### 3.12 缺必填字段 → `400` + `INVALID_REQUEST`（**不是** FastAPI 默认的 422）

> ⚠️ **这一节原先写的是「走 FastAPI 默认 422、体是 `{"detail":[...]}`」。那是错的**，
> 是计划阶段凭印象写的，落地时 `app/errors.py` 装了 `RequestValidationError`
> 处理器。B2b 的第二层门禁在真后端上把这条钉住了，才发现文档和代码不一致。

真正的形状：

```json
HTTP 400
{"code": "INVALID_REQUEST", "message": "请求参数不合法"}
```

**为什么必须翻译，不能沿用 422 的默认体**：那个默认形状破了「无信封」契约 ——
前端 `DioApiClient._toException` 从**顶层**读 `code` 和 `message`，读到两个
null，于是用户看到的是开发味的「服务端返回 HTTP 422，且响应体里没有
message 字段」。422 在本项目里另有主人（`CONTENT_REJECTED`，内容审核未过），
两个意思共用一个状态码会让排查的人分不清。

**前端认不出 `INVALID_REQUEST`（它有意的，不是缺口）**：`ApiErrorCode.tryFromWire`
对未知码返回 null，退化成通用文案。而这条路径前端**够不到** —— 前端有本地
校验，真发出去的一定带 `prompt` / `idempotency_key`。它是给 curl 手打和
将来某个新客户端写错时用的兜底。**业务校验绝不许借用这个码**：空提示词
要抛 `INVALID_PROMPT`（前端认它，会说得具体）。

两处刻意的宽严（已核对前端取值）：

- **密码**只要求非空且 ≤72 字节（bcrypt 的硬上限）。**不加最小长度** ——
  前端全线用 `pw123456`，收紧会误伤。
- **`source_asset_id` 用 `int` 注解收字符串**：前端发的是字符串
  （`requireInt(...).toString()`），pydantic lax 模式转得动，不要改成 `str`。

**注册返回 `201`，不是 `200`**（`auth.py` 显式 `status_code=HTTP_201_CREATED`）。
前端的成功判定是区间（`_send` 只判 `<200 || >=300`），所以对 App 无差别 ——
但 B2b 的门禁里写死了 201，是为了让下一个看到 201 的人不用怀疑自己看错了。

### 3.13 B3 对**响应契约**做的事：几乎什么都没做

这一批全部工作在服务端内部，**响应形状一个字段没动**（§15.1 那笔账
46 / 22 仍然是逐字不变的，有测试钉着）。三件值得记的：

1. **闸门满了 = `200` + `status:"queued"` + `queue_position`，不是 503。**
   §12.3 里那个 `QUEUE_SATURATED`(503) 说的是「**队列装不下**」，
   而 §8.2 没给队列定义深度上限 —— 所以这个码**至今在后端没有一个
   `raise` 点，而且不是 B3 漏了**。真要它可触发，得先在 §12 里补一条
   队列容量规则。前端那条覆盖台账已经改成这么写了（B3 期间改的，
   和这次后端改动配套），见 §4 那张表。
2. **B3 起 `queued` 是一段真的会持续的状态**，于是「排队中取消全额退回」
   （§7.4）和「排队中显示真实位次」（§8.2）第一次成为可达路径 ——
   而它们在 B2 的 fake 下永远只能返回 `TASK_NOT_CANCELABLE`。
3. **`ProviderResult.done` 是内部的，不进任何响应。** 别顺手把它漏到
   `TaskOut` 里：前端模型没有这个字段，而且「回执/成品」是平台对
   provider 的分类，不是对用户的。

---

### 3.14 B6：`public_url` 是**永久**地址，`url_for` 不许改成预签名

这一条同时管 `LocalStorage` 与 `S3Storage`：两者给的都必须是**永久可读、
不带鉴权、不随时间变化**的地址。本地那支靠 `/media` 静态挂载，OSS 那支
**要求桶公共读或挂 CDN**（§9.1 的第一种）。

**为什么把预签名明确排除掉**（它看起来更「安全」）：

| | 预签名 | 我们要的 |
|---|---|---|
| 会不会过期 | **会**（带 `X-Amz-Date` / `X-Amz-Expires`） | 不会 |
| 出错的时机 | **只在时间过去之后** —— 本地怎么测都是好的 | 立刻 |
| 用户看到 | 昨天生成的作品今天全裂了 | — |
| 桶的配置要求 | 私有即可 | 公共读 / CDN |

判据是一个**取巧但很锋利**的断言：同一个 key 调两次 `url_for`，结果必须
**一模一样**。预签名的定义性特征是「带时间」，所以任何把时间掺进地址的
写法都会让它红（改坏验过：加上 `?X-Amz-Date=...` 之后那条用例当场变红）。
它在 `tests/test_storage_b6.py` 与 `check_deps.py` 的 boto3 那一项里各有一份。

### 3.15 B6：`req_key` 编进 `provider_task_id`，不放在进程内存里

即梦的**同一个接口**用不同的 `req_key` 提供不同能力，而查询（`CVSync2AsyncGetResult`）
**也要带同一个 `req_key`**。于是「这个任务当初是用哪个 `req_key` 提交的」
必须跨请求、跨重启都在。

做法：`provider_task_id = f"{req_key}|{task_id}"`，随任务**一起落库**
（`tasks.provider_task_id` 那一列本来就是给这个用的）。

**为什么不加一个 `self._handles: dict[int, str]`**：那正是铁律里
「任务状态不能放在进程内存」的一种形式。它今天能跑通、测试也全绿，
但**重启之后所有在途任务都会用错的 `req_key` 去查** —— 而表现为
「查不到这个任务」→ 判死 → 退款。用户会看到一条本该成功的任务失败，
而日志里一切正常。

⚠️ **`|` 这个前缀是即梦专有的，不是一条通用约定**（2026-10-17 B7.4 补）。
它之所以存在**只是因为 `GetResult` 要把 `req_key` 再传一遍**。
MiniMax 的查询接口**只要 task_id**，所以 `MinimaxProvider` 回的是
**裸 id**（`tests/test_minimax.py::test_句柄是裸_task_id_不编前缀`
钉着）。想「统一一下，两边都编前缀」的话，代价不是多几个字符：
`tasks.provider_task_id` 是**落库的**，一个 MiniMax 在途任务被编上前缀之后，
查询会带着一个对方不认识的前缀打过去 —— 而**改不回来**（库里那些行的 id
已经错了，只能在查询前剥掉，于是前缀变成一个必须记住的历史包袱）。
「两边形状不一样」在这里不是不一致，是**各自照着自己上游的要求**。

### 3.16 B6：搬运的 IO 在事务外，但**只有 worker 那一条路**

```
worker：  事务内 claim（transfer_state=running + commit）
          → 事务外做 IO（perform_transfer，签名里没有 Session）
          → 新事务里结算 + 落资产 + transfer_state=done
同步路径：保持原样 —— IO 仍在事务里
```

**为什么不能一刀切**：`test_transfer_b4.py::test_同步路径的转存失败_502_而且一整笔都不留`
钉着「被拒的提交不留痕」，而那正是靠同步路径的 IO 在事务里被回滚实现的。
一刀切会把它变成 **200 + 一条永远 `submitted`** 的任务（`TEST_MODE=1`
下不起 worker，而跨仓门禁正是这个配置）。

**守卫的判据是「认得见」，不是「别的连接写得进」。** 后者听起来才是
「IO 不该在事务里」的理由，但它**两种写法都是绿的**：会话是
`autoflush=False`，搬运之前的几个阶段只发 SELECT，所以 SQLite 那边
根本没拿过写锁（实测：改坏之后仍然 `能否写库 = True，耗 0.00s`）。
真正有区分力的观察是「搬运进行中，库里能看到 `transfer_state = running`」
—— 也就是**认领先落库，IO 在它之后**。`tests/test_txn_boundary_b6.py`
的文件头把这件事写全了，**别把那三条用例改成「另一个连接能写入」的版本。**

### 3.17 B7.3：内联产物落 **spool 文件**，回 `file://` —— 不加字节通道

真即梦（`jimeng_t2i_v31`）**不给产物地址**，把 JPEG 内联在
`data.binary_data_base64[0]` 里（详见 §2.6 第三件事 ④）。于是
`JimengProvider.poll` 在 `_extract_url` 返回空时改走 `_materialize_inline`：
解 base64 → 原子写进 `provider_spool_root/jimeng/<即梦 task_id>.bin`
→ 回 `dest.as_uri()`。

```
即梦响应 ──base64 解码──▶ spool/jimeng/<task_id>.bin ──file://──▶
        └─ transfer._local_path_for_file_url（**包含性检查照旧生效**）
           → _sniff（按魔数判 mime）→ 写隐式标识 → put_file
```

**四条不要「顺手改整齐」的理由：**

1. **产物必须以「地址」的形态进库。** `tasks.provider_url` 是转存重试
   （和重启后的补转存）唯一的线索 —— 转存在 `defer_io` 之后做，可能发生在
   进程重启之后。把 bytes 塞进 `ProviderResult` 再落库是另一条路，代价是
   **加一列 + 一次迁移 + 每一行变胖**，而且它并不比落文件更安全。
2. **这不是一条新的信任边界。** `provider_spool_root` 之下正是 `fake`
   已经在用的那条路（`fake` 也自己把字节落到 `generated/` 再回 `file://`）。
   所以 `_local_path_for_file_url` 的包含性检查（B4 的防线，专门挡
   「被污染的 `provider_url` 变成任意文件读取」）是**被使用**的，
   **一个字符都没放宽**。任何「为了内联产物开一个例外」的改法都是在削它。
3. **文件名用即梦的 task id，是**确定性**的。** `poll` 会被重复调
   （重启后的补转存、重试）。文件名里带上时间戳或 uuid 的话，每问一次
   就在磁盘上多留一张 121 KB 的图，而 **v1 没有 GC**（§6.2 第 4 条）。
4. **下标从 `resp_data` 的 `uri://binary_data?index=N` 里读，不取第 0 个。**
   今天列表里只有一个、下标就是 0，但那是**这一次**的事实而不是约定 ——
   取第 0 个在「它指认第 1 个」的那天会**静默地交付错的那张图**，
   而库里每一条记录看起来都正常。越界退回 0（认不出来时退回是安全的）。

⚠️ **上一限（`MAX_ARTIFACT_BYTES`）判两次**，解码前按长度粗判一次
（base64 是 4:3 展开的），解码后再判一次。只判后者的话，一个远超 200MB 的
字符串会先被完整解进内存、再被判死刑 —— 那道闸门拦住的就不是磁盘而是内存了。

⚠️ **落下来的文件没有扩展名**，这是有意的：格式由转存层的 `_sniff`
按魔数判（见它那段「不能信 URL 的后缀」）。猜一个后缀只会让
「名字说 png、内容其实是 mp4」这类不一致多一个来源。

### 3.18 B7.4：provider 按 **`TaskKind`** 路由，`build_provider` 带 `kind` 形参

```python
if task_kind is TaskKind.text_to_image:
    return _make(settings.provider)              # 图片那一档
return _make(settings.resolved_video_provider)   # 其余一切
```

**这是本仓库唯一一处偏离 `providers/__init__.py` 文件头那句
「切真 provider 时调用方一行不改」的地方**，所以理由要留在这里：

- **一个 tick 一个 provider 表达不了「图片一家、视频另一家」。**
  `worker.py` 建一个 provider，然后在 `for kind in TaskKind:` 里用在所有类型上。
- **为什么不做一个内部转发的 `RoutingProvider`**（那样调用方真的可以一行不改）：
  因为 `poll(provider_task_id)` **拿不到 kind**。路由器要知道「该问谁」，
  只能把答案编进**落库的** `tasks.provider_task_id`（就是 §3.15 那个前缀）
  —— 而那是句柄格式变更，**库里在飞的任务会读不出来**。按 kind 造不动句柄。

**三条不要「顺手改整齐」的：**

1. **右边必须写 `settings.resolved_video_provider`，不许在这里自己写
   `video_provider or provider`。** 那两处 `or` 今天算出来同值，所以**任何
   行为断言都是绿的**，而 `model_post_init` 判的是属性那一个。
   「守卫拿 A 判、运行时用 B」的后果是**配置里写着 MiniMax、实际按即梦跑**，
   要到月底看账单才知道。这条由一条 `ast` 守卫钉着
   （`test_build_provider_不自己写一遍解析逻辑`），**别删它**。
2. **`video_provider` 的默认值必须是 `None`（= 跟随 `provider`），不能是
   `ProviderKind.fake`。** 前者对既有部署是**零行为变化**，后者会让每一台
   没写过这一行的机器把视频悄悄换成 fake。
3. **`VIDEO_PROVIDER=minimax` 配了却没 `MINIMAX_API_KEY` → 启动就炸。**
   同「配了真 provider 却没密钥要在启动那一刻失败」那条纪律。
   反过来 **`PROVIDER=minimax` 也炸**（消息里指出路）：MiniMax 在这个仓库
   **只有视频**，拿它当图片 provider 等于配了一个不存在的实现 ——
   静默回退的话，一个以为「全平台换 MiniMax」的部署会看到文生图照常出图，
   只是出的是假的。

⚠️ **替身（`tests/conftest.py` 的 `scripted`）接过 `kind` 但逐 kind 返回同一个
provider**，这是故意的：既有那 40 多条用例验的是「任务怎么走」，不是
「按 kind 路由」。给它们一个按 kind 变化的替身，会把那些用例变成
**碰巧还是绿的**。路由本身由 `test_minimax.py` 单独钉。

---

## 4. B2b 已完成 —— 「从来没跑过的那条路」现在跑起来了

门禁结论（2026-10-13 实测）：
**第二层契约测试打真后端 41 条全绿**；默认 `flutter test` 138 条全绿 + 22 条可见 skip。
**只动了前端 `test/`，`lib/` 一个字符没碰**（tag `b2b-live-gate`）。

`DioApiClient` 那两个从没执行过的 `_decode` / `_toException` 现在**真的被跑过了**，
而且 §15.1 那笔账（余额 22）在两仓之间逐字对上。

### 交付物（全在前端 `test/`，本次**没有**新增 `LiveBackendApiClient`）

原计划是「造一个 `LiveBackendApiClient`」。落地时发现**不需要** ——
直接让 `appConfigProvider` 拿到 `--dart-define` 的配置就行，
`apiClientProvider` 里那个 if 自然走到 `DioApiClient` 那一支。
多造一个客户端的话，验的就只是「我新写的这个客户端能不能用」，
而**「那个 if 分支接得对不对」仍然没被验过** —— 那才是唯一没被验过的东西。

| 文件 | 是什么 |
|---|---|
| `test/live_backend.dart` | **公共件，不是测试**（和 `shell_harness.dart` 同类）：按命令行分叉的容器工厂、`/__test/reset` 接线、裸 dio 请求、发积分 |
| `test/live_contract_test.dart` | **新增 22 条**：路径漂移、响应形状、错误码不撒谎、覆盖台账 |
| `test/repository_layer_test.dart` | **同一份 19 条断言现在打两种后端** —— 「换掉 provider 就够了」这句话现在可以被执行 |

### 命令（`--concurrency=1` 不能少）

```bash
# 后端（TEST_MODE 才有 /__test/{reset,grant}）
cd /g/AIVideo/backend
TEST_MODE=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 前端
cd /g/AIVideo/flutter_application_1
flutter test --concurrency=1 \
             --dart-define=USE_MOCK=false \
             --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

⚠️ **端口用 8000**：`PUBLIC_BASE_URL` 的默认值就是它（见 §3.11）。

⚠️ **`--concurrency=1` 是必须的，不是「稳妥起见」**：`flutter test` 默认
**并行跑测试文件**，而两个 live 文件共用**一个后端、一个库**，且每个用例前
都清库。并行时 A 刚 `drop_all`、B 正在插数据，撞出来的是一片
**看起来像业务错误的假象**（401 未登录、409 用户名被占、reset 自己 500），
后端日志里只有 SQLite 的 drop/create 打架。实测踩过。

### 四组门禁各守什么

| 组 | 守的东西 | 为什么只有真后端能守 |
|---|---|---|
| 路径清单 | 13 个 `ApiPaths` 与后端路由表**两个方向**都一致 | 对着后端自己的 `/openapi.json` 比，不抄一份会过期的列表。还断言两边各 13 条，防「两个空集比较」空转通过 |
| 响应形状 | 无信封、id 是整数、`available`/`provider_url`/`storage_key` 哪儿都没有、`params` 是对象、时间戳带时区 | 读**原始 JSON**。读模型只能证明「前端没崩」，证明不了「服务端没多发字段」 |
| 错误码 | 每个能触发的错都落到前端认得出的码上，且 HTTP 状态码与前端 `ApiErrorCode` 自己声明的一致 | 认不出码 → 登录页会说那句撒谎的「连不上服务器」。Mock 从不返回形状错误，这条只有真后端看得见 |
| 覆盖台账 | 前端 9 个错误码全被交代过 | 新增枚举值却没交代就红，逼人回答「这条验没验过」 |

**在 B2 里触发不了的三个码**（后端 `AppError(...)` 的调用点上**一个都不存在**）：
`CONTENT_REJECTED`（输入审核未实现，B7）、`PROVIDER_ERROR`（fake 不会失败，B7）、
`QUEUE_SATURATED`（没有真队列，B3）。B3/B7 给它们写上第一个 raise 时，
该把它们挪进「已覆盖」那一组。

> **B3 更新**：这三个的处境**不一样了**，前端门禁里那段说明也同步改了
> （那处改动在**前端仓库**，和后端 B3 配套）：
>
> | 码 | B3 之后 |
> |---|---|
> | `CONTENT_REJECTED` | 后端**已经有 raise 点**了（`generation._sync_failure`：provider 在提交阶段判违规 → 422）。但门禁跑的是 `PROVIDER=fake`，而 fake 是**契约的一部分**（永远成功、不发外网请求），所以仍然触发不了 → **B7 接真即梦后该挪进「已覆盖」** |
> | `PROVIDER_ERROR` | 同上（`_sync_failure` 的另一半：502） |
> | `QUEUE_SATURATED` | **仍然没有 raise 点，而且这是对的** —— §8.2 没给队列定义深度上限（闸门满了是「排队」，不是「队列已满」）。它**不会**因为 B7 而变化，要它可触发得先补 §12 |
>
> 这个区分有实际后果：下一个人看到「三个都没验」，很容易以为
> 「三个都是后端还没做」。**「还没做」和「构造上不可达」是两件事。**

### B2b 第一次跑就撞出来的五件事 —— **全是接线/认知问题，没有一个是后端 bug**

| 现象 | 真因 | 落点 |
|---|---|---|
| 一片 401「登录已过期」 | 登录态是 `AuthController._adopt` 装的（先落盘、再写内存副本）。测试直接调 `authRepositoryProvider` 就跳过了它。**Mock 模式永远暴露不出来** —— `FakeApiClient` 根本不看 `Authorization` 头 | 夹具改走 `authControllerProvider.notifier.register`，即登录页那条路。不要手抄 `_adopt`，否则它将来多一句夹具就悄悄过时 |
| reset 500 / 间或 409 | 两个 live 测试文件并行，互相清库 | `--concurrency=1` |
| 注册响应 `statusCode` 是 201 | 后端显式 `HTTP_201_CREATED`；门禁里写死了 200 | 前端 `_send` 判的是区间，2xx 都放行（见 §3.12） |
| 「积分不足」那条红了，但报的是「图生视频必须提供 source_asset_id」 | 校验顺序照抄 Mock：**提示词 → 参考图 → 幂等 → 配额 → 余额**。测试没传参考图，撞的是前面那道闸 | 顺序是对的，测试错了。**一条测 A 却因为 B 而红的用例比没有更糟** —— 它绿的时候你会以为 A 被守住了 |
| `params.ratio` 是 null | 前端 `TaskParams.toJson` **省略值为 null 的键**，测试没给 ratio，于是参数里压根没有它 | 想验「原样回来」就必须真给一个值 |

### 已知缺口（记录在案，**不在 B2b 修**）

后端会发而前端 `ApiErrorCode` 里**没有**的码：`INVALID_REQUEST`、`USERNAME_TAKEN`、
`INVALID_CREDENTIALS`、`NOT_FOUND`、`TASK_NOT_CANCELABLE`。

其中 401（`INVALID_CREDENTIALS` / `UNAUTHORIZED`）和 409（`USERNAME_TAKEN`）
前端是**按 HTTP 状态码分支**的（登录页看 401/409，`isUnauthorized` 看 401），
所以**不说错话**；`NOT_FOUND`(404) 落到通用兜底，也不撒谎。
只有 `TASK_NOT_CANCELABLE` 在 UI 上没有精确文案（「出错了，请稍后重试」）。
要精确文案得在前端枚举里补一条 —— 那是 F 侧的一次小改动，不属于后端批次。

### 已知的接线坑（B2 里实测到的）

| 坑 | 现象 | 结论 |
|---|---|---|
| 命令行里的中文 | FastAPI 报 `There was an error parsing the body` | 见下方「为什么是命令行的问题」 |
| Windows 下 `/tmp` | python 与 curl 都 `No such file or directory` | `/tmp` 是 MSYS 的虚拟路径，Windows 程序看不见。用仓库下的临时目录，路径写 `G:/...` |

#### 为什么是命令行的问题（实测的字节，不是猜的）

把 `{"username":"验收的人"}` 发到一个记录原始字节的小服务端上，两种情况：

```
写在命令行里（curl -d '...'）  字节 d1e9cad5b5c4c8cb   → GBK
写在文件里（--data-binary @f） 字节 e9aa8ce694b6e79a84e4baba → UTF-8
```

**bash 本身发的是 UTF-8**（`printf '验收的人' | xxd` 就是 UTF-8）。
变的是**交给原生 Windows 程序的那一步**：MSYS2 会把非 ASCII 的**参数**
按**系统 ANSI 代码页**（这台机器是 CP936）转成 GBK 再交给它，
而 curl 是原生 C 程序、读的正是 ANSI `argv` —— 于是它把 GBK 字节当 body 发了出去。

**所以**：

- 请求体里有中文时，**用文件传**（`--data-binary @f`），文件里的字节
  bash 不做任何转换；
- 这条**不适用于 MSYS 自带的程序**（`printf`）和**走 UTF-16 命令行的
  程序**（Python 3 在 Windows 上从 `GetCommandLineW` 取 argv，拿到的是
  正确的中文）—— 别看到 Python 那边正常就以为 curl 这边也正常；
- 在 shell 里加 `chcp 65001` **不管用**，转换发生在启动原生程序那一刻；
- **后端是对的**，不要在那边改任何东西。

---

## 5. 已经踩过的坑（别再踩一遍）

| 坑 | 现象 | 结论 |
|---|---|---|
| `alembic.ini` 里的中文 | `UnicodeDecodeError: 'gbk' codec` | `.ini`/`.cfg` 纯 ASCII |
| httpx 0.28 的 `ASGITransport` | `no attribute '__enter__'` | 它**只有异步接口**；**整套契约测试都是 async**，这不是风格选择 |
| SQLAlchemy 2.0 的 `Mapped[]` | `ArgumentError: Could not interpret annotation` | 注解按**模块级名字**解析。`Mapped` 必须 `from sqlalchemy.orm import Mapped` 且**名字在模块全局**，函数内 import 会抛 |
| `JWT_SECRET=` 留空 | 服务带**空密钥**正常启动 | 「必填」不挡空串。已修：`env_ignore_empty` + 32 字符强度下限 |
| 循环外键 | `SAWarning: Cannot correctly sort tables` | SQLAlchemy 打一行警告然后**照常生成迁移**；SQLite 侥幸能跑，**PostgreSQL 直接失败**。已断掉环 |
| 时间的 8 小时偏差 | 前端显示比实际早 8 小时，**两边测试全绿** | SQLite 不存时区 → 读出来 naive → 序列化不带 `Z` → Dart `DateTime.tryParse` 按**本地时间**理解。已修：`app/types.py` 的 `UtcDateTime` |
| SQLite 不报唯一约束名 | 断言约束名永远红 | SQLite 对命名 CHECK 报名字，对 **UNIQUE 只报列名**。断言列名 |
| Alembic 不会给自定义类型加 import | 迁移 `NameError: name 'app' is not defined` | 且 `EnumStr` 会被渲染成**丢了枚举信息**的形式。已修：`alembic/env.py` 的 `_render_item` —— **修生成器，不要手改产物** |
| httpx 的 multipart 两元组 | 想测「不带 Content-Type」却测不到 | 两元组会用**文件扩展名**猜类型，猜不出才退回 `application/octet-stream` —— 它总能发出一个非空类型。只有显式传 `content_type=""` 才会发出空 `Content-Type: `。已实测确认 |
| FastAPI 序列化的是**紧凑** JSON | 断言 `'"x": true'`（冒号后有空格）永远红 | 用正则 `r'"x":\s*true\b'`，别钉死空格 |
| `atomic()` 回滚会 expire ORM 对象 | 「重复提交时体里带 task」在回滚后才序列化 → 属性访问报错 | **抛之前**先 `model_dump(mode="json")` 成 dict。见 `_duplicate_error` |
| 幂等那道闸其实有**两层** | 抠掉查重那段，测试**不红** | 数据库上的 `UNIQUE(user_id, idempotency_key)` 会兜住，`_translate_integrity_error` 把它翻译成同一个 409。真正能改红的是**把幂等键存成 null** |

B3 新踩到的：

| 坑 | 现象 | 结论 |
|---|---|---|
| `from app.providers import build_provider` | `monkeypatch.setattr(app.providers, "build_provider", ...)` **不起作用** | 名字在**导入时**就绑定了，`generation.py` 和 `worker.py` 手里各自攥着原来那个函数对象。用**字符串目标**（`"app.services.generation.build_provider"`）一次改对。这个坑的表现是「用的还是真 fake」，**不报错**，只是让用例以一种莫名其妙的方式变绿或变红 |
| `expire_on_commit=False` + worker 改过的行 | 断言读到的是「worker 动手**之前**」的状态 → 一条永远绿的用例 | 测试里读 worker 改过的行必须 `session.expire_all()` 再读。见 `test_worker_b3.py` 的 `_task_row` |
| `worker._last_poll_round` 是**模块级全局** | 单独跑一条用例是绿的，跑整个文件就红 | 上一条用例留下的时间戳会让这一条的 poll 被**静默跳过**。`test_worker_b3.py` 里有个 autouse 夹具兜它 |
| 「先问进度、再出队」的顺序 | 反过来写**不会让任何功能失效** | 它只是让吞吐变差（闸门只有 1 个位子，每完成一条白等一轮 2 秒）。**只影响性能、不影响正确性**的顺序最容易在重构里被无声调换 → 专门有一条用例钉着 |
| 位次和出队顺序是**跨函数**的约定 | 两个函数各自都对、合起来错 | 钉它的用例必须让四种候选键给出**四个不同的答案**，否则一个用错键的实现照样绿。见 `test_queue_b3.py` 那条用例里那张别扭的表 |
| uvicorn **不给 root 挂 handler** | 应用日志（横幅、worker 启动、tick 摘要）在真进程里一个字都没有；**pytest 下完全正常** | 详见 §2.4 第 ② 件事。**这一条只有真跑进程能发现** |
| 手工验收里「把钱冻上」 | 忘了冻结就摆任务 → 结算时会扣一笔没冻过的钱 | 摆 `queued` 任务的脚本要调 `credits.freeze(...)`，不能只插 `tasks` 一行 |

**一条工作约定**：守卫测试要**故意改坏跑一遍**，确认它真的会红。
已经这么验过的：`TEST_MODE` 门禁（改坏时 6 条全红）、UTC 时区、
迁移漂移（改坏时直接指出缺哪一列）、`settled_amount` 的 `null`→`0`。

B3 又验了 10 处（改坏 → 确认变红 → 还原，**逐字对过文件**）：
`dispatch` 漏掉 `done` 的 return（10 条红）、出队改用 `created_at` 排序、
先出队再问进度、重试时不清 `provider_task_id`、拿掉过期兜底、
拿掉 `TEST_MODE` 的 worker 门禁、位次去掉 `id` 兜底、
不再判断 root 有没有配过日志、`main` 不再接日志、
把 `aivideo.propagate` 设成 `False`。

⚠️ **其中有一次「改坏了却不红」，而那次是测试写错了**：`propagate=False`
经过的是「应用 → root」那一段，而我原先那条用例只钉了「`aivideo.worker`
→ `aivideo`」那一段 —— 也就是说**它的注释在说一件它没在测的事**。
补了一条 `test_应用logger仍然向上传播` 之后才真的红。
改坏验的是「守卫有没有用」，顺带也会照出「注释有没有撒谎」。

⚠️ 而 B2 里有一次**改坏了它却不红**，那次最值钱：上面那条
「幂等有**两层**」的发现，以及顺带查出来的一个**真 bug** ——
`_translate_integrity_error` 原先取的是「这个用户任意一个带 key 的任务」，
在没有并发的测试里看不出问题，真走到那条路径时会把**别的任务**
当成重复的那个返回给客户端（用户点生成，拿回来一个他上周做的视频）。
已修：加 `idempotency_key` 参数并按它过滤。
**所以「改坏了不红」不是测试写错了，是还有一层没被看见。**

B4 验了 **8 处**（8 条防线逐条改坏 → 确认变红 → 还原，跑完
`git status` 确认一个字节都没留下）：

| 改坏什么 | 变红几条 | 备注 |
|---|---|---|
| 拿掉 ≤4096 边长校验 | 2 | 两个样本各走一条路径，见 §2.5 的「68 字节炸弹」 |
| 转存不落视频封面 | 5 | 连带 B2 的两条也红（资产张数变了） |
| 转存不记 `provider_url` | **41** | 最响的一条：地址一空，任务**当场判失败**，半个套件塌方 |
| 转存失败不累加 `transfer_attempts` | 2 | 重试与耗尽各一条 |
| 资产行改回写死的宽高 | 3 | 见下 |
| 整个拿掉 spool 包含性检查 | 1 | 任意文件读取 |
| 包含性检查改成裸字符串前缀 | 1 | **只有 `spool-evil` 那个样本红** —— 见下 |
| 同步路径失败改回「留在 `submitted`」 | 1 | **只有「可重试的失败」那条红** —— 见下 |

三条值得单独记：

- **「写死的宽高」那条能红，是因为测试里用了 333×777。** 如果重试
  用例拿 fake 的契约尺寸（1024×1024 / 1280×720）当样本，一个
  **把宽高写死**的实现会看起来完全正常 —— 测出来的和写死的一样。
  故意用一组**不像契约值**的尺寸，正是为了让这条能红。
- **「裸字符串前缀」那条只被 `spool-evil` 抓到。** `credentials.txt`
  和 `../` 两种形状，`startswith` 检查**照样能挡住**；只有名字以
  `spool` 打头的**兄弟目录**（`spool-evil`）能穿过去。少造这一个样本，
  这条防线就永远是绿的。
- **「同步路径」那条必须用可重试的失败。** 不可重试的失败在 B4
  之前就已经会被判死（`not exc.retryable` 那半个条件），所以它
  **测不到 `sync` 这个开关**。只有「可重试的失败 + 同步请求」这个
  组合，才真的证明 `sync` 接上了。

⚠️ 另外两个**工具层**的坑（都不是业务 bug，但会把结论带反）：

- **`pytest.ini` 里已经有 `addopts = -q`。** 所以命令行再加一个 `-q`
  就成了 `-qq`，它会**把最后的汇总行也吃掉** —— 表现是「跑完了但没说
  通过几条」，很容易被读成「没跑完」。跑门禁时**不要**再加 `-q`。
- **这个仓库里两种行尾都有**（`transfer.py` 是 LF，`generation.py`
  是 CRLF）。写「改坏再还原」的脚本时必须**按文件自己的行尾**匹配，
  否则那句改坏**匹配不上、静默跳过** —— 而它会被读成「这条守卫通过了」。
  这正是 B4 第一次跑这个脚本时 M4/M5 两处的样子。

B7.3 新踩到的（全是**真外部**才照得出来的，B0–B7 的测试一条都抓不到）。
**最后三行是 2026-10-16 那一轮加的**（同一类坑，同样是真外部才照得出来）：

| 坑 | 现象 | 结论 |
|---|---|---|
| **网关的 `InvalidAuthorization` 有四种成因，长得一模一样** | 签名写错 / AK 形状不对 / `req_key` 不对 / 能力没开通，**同一个 400** | 逐条做减法，**最快的一刀是拿一把已知有效的凭据当对照组**（§2.6 第三件事 ① 那张表）。⚠️ 别一上来就怀疑签名 |
| **`.env` 里填的是别的类型的凭据** | 60 位 base64 味 + 158 位 base64url；形状对不上 IAM 的 `AKLT`+43 | 「填上了」≠「填对了类型」。**验形状**（`AKLT` 开头 + 47 字符）比验值便宜 |
| **`Host` 不在待签头集合里** | `jimeng_sign.py` 收了 `host` 参数却忘了并进 `signed_headers_in` | 规范偏离**照旧要修**，但别指望它解释真网关的拒绝 —— 修完真网关的答案一个字没变。`httpx` 只在头里没有 `host` 时才按 URL 补一个，所以我们给了它就一定用我们的 |
| **官方 SDK 的签名也不被这个网关接受** | 拿火山自己的 `SignerV4` 算出来逐字节相同，照样 `InvalidAuthorization` | 这一条**很值钱**：它把「我们签错了」整个假设空间一次排除掉。**当自己在实现一个协议时，先找一个「已知正确的实现」当对照组** |
| **`>= 400` 的响应体原先没有被记录** | 四次 `HTTP 400`，`provider_calls` 四行 `resp_message` **全 NULL** —— 对方说了病因，我们一个字没留 | **对方明确说病因的那一类响应，恰恰是唯一不记录的一类。** 已修（`_with_body`），认业务信封与 `ResponseMetadata` 两种形状。⚠️ 只进对账表，**不进用户响应体** |
| **探针脚本「结构上不可能真的提交任务」** | 没有 prompt 的探针，网关照单全收，回了个真 `task_id` | 即梦那边多了一条**我们没有跟踪**的任务。**凡是往计费接口发的请求，先假设它会成功** |
| 真网关回的码不在文档表里 | `50430 Request Has Reached API Concurrent Limit` | 文档那张表只有 `50429`（QPS）的岗。**真跑出来的码会超出文档**，所以「未收录的码默认可重试」这条保守策略是对的（§3.13） |
| **两个闸门各给一个码，而现象都是「失败」** | `50400 Access Denied`（HTTP 401）= **权限/开通**没过；`50430`（HTTP 429）= 权限过了、**撞在并发配额**上 | 分不清这两个，就会把「这个产品没开通」读成「我们代码有问题」。**码本身就是那把刀**，不用猜（§2.6 第四件事 ② 有对照表） |
| **桶匿名可读，浏览器里却没有那张图** | `curl` 200、对象就在桶里、后端日志全绿；应用侧 `performance` 那条是 `status:0, transferSize:0, initiatorType:'xmlhttprequest'` | CanvasKit 的 `Image.network` 走 **XHR**、不是 `<img>`，所以还需要桶上的一条 **CORS 规则**。**「服务端取得到」和「浏览器显示得出」是两件事**，判据也不同（§2.6 第四件事 ③） |
| **一条永远不可能成功的「可重试」** | `50430` 被分类成可重试，同一条任务连着提了 4 次，**四次撞的是同一堵墙**，用户看到的是「生成失败，请重试」 | 错误码给出「能不能重试」是不够的 —— 配额为 0 时那是一个**确定性失败**。真到线上需要「同一任务连续 N 次同类错就停」这一层（§6.2 新缺口第 2 条）|

---

## 6. 环境缺口与已知缺口

### 6.1 环境（需要人动手的）

| 项 | 状态 | 影响 |
|---|---|---|
| **ffmpeg** | ✅ **已解决**（2026-10-13） | `Gyan.FFmpeg 9.0.2 full_build`，`bin` 已进**用户** PATH。⚠️ **这一项在 B5 之后不再是「全过」的判据** —— `check_deps.py` 从 15 项长到了 18 项（B6 加了 boto3 往返、OSS 缺配置、即梦缺 `req_key`），今天要全绿是 **18/18**。⚠️ 两处残留：那个 `bin` 路径里带版本号（`ffmpeg-9.0.2-full_build`），`winget upgrade` 之后会失效；用户 PATH 里这一条**重复了两遍**（无害，但别在排查 PATH 问题时被它带跑）。**坑的经过见下面「一条坏命令」** |
| **即梦 AK/SK** | ✅ **本机已填且已过网关（2026-10-16）** | `backend/.env` 里那两行现在是真值（`.env` 在 `.gitignore` 里，所以**这个仓库永远没有它们** —— 换一台机器要重填）。⚠️ **填过第一遍是错的**：最初那对是 60 位 base64 味 + 158 位 base64url，**不是火山 IAM 凭据的形状**，网关回 `InvalidAuthorization`（§2.6 第三件事 ①）。现在填的是**与 `S3_ACCESS_KEY_ID/SECRET` 同一份值**（借的，见 §8.2 第 10 条）。判定「过没过网关」的不花钱办法：`GetResult` 查一条老任务（纯查询、不计费），回 `code 10000` 即过 |
| **即梦 `req_key`（两个）** | ◐ **文生图那个已定；图生视频那个只剩「哪个产品」没定（2026-10-16）** | `jimeng_t2i_v31`（文生图）→ `10000` + 真 `task_id`，**整条从前端界面跑完过**（§2.6 第四件事 ①）。图生视频那侧**做过一次两个钥匙的对照**：`.env` 里配的 `pippit_iv2v_v20_cvtob_with_vinput` → `50430`（**并发闸门**，形状上说明它被认了），第三方文档推荐的 `jimeng_i2v_first_v30` → `50400 Access Denied`（**权限闸门**，说明**那条产品线在这个账号上没开**）。⚠️ 这两个码别再混着读：**`50400` = 没开通 / 没权限；`50430` = 开通了、但并发配额是 0**（对比表在 §2.6 第四件事 ②）。它**不在任何公开文档里，只能在控制台确认**（§18-2）。守卫是「`PROVIDER=jimeng` 而没填 → **启动即失败**」，故意的：不拦的话第一次生成会花掉一次**真调用**去换回一句「不支持的 req_key」（`app/config.py`）。清单见 §2.6 的 ②③ |
| **S3 / OSS 桶** | ✅ **读写 + 匿名读 + 浏览器可见全过（2026-10-16）** | 火山引擎 TOS：桶 `heluo`、endpoint `tos-s3-cn-guangzhou.volces.com`、公网前缀 `https://heluo.tos-s3-cn-guangzhou.volces.com`。`scripts/check_storage.py` 现在**四项全过**（写 / 读回逐字节一致 / 删 / **匿名 GET 200** —— 2026-10-15 时是 403）。⚠️ **但「匿名可读」不等于「页面能显示」**：2026-10-16 补了一条 **CORS 规则**才让 Flutter web 取到图（`Image.network` 走 XHR，需要 `Access-Control-Allow-Origin`），见 §2.6 第四件事 ③。⚠️ 见下面「真桶验出来的三件事」——其中第一件推翻了我们自己文档里写的一条建议。清单见 §2.6 的 ④ |

**一条坏命令（值得单独记，因为它把结论带反了）。** ffmpeg 那一项转绿之前，
给出的诊断是「用户和机器两份注册表里都没有它，所以重开终端也不管用」
—— **错**。真正的原因是读注册表那条命令本身是坏的：

```bash
reg query "HKCU\Environment" /v Path      # ← 在 Git Bash 里必然失败
```

MSYS（Git Bash）会把**以 `/` 开头的参数当路径改写**，`/v` 被改写成
一个 Windows 路径，reg.exe 收到的是无效语法，回一句「错误: 无效语法」
就退出了。而我把 stderr 丢进 `/dev/null`、又拿 `|| echo "(没有)"` 兜底 ——
于是**那句错误被翻译成了「注册表里查无此项」**，形状上完全不像，结论正好相反。

核实后的事实：那一条**从 winget 装好的时候起就在用户 PATH 里**，后来又被
手工加了一遍，所以现在是两条重复。也就是说「重开终端不管用」这句是错的，
**新终端一直找得到它**；当时真正的现象只是**我这个会话的环境变量早于安装**。

Git Bash 里读注册表的正确写法（三选一）：

```bash
MSYS_NO_PATHCONV=1 reg query "HKCU\Environment" /v Path
reg query "HKCU\Environment" //v Path        # 双斜杠让 MSYS 放行
powershell -c "[Environment]::GetEnvironmentVariable('Path','User')"
```

⚠️ 真正的教训不是「reg 不能信」，是 **`2>/dev/null` 配上 `|| echo 没找到`
会把「命令失败了」和「结果为空」压成同一句话**。凡是要靠「有没有」下结论
的地方，要么别吞 stderr，要么先确认命令自己跑得通。

### 6.2 代码里的已知缺口（记录了，但**没在这些批次里修**）

| 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|
| **worker 是单实例假设** | 两个 worker 同时跑会把同一条任务问两次、甚至各提交一次。`claim` 是「先 SELECT 再改状态」，PostgreSQL 多实例下要改成带条件的 UPDATE（`WHERE status='queued'` + 看 rowcount） | 想横向扩 worker 之前。v1 的部署形态是单进程，`worker.py` 的文件头写明了 |
| ~~**`scripts/` 里没有运维脚本**~~ | ✅ **B5 补上了 `scripts/create_invite.py`**（`--code` / `--uses` / `--list` / `--deactivate` / `--expires-in-days`）。**发积分仍然没有脚本** —— 今天只有 `/__test/grant`，而它只在 `TEST_MODE` 下挂着 | 第一次真实部署要「补积分给某个用户」之前 |
| **`TEST_MODE=1` 的实例不推进队列** | 跨仓门禁起的正是这种实例，所以那 43 条**观察不到** `queued → submitted`。这是有意的（后台 worker 会和 `/__test/reset` 的 `drop_all` 抢表），代价写在 `main.py` 的 `_start_worker` 里 | ~~换真 provider（B7）之后…~~ ✅ **B7 已收**：不靠换 provider，靠 **pytest 里注入的时钟** —— `worker.run_once(session, now=…)` 把「10 秒轮询窗口」直接推着走。跨仓门禁**仍然是对的行为**（它验的是端点契约，不是队列推进）。⚠️ 这一行留下的教训是「等接上真 X 就能验」这种句子**多半是假承诺**，见下面 §6.2 的收尾注 |
| **`PROVIDER=fake` 造不出 `queued`/`submitted` 的在途任务** | 前端 138 条 + 跨仓 43 条全都跑在「提交即完成」上，所以**没有任何自动化**能看见真实的排队 | ✅ **B7 已收（B5 起就收了）**：`tests/_providers.py` 的 `ScriptedProvider` 让替身也「先回执、后完成」（`polls_before_done`），`test_acceptance_b7.py` 的剧本里 `polls_before_done = 1`，于是那条路**每次跑门禁都在走一遍**。⚠️ 真·HTTP 的排队仍然没验（那要真即梦） |
| **`QUEUE_SATURATED` 没有触发条件** | 见 §3.13 第 1 条。不是漏了，是 §12 没给队列深度上限 | 要它可触发，先在 §12 补规则 |

**B4 新增的七条**（按处理优先级排，1 号最急）：

| # | 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|---|
| ~~1~~ | ~~**转存的 IO 在 DB 写事务里**~~ | ✅ **B6 做了，但只做了 worker 那一条路**：`defer_io=True` 只在 worker 路径上传，排队 → 认领 → **事务外搬运** → 新事务里结算。同步路径**刻意保持 IO 在事务里**（`test_transfer_b4.py::test_同步路径的转存失败_502_而且一整笔都不留` 靠它）。完整理由与「为什么守卫的判据是『认得见』而不是『别的连接写得进』」见 **§3.16**。⚠️ 残留：`worker.py` 在 `atomic()` 里调 `provider.poll()` 这件事**没变** —— 出队轮询仍是网络 IO 在事务里（对 fake 是空操作，对真即梦是一次 HTTP）。已知，未修 | 真 provider 上线后若观察到写锁争用，下一步是连 `dispatch` 里的 `poll` 也搬到事务外 |
| 2 | **≤4096×4096 对非图片文件不执行** | 解不出尺寸就无从校验（用户拍板的口径）。攻击面：一张 20MB 以内、声称 6 万×6 万、又**真的解不出来**的图会被存下并公开发布 —— 今天没人解它，明天「生成缩略图」这类需求一上来就有了 | 任何一次「上传的字节会被解码」的新功能之前 |
| 3 | **转存重试依赖 worker** | `TEST_MODE=1` 的实例不起 worker，那种实例上的转存失败只能等 `task_timeout_sec` 超时兜底。同步路径已经改成 502，所以**只有真 provider 那条路**会走到这里 | 要不要在无 worker 的实例上跑真 provider |
| 4 | **孤儿文件没有 GC** | 删资产会删对象，但「用户删任务」「进程死在转存中途」「同步路径回滚」留下的文件没人清 —— 存储会**单调上涨**。回调顺序是刻意的（先 commit 删行、再 best-effort 删文件），宁可留孤儿也不能留「行还在、文件没了」 | v1 不做，记录在案 |
| 5 | **不产图片缩略图资产** | Mock 只给视频配封面；给图片加一行会让 `GET /assets` 的内容变。C6 的「图片生成缩略图（Pillow）」落在**探针 + 占位封面**这条路上 | 前端要展示图片缩略图时 |
| ~~6~~ | ~~**隐式标识（写进文件元数据）不在 B4**~~ | ✅ **B5 做了**：图片 EXIF+XMP、视频 MP4 元数据，钩在 `transfer_artifact` 里 | — |
| 7 | **重试转存时重建 `ProviderResult` 与 provider 接口耦合** | ②.5 相位只从库里的 `provider_url` + `output_duration_sec` 重建结果，**丢了** `provider_task_id` 与 params。B6 之后仍然如此 —— 转存重试**不发任何 provider 请求**（产物 URL 已经落库了），所以丢 `provider_task_id` 不影响它。但它也意味着：**转存失败重试时，我们不再有任何办法回头向 provider 追问这条任务** | 若将来要做「转存失败后重新向 provider 取一次产物地址」（即梦的 URL 只活 1 小时，这是个真会来的需求），必须先把 `provider_task_id` 一起带上 |

另外一处**顺手修掉的真缺陷**（不属于 B4 的交付，是撞出来的）：
`alembic/env.py` 的 `fileConfig(...)` 用了默认的 `disable_existing_loggers=True`，
它会**永久关掉**此刻已存在的每一个 logger（包括整棵 `app.*` 树）。
后果是「跑完迁移那条用例之后，后面每一条断言日志的用例都静默失灵」——
单独跑是绿的、跑整个套件才红，排查方向会完全跑偏。已改成
`disable_existing_loggers=False`，理由写在那个文件里。

**B5 新增的六条**：

| # | 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|---|
| 1 | **`provider_calls.task_id` 的 `ON DELETE CASCADE` 对成本对账表是错的删除规则** | 删一条任务会把「我们为它打过几次接口」一起删掉 —— 而对账要的恰恰是「任务没了、钱花过」那种记录。今天只是**理论问题**：v1 没有删任务端点，用户也不能硬删 | 真要改成 `ON DELETE SET NULL` + 一次迁移。**在那之前别删任务** |
| 2 | **「被拒的调用计不计费」§18-4 仍未确认** | 直接影响 `50511` 该不该可重试（重试一次被拒的输出 = 再付一次钱） | 这正是 `provider_calls` 这张表**将来用来回答的那个问题** —— 它是工具，不是答案 |
| 3 | **过 Pillow 存一遍会丢掉 provider 原本附在产物上的 EXIF/XMP** | 对我们自己产的产物可接受；对「保留上游元数据」有要求的场景不行。两段 XMP 拼在一起没有合并语义，所以不是「顺手补一下」能解决的 | 若将来要保真上游元数据，得改成**只插不改写**的容器拼接（XMP 那段本来就是这么做的） |
| 4 | **标记失败 ⇒ 转存失败 ⇒ 任务失败** | 一个系统性的 EXIF/ffmpeg 故障会挡住**所有**交付。这是「合规优先」的代价，是**故意的**：宁可不出，也不出一份没有标识的产物 | 症状出现时用 `marking_enabled=0` 逃生门顶住（默认开，有测试钉着），然后修根因 |
| 5 | **WebP 走 Pillow 存一遍会重编码，同一张图体积差约 3 倍** | 今天**没有生产路径产 WebP**（只有 `encode_webp` 这条测试路径），所以不构成线上问题。但将来若真要产 WebP，这条路会悄悄把图片变大 | 真要产 WebP 时，改成 VP8X-flag-aware 的 RIFF 拼接（`_mark_webp` 里那段注释写明了为什么现在不这么做） |
| 6 | **入口词表挡不住同音字 / 变体字**（「炸弹」→「炸蛋」） | 这是关键词方案的**固有上限**，兜底在即梦那边的第②层审核 | 不修。测试里一个变体字用例都没写 —— 写上去只会是一条永远红、最后被改成 `xfail` 然后被忘掉的测试 |

（另外：~~⚠️ 「取回 `public_url` 能读出标识」这一条**只在测试进程里验过**，
真 uvicorn + 真磁盘上的手工验收留给 B7。~~
✅ **B7 补上了**，见下面 `### B7` 的验收记录。）

**B6 新增的五条**：

| # | 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|---|
| 1 | ~~**真桶、真网关、真即梦：一个都没碰过**~~ **2026-10-16 起碰过两轮，仍然只碰了一半** | 原文说的是「B6 交付的是我们自己这一侧自洽、五件事全是猜的」。**现在有答案的**：签名（对，`Host` 那条修过）、`req_key` 两个（都被网关认了）、产物在信封里的哪个字段（**`binary_data_base64`，内联的字节而不是地址** —— §2.6 第三件事 ④）、**以及文生图整条（提交 / 轮询 / 转存 / 落桶 / 标识 / 前端可见，§2.6 第四件事 ①）**。**仍然没答案的**：**图生视频整条**（四次提交全死在闸门前面，见第四件事 ②）、**图生视频的请求 JSON 字段名**（文生图那次回 `10000` 只证明了**那一份** body 被认）、**产物字段名只在 `jimeng_t2i_v31` 上验过** | ~~§2.6 的清单走完之前…~~ §2.6 走完之后才算。**⚠️ 别把「文生图从前端跑通了」读成「即梦这一侧接完了」**：图生视频、时长真值两件还在外面 |
| 2 | **参考图公网可达：地址这一侧已经够用，但「即梦真的取到了」仍然没验过** | `PUBLIC_BASE_URL` 填 localhost 的话，我们交给即梦的 `source_url` 指向它自己 —— 四五个环节都不报错，报出来的是一句和病因无关的错。`GenerationRequest.source_url` 是 B6 才补上的字段（在那之前**根本没有这个能力**，即梦拿不到参考图） | **⚠️ 口径 2026-10-16 更新**：`STORAGE=oss` 之下这条路**不用走了** —— `source_url` 取的是 `Asset.public_url`，而 OSS 下它就是桶的公网地址（匿名打得开），**不需要域名也不需要公网 IP**（§2.6 第四件事 ④）。**但那一格仍然没关死**：四次提交都死在闸门前面，**即梦有没有真的把那张图取下来，谁都没看见**。`STORAGE=local` 下原来那三关仍然成立：公网 IP 真可从外网打、端口放行、以及**它会变**（宽带重拨就换） |
| 3 | **`S3Storage.put_file` 是单次 PUT，不是分片上传** | `MAX_ARTIFACT_BYTES` 是 200MB，单次 PUT 对绝大多数桶够用，但超过桶的单对象 PUT 上限（S3 是 5GB，OSS/COS 各有各的数）会**在真桶上**失败 —— 而本地的替身**永远绿**。真到那一步的表现是一次 `EntityTooLarge`，不是超时 | 真要收 200MB 以上的产物时改 multipart。今天 `MAX_ARTIFACT_BYTES` 就卡在 200MB，所以先记着 |
| 4 | **`provider_calls.task_id` 级联删**（同 B5 第 1 条，B6 起更值钱了） | B5 时它是个理论问题；B6 之后这张表里开始有**真花钱**的行（`req_key`、`resp_code`、`latency_ms`），而删一条任务会把它们一起带走 | 同上：要改是 `ON DELETE SET NULL` + 一次迁移。**在那之前别删任务** |
| 5 | ~~`S3_FORCE_PATH_STYLE` 选错的表现是 DNS 解析失败~~ **2026-10-15 在真桶上验了，原文只对一半，而且代码里那个「关」是空的** | 两个方向形状不同：该 virtual 却给了 path → `InvalidPathAccess`（TOS 实测）；该 path 却给了 virtual → 才是 DNS 解析失败。**更严重的是 `False` 原本映射成 `auto`，而 `auto` 实测等于路径风格** —— 于是关掉开关这个动作在真桶上什么都没做。已改成 `False → "virtual"`，并加了一条断言钉住。详见 §2.6 下面那次实测 | ~~第一次配真桶时~~ ✅ **已修并已验**（`scripts/check_storage.py`）。**残留**：OSS / COS / MinIO 那几家「路径风格」的说法仍然**没人在真桶上验过** |

（另外记一笔：**B6 顺手修掉了一个真缺陷** ——
`_create_assets_for` 调的是**模块级** `storage.public_url_for`，写死 `/media/`。
`STORAGE=oss` 下它会拼出本地路径形状的地址，而生成、扣费、落库全都正常 ——
只有用户点开作品时是 404。改成走 Storage 实例的 `url_for`，与 `assets.py` 对上传的处理一致。
守卫见 §2 的 B6 那张表和 §3.14。）

**B7.3 新增的两条**（都是「内联产物」这个交付形态带出来的）：

| # | 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|---|
| 1 | **`spool/jimeng/` 里的产物没有 GC**（叠加在 B4 第 4 条「孤儿文件没有 GC」之上）| 每成功一条即梦任务，就在**应用服务器的本地磁盘**上留一份**完整尺寸**的产物（这次是 121 KB，视频会大得多）。它不是对象存储里的对象，所以**不产生桶账单，只涨本地磁盘** —— 而转存成功之后那份 spool 文件其实已经没用了（字节已经在桶里）。文件名是确定性的（即梦 task id），所以重复 poll 不会堆积，但**不同任务之间是只增不减的** | 真即梦开始有量之前。最省事的做法是在转存成功之后删掉那一份（但要小心：转存重试还会需要它，所以得等 `transfer_state=done` 之后再删）|
| 2 | **内联交付把内存峰值抬到了产物体积的两倍多** | 即梦把整个产物 base64 塞在 JSON 里，于是 `response.json()` 已经持有一份完整字符串。`MAX_ARTIFACT_BYTES`（200MB）**在解码前后各判一次**，所以磁盘和「解码后的字节」都被闸门管住了 —— 但**解码那一刻的峰值**（≈「4/3 倍的 base64 字符串」+「完整 bytes」）没有任何东西在限它 | 若把 `MAX_ARTIFACT_BYTES` 调大，或某个 req_key 开始回大体积视频。真到那一步要改成**流式解码 + 边解边写文件**，而不是一次 `b64decode` |

**2026-10-16 那一轮（前端真跑 + 前端可见）新增的两条**（这一轮 `app/` 一行没改）：

| # | 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|---|
| 1 | **桶上的 CORS 规则成了一条「隐性依赖」** | 后端每一处都是对的（桶匿名可读、`public_url` 永久、`GET /media` 200），**只有浏览器里的 Flutter web 取不到图**。而 `scripts/check_storage.py` 查的是**匿名 GET**（它只能 `curl`，没有同源策略，**看不见 CORS**）—— 也就是说**现有闸门对这条规则完全没有覆盖**，删掉它一切照旧通过 | 换桶 / 换 CDN / 上线到真域名时**手动确认这条规则还在、且覆盖新 origin**（§2.6 第四件事 ③ 有诊断入口与回退方式）。想做自动化的话，判据是「`GET` 对象时带 `Origin` 头，响应里必须有 `access-control-allow-origin`」—— 这是**唯一**能发现它的断言 |
| 2 | **「图生视频那条产品线的并发是 0」是一个账号侧事实，代码里没有任何东西能表达它** | 四次提交全部 `50430`，而我们的错误码一律压成 `PROVIDER_ERROR` + `retryable`，于是**四次重试全都白打**（每次都撞同一堵墙），16 行 `provider_calls` 换回一个和后端毫无关系的答案。用户看到的是一句「生成失败，请重试」，而重试**永远不可能成功** | 火山那边把并发买到 ≥1 之后**就不再会触发**，所以**不修代码**；但下一轮若再遇到「重试永远失败」的形状，先去看 `resp_code` 是 `50400` 还是 `50430`，别先怀疑重试逻辑（§2.6 第四件事 ②）。真要产品化，应该在**启动时**探一次能力（一条不计费的 `GetResult`），把「这个账号没这个能力」拦在提交之前 |

⚠️ 这一条**被 B7.4 换掉了通道、但没有被解决** —— `b7.4` 让图生视频改走
MiniMax 绕开它（那才是本批的目的），而**火山那边的配额仍然是 0**。
也就是说：今天两路并存，其中视频那一路是新的、没验过的（见下面 B7.4 那张表）。

**B7.4 新增的五条**（图生视频换通道带出来的；2026-10-17 真跑了一遍之后逐条更新）：

| # | 缺口 | 影响 | 什么时候必须处理 |
|---|---|---|---|
| ~~1~~ | ~~**MiniMax 能不能把我们桶里那张参考图下下来**~~ | ✅ **2026-10-17 关掉了**。判据不是「提交回了 200」（那只证明它收下了 URL），而是**成片的首帧就是我们那张图**：参考图是一张带橙色对角线与白色方块的渐变图，成片第 0 帧与它逐像素一致，之后各帧的平均像素差 0 → 13.35 → 29.46 → 30.97 单调变化。⚠️ **即梦那边同一个空位仍然空着**（§6.2 的 B6 第 2 条）—— 别把这条关掉读成「两家都能取到」 | — |
| ◐ | **MiniMax 的文档字段名与实际是否一致** | ◐ **提交体与查询响应都对上了**（`task.content.url`、`task.duration`、`status` 五态里见过 3 个、HTTP 200 的信封形状）。⚠️ **仍然没见过的**：`failed` / `cancelled` 的响应形状、`error.message` 末尾那串 `(\d+)` 内部码的**真样本**、以及文生视频的 `ratio` 分支。即梦上一次（B7.3）正是在这一段上翻的车 —— `binary_data_base64` 是实测撞出来的，不是文档里读出来的。`tests/test_minimax.py` 打的是 `httpx.MockTransport`，它证的是「给定这种响应我们处置对」，**不是**「它真会这么回」 | 撞上 `failed` / `cancelled` 的那一天。判据：看 `provider_calls` 里的 `resp_message` |
| 3 | **MiniMax「输出之后才判不合规」那个内部码是多少 —— 不知道，所以它会白试三次** | `MINIMAX_CODE_MAP` 里**刻意没有猜的条目**。即梦那边这类是 `50511`，MiniMax 大概率有一个对应号，而 `1026`（文档里逐字给出的）是**输入**侧的。猜错的代价不对称：若猜的那个号其实表示「对方服务忙」，我们会把瞬时故障判成 `rejected` —— 而 `rejected` 在界面上是**「内容违规」**，等于平白指控用户 | 真见到那个号了再补进 `MINIMAX_CODE_MAP`（`app/services/moderation.py`）。在那之前它落到「未收录 = 可重试」，也就是**多花两次钱**，方向是安全的那一侧 |
| 4 | **`schemas.VideoGenIn.duration` 接口层仍然没有上下界** | H3-Max 只吃 5~15 秒，而 `{"duration": 4}` 在接口层是**合法**的（`int = 5`，没有 `ge`/`le`）。前端只发 5 / 10，所以线上碰不到；本批只在 provider 里响亮失败（一行判断、**不花真调用**、提交前就炸） | 给契约加 `ge=5, le=15` 是**契约变更**，要前后端一起动，所以本批**没加**。何时处理：下一次动 `schemas/` 那个文件时顺手（在那之前接口层的 400 由 provider 兜着，形状是 `PROVIDER_ERROR` 而不是 `INVALID_REQUEST`）|
| 5 | **`PROVIDER_MAX_CONCURRENCY` 是一个全局数、按 kind 分开计** | 换通道之后，MiniMax 与即梦**共用「视频」那一档配额** —— 一个跑即梦视频的部署和一个跑 MiniMax 视频的部署会互相挤。这是**既有设计**（B3 就是这样），B7.4 没动它 | 两路视频真同时在跑之前。到时候要么按 provider 分档，要么承认「同时只该开一路」 |

---

## 7. 铁律（项目级约束，不是本仓库的偏好）

- **AK/SK 只从环境变量读**，绝不写进 `.py`、绝不进 git。开发与生产用
  **不同**的密钥。提交前过一眼 `git diff --cached`
- **AI 生成内容必须有「AI 生成」标识** ——《人工智能生成合成内容标识办法》
  规定的**法律义务**。前端负责可见角标，**后端负责隐式标识**
  （把生成信息写进文件元数据）
- **v1 没有充值 / 支付 / 购买。** 不建任何相关接口。前端有一条守卫测试
  扫 `lib/` 的非注释行找这些词
- **任务状态不放在进程内存里。** 全部落库，否则重启就丢
- **绝不把 provider 的产物 URL 当资产真相**（即梦的只活 1 小时）
- **`/__test/*` 必须硬门禁在 `TEST_MODE`** —— 它能造积分、能删库
- 前端 `lib/theme/*`、`app_background.dart`、`glass_card.dart`、
  `section_title.dart`、`placeholder_body.dart` **不得修改**；
  不许新增颜色值；生成按钮下**不许写确定的积分数字**（§13.4）
- 前端页面只 `ref.watch(xxxRepositoryProvider)`，**绝不**直接构造
  Repository 或调 `ApiClient`

---

## 8. 待你（人）拍板的

### 8.1 已拍板（2026-10-13，项目所有者）

三条从下面的待办里划掉。**每条都留了「为什么这么定」和它的后果** ——
否则下一个人看到结果只会觉得是漏了，然后「顺手补上」。

| 原条目 | 决定 | 落地含义 |
|---|---|---|
| §18-1 实名义务 vs 邀请制 | **先不管** | 维持邀请制，不引入实名。⚠️ 法律风险**没有被消解，只是被有意推迟** —— §6.3 那句「不能由工程判断拍板」仍然成立，将来真要接实名时它还是同一个洞 |
| 是否把可见水印烧进成片（§10.1） | **不烧** | 于是**下载/分享出去的成片只有隐式元数据、没有可见标识**。⚠️ 这**不减免**另外两条：《标识办法》要求的**前端界面「AI 生成」角标**、以及**后端把生成信息写进文件元数据**，仍然无条件做。放弃的只是「把标识烧进文件本身」这一层 |
| `DURATION_SLACK_SEC` = 3（§18-2） | **维持 3，这次不动** | 冻结额就按 `(5+3)×4 = 32` 走。⚠️ `.env.example` / `config.py` / `providers/fake.py` 里那三处「**占位值**，等 B0.5 实测修正」**仍然是对的**（B0.5 确实没跑），别看到这条就把它们改写成「已定稿」 |

~~另外一条调度决定，值得单独记：**即梦 AK/SK 项目所有者决定留到项目收尾时
再填**（口述：「留到项目快完成时我自己填」）。~~

⚠️ **这条已经执行完了，别再照着它办**（2026-10-15/16）：密钥填了、
`PROVIDER=jimeng` 起过、真文生图打过一枪（§2.6 第三件事）。
**「不要催 AK/SK」这句话现在是过期的**，留在这里只是为了让下一个人
明白为什么 B0–B7 的文档里到处写着「等凭据」。

不过它连带的两件事**确实**还没答案，仍然成立：§18-4（审核被拒是否仍计费）与
§18-2（时长余量真值）—— 前者要一次**被拒**的真调用，后者要一次**真视频**。

### 8.2 仍然待你拍板（编号沿用原表，所以是 2 / 3 / 5 / 7）

2. **§18-4 审核被拒的任务即梦是否仍计费** —— B0.5 实测。**若计费，
   退款政策与日配额都要收紧**。
   ⚠️ **B5 之后这个问题的答案有地方找了**：`provider_calls` 从 B5 起
   每次调用都留一行，所以「被拒的那次到底打没打、打了几次」在库里查得到 ——
   **这张表就是为回答它建的**。另外 `50511` 在 B5 被定成**不可重试**
   （理由正是「重试 = 再付一次钱」，而这个问题还没答案），见 README
3. **转存重试耗尽后是否退积分** —— 用户付了钱没拿到可用的东西，但我们被计费了
5. **`MAX_CONCURRENT_TASKS` 与日配额的具体值** —— 这是钱
   （§8.2：扩容 ¥500/日/并发）
   **⚠️ B3 之后这里多了一个旋钮**：`PROVIDER_MAX_CONCURRENCY`
   （出队闸门，§8.2）**也是钱**，而且和上面那个是**两个方向** ——
   上面那个限「一个人同时开几个」，这个限「整个平台同时压几个给即梦」。
   两者默认都是 1，看着像同一个数，见 `config.py` 里那段说明。
7. **产品名**（§18-5，前端留了 `isPlaceholderName` 钩子）

**B6 新增的两条（编号从这里往后是新的，原表到 7 为止）**：

8. **即梦的两个 `req_key`** —— `JIMENG_REQ_KEY_IMAGE` / `JIMENG_REQ_KEY_VIDEO`。
   代码里写的是候选值（`pippit_iv2v_v20_cvtob_with_vinput` 那个系列）。
   ◐ **2026-10-16 起半边有答案**：文生图那个**被网关认了也真跑通了**
   （`10000` + 真 `task_id` + 一张交付到界面的图）；图生视频那个**做了一次
   两个钥匙的对照** —— `.env` 里这个回 `50430`（并发闸门），文档推荐的
   `jimeng_i2v_first_v30` 回 `50400 Access Denied`（权限闸门，
   说明**那条产品线没开**）。**仍然要人去控制台确认的是「它们各自对应哪个
   模型、单价多少」** —— 文档里没有一张公开的「`req_key` ↔ 能力 ↔ 单价」
   对照表，而它同时决定了**走哪个模型**和**花多少钱**。怎么在不花钱的前提下
   把「签名错了」和「`req_key` 错了」分开，见 §2.6 的 ②；怎么把「没开通」和
   「开通了但并发是 0」分开，见第四件事 ②。
9. ~~**S3 桶的三件事**：桶名、**永久公网前缀**（`S3_PUBLIC_BASE_URL`）、
   以及桶的读权限。~~ ✅ **三件都落地了（2026-10-16）**：桶 `heluo`、
   公网前缀已填、桶**匿名可读**，而且**浏览器里真的看得见作品图**了。
   ⚠️ 落地时才发现还有**第四件**：桶上必须有一条 **CORS 规则**，
   否则 Flutter web 的取值（XHR，不是 `<img>`）会被浏览器整个挡掉 ——
   表现是**桶里有图、`curl` 也 200、页面上只有一个加载占位**
   （§2.6 第四件事 ③）。这条规则是**新增的、可回退的**，但它**没有自动化覆盖**
   （见 §6.2 那条新缺口）。

   > **原文里那段「如果你们的口径是「桶绝不能公共读」，那 §3.14 要重新拍一次」
   > 已经不再是待决项**：桶**已经**是匿名可读的（2026-10-15 之后某个时刻改的），
   > 于是 §3.14 那条「永久地址、不带鉴权、不用预签名」的选择**被现实背书了**。
   > 留一句在那里的理由：**这是本项目对外暴露面里最大的一块** ——
   > 任何人拿到 `public_url` 就能永久取到那个文件。想收回去只有两条路：
   > 桶改私有 + CDN 回源（那 `public_url` 就不再是永久地址，
   > §3.14 与跨仓 live 门禁里的「永久地址」那条断言要一起改），
   > 或者接受现状并靠「地址不可猜」当唯一的屏障。**现在选的是后者，没写下来过。**

**B7.3 新增的一条**：

10. **即梦要不要单独申请一把专用密钥？** 今天 `.env` 里 `JIMENG_AK/SK`
    填的是**与 `S3_ACCESS_KEY_ID/SECRET` 同一份值** —— 因为它们是同一个
    子账号，而那一对本就已被证明有效（桶里的对象就是它传的）。
    这么填能跑，但有三个问题，都要人来拍：

    - **一次轮换要改两处**，漏一处的表现是「生成突然全挂，而桶里好好的」；
    - **职责没有边界**：那把钥匙既能读写整个桶，又能调生成接口，
      任何一处泄漏都是全量的（最小权限原则下这本来就该拆）；
    - **铁律要求开发与生产用不同的密钥**，而今天开发和生产会共用这一对
      （除非生产环境另填 —— 那也正是「改两处」那条）。

    要拆的话：去火山控制台给即梦建一个**只带 CV 权限**的子账号/密钥，
    填进 `JIMENG_AK/SK`，`S3_*` 那一对保持不变。**代码不用改一个字**
    —— 两对本来就是分开读的（`app/config.py`），这也是当初把它们分成
    两组配置的原因。

**2026-10-16 那一轮新增的一条（编号接着往下写）**：

11. **图生视频那条产品的「并发」要不要买？** —— 这一条**是钱**，而且它
    现在是**图生视频整条链路上唯一的拦路虎**。

    - **现状**：控制台 `已开通API列表` 里，「即梦AI-图片生成」= **1 并发**、
      「智能生视频Agent-Seedance 2.0 fast 720p 有参考」= **0 并发**。
      0 并发的表现不是「慢」，是**每一次提交都被回 `50430`**（§2.6 第四件事 ②）。
    - **要拍的**：① 买不买（花多少、按日还是按月）；② 买**哪个**产品 ——
      我们的 `.env` 里配的是 `pippit_iv2v_v20_cvtob_with_vinput`，
      而**公开文档里查不到一张 `req_key ↔ 产品 ↔ 单价` 的对照表**，
      所以「买哪个」这件事只能对着控制台的产品名来定（§8.2 第 8 条）。
    - **不买的后果**：图生视频这个功能**在真 provider 下完全不可用**，
      但**每一个想用它的用户都会先被冻结 32 积分、再被全额退回** ——
      钱不丢，换个用户看得见的「生成失败，请重试」，而重试永远不会成功。
    - **买了之后仍要验三件**（一次真提交能同时回答）：
      即梦**能不能取到我们给的参考图**（§6.2 的 B6 第 2 条）、
      **视频的请求体字段名对不对**、以及**返回的真实时长** ——
      最后一件决定 `DURATION_SLACK_SEC`（现在是占位值 3，§18-2）。
    - ⚠️ **别用「再试一次」当验证手段**：已经试了 16 次，16 次都是同一堵墙。
    - ⚠️ **2026-10-17 补**：这一条**已经被绕开了、但没被解决** —— B7.4 让
      图生视频改走 MiniMax（§2.7），所以「不买」不再等于「这个功能不可用」。
      **但上面那三件要验的事一件都没少**，只是换到了 MiniMax 那一路上去问
      （见 §2.7 的清单与 §6.2 的 B7.4 第 1、2 条）。
      要不要买仍然是**你的决定**：买了就等于回到即梦这条**已经被验过一半**的路。

**2026-10-17（B7.4）新增的一条**：

12. **MiniMax 那个「按量购买 API」买不买？** —— 也是钱，而且是**这一批
    唯一挡在真验收前面的东西**。

    - **现状**：代码、配置、测试都就位了，**密钥由你亲自填**（§2.7 的清单
      第 ① 步）。而 `MINIMAX_API_KEY` 填进去之后，第一次提交**仍可能**
      拿回一个 `402` / `1008`（余额·额度类）—— 因为文档明写 H3 / H3-Max
      **需要先在开放平台「按量购买 API」**，那不是代码能替你处理的事。
      ✅ **2026-10-17 实测：这个账号已经买过了** —— 第一次提交就回 200 +
      真 `task_id`，没撞任何额度闸门。⚠️ 但这**不能推广到别的账号**，
      新账号第一次提交仍可能是 402 / 1008。
    - **要拍的**：买多少额度、以及**用哪一档模型** —— H3 支持 4~15 秒，
      H3-Max **只支持 5~15 秒**；本批默认填 `MiniMax-H3-Max`（前端只发
      5 秒 / 10 秒，两档都装得下）。换档不用改代码，改
      `MINIMAX_VIDEO_MODEL` 一行。
    - ⚠️ **本批**没有**碰定价**：H3-Max 的真实单价与「4 积分/秒」之间的
      差额是一个**独立的定价决策**（§2.7 的「不做什么」第一条）。
      在那之前，平台会按 MiniMax 的真实账单付钱、按 4 积分/秒收用户的积分 ——
      **这两个数今天没有任何东西在保证它们对得上**。

---

## 9. 可复用的现成资产

| 资产 | 用途 |
|---|---|
| §2.4 的「B3 手工验收剧本」 | **真进程级**的检查。测试覆盖不到的东西（线程到底起没起、日志到底打不打得出来）只有它抓得到 |
| `backend/tests/_providers.py` | `ScriptedProvider` —— 想验队列/重试/审核拒，用它，别去动 `FakeProvider`（那是契约的一部分） |
| `backend/scripts/check_storage.py` | 对着**真桶**打写/读回/匿名 GET/删（几十字节的探针对象，不碰用户数据）。换桶之后先跑它 |
| `G:\AIVideo\_local_oss_check\` | **B7.3 的一次性探针**（不在任何一个仓库里，所以不会被误提交）：`verify_env_creds.py` 用**纯查询**验一对凭据过不过网关（不花钱）、`probe_result.py` 把一条即梦任务的原始信封打出来、`probe_official.py` 拿**火山官方 SDK** 对同一个请求算签名（当对照组用）。⚠️ 里面有 `serve_live.py`，那是「`.env` 还没填好」时代的临时顶替手段，**现在 `.env` 填对了，别再用它** |
| `flutter_application_1/lib/data/mock/fake_api_client.dart` | **可执行的规格**。后端要逐字对齐 |
| `flutter_application_1/test/repository_layer_test.dart` | 最高价值的契约门禁 |
| `flutter_application_1/HANDOFF.md` | 前端的批次历史与 §3.1 的赠送额裁决 |
| `G:\AIVideo\_acceptance\` | CDP 驱动器与剧本（坐标要按真后端重算） |
| `G:\AIVideo\工程文档.md` | 裁决文档。§11 数据模型 / §12 接口契约 / §15 执行卡 |
