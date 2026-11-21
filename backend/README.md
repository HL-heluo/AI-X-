# AI 视频创作平台 · 后端 v1

FastAPI + SQLAlchemy 2.0 + Alembic + SQLite（→ PostgreSQL）。

接口契约的唯一出处是 `G:\AIVideo\工程文档.md` §12；本仓库不重新定义契约，
只实现它。**前端 v1 已冻结**，所以契约上有歧义时，一律以冻结的前端为准
（可执行规格：`flutter_application_1/lib/data/mock/fake_api_client.dart`）。

---

## 批次进度

每批一个 tag，过不了门禁不进下一批（照前端 B0–B7 的做法）。

| 批次 | 交付 | tag | 状态 |
|---|---|---|---|
| B0 | 仓库骨架 + 依赖闸门 + `/health` + `/docs` + Alembic 初始化 | `b0-skeleton` | ✅ 依赖闸门当天 15/15（ffmpeg 于 2026-10-13 补上）。**闸门项数后来长到 18** |
| B1 | 7 张表 + 约束 + 首次迁移 + 8 个状态枚举 | `b1-schema` | ✅ |
| B0.5 | 即梦 Spike S1–S4 | — | ⏸ **有意排到项目收尾**：AK/SK 由所有者那时自己填（HANDOFF §8.1）。⚠️ **2026-10-15/16 凭据已填并已打过一枪**（`b7.3`），但 B0.5 那四项（主要是**时长余量真值**）仍然要一次真视频 |
| B2 | 12 个端点 + 响应形状 + 错误码 + 记账 + fake provider | `b2-endpoints` | ✅ 125 条测试 |
| B2b | 跨仓契约门禁（**只动前端 `test/`，没动 `lib/`**） | `b2b-live-gate` | ✅ 真后端 41 条 + Mock 138 条 |
| B3 | `services/queue.py` + `worker.py`（跨时间的真排队） | `b3-queue` | ✅ 148 条测试 + 真进程手工验收 |
| B4 | 真字节产出：落盘 / 缩略图 / ffmpeg 抽帧 / 转存（§9.2–9.4） | `b4-bytes` | ✅ 201 条测试 + 真进程手工验收 |
| B5 | 合规与成本：入口审核 / AI 生成隐式标识 / `provider_calls` 对账（§10） | `b5-compliance` | ✅ 273 条测试 + Mock 138 + 跨仓 live 22 |
| B6 | 真外部适配层：即梦（签名 / 两段式 / 审核码）+ `S3Storage`（§9.1） | `b6-providers` | ✅ 333 条测试 + check_deps 18/18 + 跨仓 live 24。⚠️ **真凭据未填，所以真桶/真网关一次都没碰过** —— 见 HANDOFF §2.6 的验收清单 |
| B7 | §15.1 端到端自动化 + 真进程验收（**只加了一个测试文件，`app/` 一行没改**） | `b7-acceptance` | ✅ 339 条测试 + 真进程验收（含**重启后仍取回标识**）。跑的是 `fake` + `local`，真凭据按 §8.1 有意留到最后 |
| B7.3 | 真凭据那一侧的**第一次实弹**修回来的三件事：凭据类型、`Host` 进签名、**产物是内联的字节而不是地址** | `b7.3-inline-artifact` | ✅ 351 条测试 + check_deps 18/18 + 用**真网关的响应**验完整条交付链。⚠️ 图生视频、`PUBLIC_BASE_URL` 公网可达、时长真值**仍未验** —— 见 HANDOFF §2.6 第三件事（**其中「公网可达」的口径已被第四件事改写**）|

**到这里，后端「规格已定」的部分全部做完。** 真凭据那一侧已经从
「一次都没碰过」变成「**文生图从前端界面整条跑通**」—— 但**没有走完**：

- **图生视频一步都没成，而卡点不在代码里**：账号里那个产品的**并发配额是 0**，
  每次提交都被回 `50430`。要人或钱去解（HANDOFF §8.2 第 11 条）。
- **2026-10-16 那一轮（没改 `app/` 一行）的完整记录在 HANDOFF §2.6 的
  「第四件事」**：`50400` 与 `50430` 两个码怎么分工、桶上那条 **CORS** 规则
  （没有它，Flutter web 里就是看不见图）、以及参考图公网可达这一格的口径更新。
- **仍然空着的**：图生视频整条、`DURATION_SLACK_SEC` 的真值。

剩下的**必须由人来做**（凭据只从环境变量来、不进仓库）。

B1 定的几件事（改之前先读）：

- **主键一律 INTEGER**，不用 UUID —— 前端四个模型都走
  `requireInt(json['id']).toString()`，字符串会抛。
- **`users` 多一列 `username_canonical`**，唯一索引建在它上面。
  直接给 `username` 建唯一索引的话，`Bob` 和 `bob` 会是两个账号，
  而用户在另一台设备上打字习惯一变就**登录也失败、注册也失败**
  （他会被告知「bob 已被占用」，而占用它的是他自己）。
- **`invite_codes.created_by` 故意没有外键**。它和 `users.invite_code_id`
  构成循环外键，SQLite 上侥幸能跑、PostgreSQL 上会直接失败 ——
  详见 `app/models.py` 里那一段。
- **`tasks` 有一条 `succeeded ⟹ settled_amount IS NOT NULL` 的约束**。
  「成功」是唯一一个用户真的拿到了东西的终态，它没有结算额就意味着
  「东西给了、钱没记」，而对账时这种任务查不出来（NULL 不参与求和）。
- **时间列一律走 `app.types.UtcDateTime`**。它挡的是一个
  静默偏差 8 小时、而前后端各自的测试全绿的 bug —— 详见那个文件的开头。

B2 定的几件事（改之前先读）：

- **事务边界在 service 层，不在 `get_db`。** `get_db` 只负责关会话。
  写路径在 `services/*` 里自己 `commit`（都经过 `atomic()` 上下文）；
  出错就抛 `AppError`，会话不 commit，连接关闭时自动回滚 —— 用户看到
  「积分不足」时，余额、冻结、任务、流水**一个都不能动**。
  顺带一条：**不要写 `with session.begin()`** —— `get_current_user` 的
  SELECT 会先 autobegin，随后 `begin()` 抛 `InvalidRequestError`。
- **`POST /generation/*` 提交即完成。** fake provider 在**同一个事务**里
  走完 `pending → queued → submitted → succeeded` + 结算 + 退回 + 落资产，
  响应直接是 `status:"succeeded"`。跨时间的真排队是 B3；届时要换的只是
  `provider.submit`，调用方那层不用动 —— 这正是 §12.2 把它收成 Protocol 的意义。
- **资产 URL 是拼出来的，背后没有文件。** `public_url` 指向 `/media/...`，
  但 B2 不写任何字节，所以浏览器里图是裂的（缩略图的 `size_bytes` 是
  `null`）。这与今天 Mock 的 `mock-oss.local` 行为一致，真字节产出是 B4。
  **别把它当 bug 查。**
- **错误码只从 `app/enums.py` 的 `ErrorCode` 引常量**，不许写字面量；
  错误体顶层就是 `{code, message}`，**不加任何统一包装的中间件**。
- **缺必填字段走 `400` + `INVALID_REQUEST`**（体仍是顶层 `{code, message}`）。
  **不是** FastAPI 默认的 422 —— 那个形状会破「无信封」契约（前端从顶层读
  `code`/`message`，读到两个 null），而且 422 在本项目里另有主人
  （`CONTENT_REJECTED`）。翻译点在 `app/errors.py` 的 `RequestValidationError`
  处理器。它是**调用方 bug**，不该假装成业务错误码；业务校验（空提示词、超长）
  必须在 service 里显式抛 `INVALID_PROMPT`（前端认它，会说得具体）。
- **注册返回 `201`**（创建资源），其余 200。前端的成功判定是区间，所以无差别 ——
  但别看到 201 以为出错了。

B3 定的几件事（改之前先读）：

- **队列就是 `tasks` 表本身，没有第二个数据结构。** §4.1 不引入 Redis/Celery，
  理由见 `services/queue.py` 开头（那是算术，不是品味：只要一道信号量）。
  出队 = 一条带顺序的 SELECT，入队 = 一次状态更新。
- **出队顺序和排队位次必须用同一个键：`(queued_at, id)`。** 两处一旦分岔，
  「前面还有 3 个」就成了一句谎话 —— 位次按 A 排、出队按 B 走。
  两个函数就放在同一个文件里，为的是这个约定有个看得见的位置。
  **键不是 `created_at`**：退避是把 `queued_at` 推到未来实现的，用
  `created_at` 的话被退避的任务会永远排在最前，变成一次空转的忙等。
- **退避 = 把 `queued_at` 推到未来，不是 `sleep`。** worker 是单线程的，
  sleep 5 秒等于全平台停摆 5 秒。推到未来只影响那一条任务，而且它**自动落库**
  （进程重启退避还在）。
- **`ProviderResult.done` 是 B3 加的必读字段。** `submit` 回来不等于做好了：
  fake 当场给成品（`done=True`），即梦只给一张带句柄的回执（`done=False`）。
  漏判的表现是**把一张还没有产物的回执当成成品结算掉** —— 钱扣了、资产记录
  落了、文件根本不存在。**别用 `output_duration_sec == 0` 代替它**：
  文生图的成片时长本来就是 0。
- **`provider_max_concurrency`（§8.2 闸门）和 `max_concurrent_tasks`（§7.5
  入口闸）是两个数，别合并。** 一个管「整个平台压几个给即梦」，一个管
  「这一个人同时能开几个」。合并之后，「给单个用户放宽一点」会顺手把整条
  provider 通道打爆，而账单要到月底才看得出来。
- **`/tasks` 的 `queue_position` 只在 `queued` 时有值**（B2 就定了），
  B3 起这个状态**真的会持续一段时间** —— 于是「排队中取消，全额退回」
  （§7.4）第一次成为可达路径。
- **收尾逻辑只有一份。** 请求路径和 worker 两个入口都走
  `generation.finish_succeeded` / `handle_failure` / `expire_stale`。
  两边各写一份的后果不是代码重复，是它们会在「先退冻结还是先扣余额」
  这类细节上分岔 —— 而分岔之后余额总数还是对得上，是流水里的
  `balance_after` 快照对不上，那时已经查不清是哪一条写坏的。

B5 定的几件事（改之前先读）：

- **入口审核闸在余额校验之前**，于是**零余额 + 违规提示词拿到的是 422
  `CONTENT_REJECTED`，不是 `INSUFFICIENT_CREDITS`**。这是有意的：它在任何
  写库之前、且比后面每一步都便宜，所以「被拒的提交一个数字都不动」天然成立。
  告诉用户「你没钱了」会让他去充值，而充完还是发不出来。有测试钉住这个顺序。
- **`50511`（输出后审核）判 `rejected` 且不可重试，这是对 §9 那张表的
  有意偏离。** §9 的重试列给它打了勾，§7.4 / §7.5 与执行卡 C11 说审核类一律
  rejected + 全额退回 —— 取后者：重试一次已经被判不合规的输出就是**再付一次钱**，
  而「被拒的调用是否计费」§18-4 恰恰还没确认。**改这个值之前先读
  `app/services/moderation.py` 里 `JIMENG_CODE_MAP` 上那段注释。**
  （B7.x 起那张表改名成 `JIMENG_CODE_MAP` —— MiniMax 接进来后有了**第二张**
  表，而两张表的键不是同一种东西：即梦的是它信封里的 `code`，MiniMax 的要从
  `error.message` 末尾的括号里抠。合表会让两家的号互相覆盖，而覆盖是静默的。）
- **`provider_calls` 的审计行必须等事务落定后再冲刷，不能同事务插。**
  `generation.submit` 在外层事务里**持着 SQLite 的写锁去发 HTTP**，第二个连接
  此刻写 `provider_calls` 会在 `busy_timeout` 上自己等自己。更根本的是语义：
  这张表存在的意义就是记下「我们打了接口、对方拒了、而我们因为回滚没留下
  任何业务痕迹」的那一次调用 —— 同事务插的话，它恰好是被回滚掉的那一行。
  所以：**事务外、独立会话、`task_id` 传 NULL**（回滚后那个 id 在库里不存在，
  拿它去写外键会在 `PRAGMA foreign_keys` 没开的连接上静默成功，于对账表里
  多一条指向空气的记录）。
- **审计是 best-effort，这是硬要求不是偷懒。** 审计子系统出任何问题（库锁了、
  盘满了、表被删了）都只记日志，**不许**把一次正常的生成变成 500 —— 同
  `assets.delete_asset` 吞掉删文件异常的那条纪律。冲刷失败之后待冲队列**清空且不重试**：
  「写不进去」通常正是库层面的问题，留着让下一次连同上次一起重试只会滚雪球。
- **审计表里不存签名地址。** provider 报错常把带签名的产物地址原样回显，落库
  就等于把签名存下来了（`provider_url` 那条铁律射程里包含这张表）。先按
  `https?://\S+` 换成 `<url>`，再截断到 ~200 字符 —— 对方可以回一屏 HTML 错误页。
- **隐式标识是法律义务，所以失败策略是「合规优先」**：`apply_marker` 出错 →
  `TransferFailure(retryable=True)` → 转存重试 → 耗尽后任务 `failed` + 全额退款。
  **宁可不出，也不出一份没有标识的产物。** `marking_enabled` 是逃生门，
  默认开，有测试钉住它默认是开的。
- **标记一个像素、一个码流比特都不许动。** 图片走容器字节拼接（PNG `iTXt` /
  JPEG APP1 / WebP VP8X），视频走 `-c copy` 只改元数据容器。这不是「应该不会变」，
  是**被证明**的：`transcode.image_digest`（解码后 RGB 的 sha256）和
  `transcode.video_stream_digest`（`-c copy -f md5`）就是为这件事存在的。
- **上传的参考图不带标识，这是结构决定的，不是运行时开关。**
  `assets.store_reference_image` 根本不经过 `transfer_artifact`，所以想标也标不到 ——
  一个守卫测试（改坏上传路径 → 变红）钉住它。别为了「统一」把两条路合并。
- **过 Pillow 存一遍会丢掉 provider 原本附在产物上的 EXIF/XMP。** 这是**有意的行为**，
  不是 bug：我们要写的是自己的标识，而两段 XMP 拼在一起没有合并语义。
- **`test_provider_calls_b5.py` 里的触发词是从 `app.providers.fake` 读出来的，
  不在测试里手抄。** 抄一遍的话，改了那边这里就变成「一个凑巧不在词表里的
  普通提示词」，于是整个文件会从「验失败路径」悄悄变成「验成功路径」而全绿。
  同一个理由，`test_moderation_b5.py` 的 `_SENTINEL` 也从词表里读。
- **对账用例断言的是「比基线增加」，不是绝对条数。** 注册赠送已经写了一条
  `grant` 流水，那是基准不是噪音 —— 写死绝对条数的话，这条用例会被注册流程的
  一个无关改动弄红。

B6 定的几件事（改之前先读）：

- **`public_url` 是永久地址，预签名被明确排除。** 看着「预签名更安全」，
  但契约里 `public_url` 是**永久**的：预签名的表现是「昨天生成的作品今天全裂了」，
  而且**只在时间过去之后**才出错 —— 本地怎么测都是好的。代价是桶要公共读
  或挂 CDN（§9.1 的第一种）。判据写成了「**同一个 key 调两次要一模一样**」，
  卡在预签名的定义性特征（带时间）上。完整理由见 HANDOFF §3.14。
- **`_create_assets_for` 走 Storage 实例的 `url_for`，不是模块级的
  `public_url_for`。** 后者写死 `/media/`，在 `STORAGE=oss` 下会拼出本地路径
  形状的地址 —— 而生成、扣费、落库全部正常，只有用户点开作品时 404。
  这是 B6 顺手修掉的一个真缺陷。
- **`req_key` 编在 `provider_task_id` 里跟着任务落库**，不是记在 provider 实例
  的字典里。后者是「任务状态放在进程内存里」的一种形式：重启即丢，
  而丢了的表现是所有在途任务的查询都用错 `req_key` → 判死 → 退款，
  日志里一切正常。见 HANDOFF §3.15。
- **搬运的 IO 挪到事务外，但只挪了 worker 那一条路。** 同步路径的 IO
  **仍在事务里**，这是故意的：`test_transfer_b4.py` 那条「被拒的提交一整笔都
  不留痕」靠的正是回滚。一刀切会把它变成 200 + 一条永远 `submitted` 的任务
  （`TEST_MODE=1` 下不起 worker，而跨仓门禁正是这个配置）。
  ⚠️ 守卫的判据是「**搬运进行中，库里认得见 `running`**」，**不是**「另一个连接
  写得进」—— 后者两种写法都是绿的（实测过）。别把那三条用例改写成后者。
- **`perform_transfer` 的签名里连 `Session` 都没有**，有一条 `inspect.signature`
  守卫钉着。不是洁癖：只要它能拿到会话，「在事务里做 IO」就会在某次重构里
  悄悄长回来。
- **计费算式只能在 `providers/pricing.py` 里有一份。** 两个 provider 各写一遍的
  后果不是「算式错了」，而是**分岔之后两边测试都还是绿的**。有一条 `ast` 守卫
  数 `JimengProvider` 那两个方法体里的语句数（必须只剩一句 `return`）。
- **`app/providers/jimeng.py` 与 `jimeng_sign.py` 的每一个猜测都写在文件头。**
  签名规范、请求 JSON 的字段名、`req_key`、模型 id、产物字段名 —— 五件里
  没有一件是从真实网关验证过的。`httpx.MockTransport` 只能证明**我们自己自洽**。
  别把那些「未经验证」的注释删掉，它们是这个文件最重要的部分。
- **`S3Storage` 的实现是真的，验证是隔的**：`tests/test_storage_b6.py` 拦的是
  `before-send.s3.*`，所以 boto3 的序列化、SigV4 签名、寻址风格全是真的，
  只有「发出去」那一步被截下来。**真桶接不接受这个桶名/区域/权限，没验过。**

B7 定的几件事（改之前先读）：

- **`test_acceptance_b7.py` 里的库读数走的是「新开一个 engine」。**
  在同一条会话里读回来的行，**无论如何都在内存里**，所以那种绿证明不了
  「任务状态不在进程内存中」。跨连接读是让这条铁律**在 pytest 里可被证伪**的
  唯一办法 —— 别为了「少写几行」把它改回 `db.get(Task, id)`。
- **冻结那条流水的 `balance_after` 是 `46`，不是 `14`。** §7.2 里 `freeze`
  只抬 `frozen`、`balance` 只在结算时动。写成 `14` 看着更「整齐」，
  但那是另一套记账模型，会和前端的 `available = balance − frozen` 对不上。
  用例里另有一条 `balance_after - frozen_after == 14` 把真实可用的 14 钉住。
- **剧本里 `polls_before_done = 1` 是刻意的。** 它保证有一次「问了、还没好」
  的查询真的发生过 —— 那一次也必须进 `provider_calls`（对账表要记的是
  **调用了**，不是**成功了**）。
- **这个文件只加测试，`app/` 一行没改。** 所以它的 339 条里没有任何一条
  是在验新功能；它验的是**既有功能合起来还成立**。真进程那一半
  （手工跑、含重启后仍能取回标识）见 HANDOFF 的 `### B7` 一节。

## 起步

```bash
# 1. 建虚拟环境（Python 3.12）
python -m venv .venv

# 2. 装依赖
.venv/Scripts/python.exe -m pip install -r requirements.txt        # 生产
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt    # 开发（含 pytest）

# 3. 配密钥。JWT_SECRET 没有默认值，不配就起不来 —— 这是故意的。
cp .env.example .env
.venv/Scripts/python.exe -c "from app.config import generate_dev_secret as g; print(g())"
# 把输出填进 .env 的 JWT_SECRET=（至少 32 字符）

# 4. 起服务
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

起来之后：

| 地址 | 是什么 |
|---|---|
| `http://127.0.0.1:8000/health` | 健康检查。**先看它的 `provider` 与 `video_provider`** —— 那两路可以是两家（`PROVIDER` / `VIDEO_PROVIDER`），只看一个会漏掉一半 |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/openapi.json` | OpenAPI schema |

---

## 门禁

两样都要绿，缺一不可。

```bash
# 依赖闸门：证明每个依赖不只是「装上了」，而是「真的能用」
.venv/Scripts/python.exe scripts/check_deps.py

# 测试
.venv/Scripts/python.exe -m pytest
```

`check_deps.py` 不是 `pip install` 的替代品，两者测的是不同的东西：
`pip install` 成功只说明包被解压到了磁盘上，**不说明** C 扩展能加载、
版本之间能协作、关键路径能跑通。前端的教训（《工程文档.md》§4.4：
pub.dev 不通必须在 C0 发现，不能等写到一半）在后端同样成立 ——
B5 写到一半才发现密码哈希方案装不上，要换的是方案，不是包。

所以闸门里每一项都**做一次真动作**，其中有**四条是反证**（缺了必须启动失败）：
`JWT_SECRET`、配了 `jimeng` 却没有 AK/SK、配了 `jimeng` 却没有 `req_key`、
选了 `STORAGE=oss` 却没有桶名/密钥。一个永远返回配置对象的 `Settings`
会让这四条防线静默失效。

（`req_key` 那一条的判据 B7.x 起是**按路**的：图片那一路用即梦就要
`JIMENG_REQ_KEY_IMAGE`、视频那一路用即梦就要 `JIMENG_REQ_KEY_VIDEO`。
所以 `PROVIDER=jimeng` + `VIDEO_PROVIDER=minimax` 这个组合只需要前者 ——
要求它填一个视频那一路根本用不上的键，只会让正确的配置起不来。）

⚠️ **项数是会长的**（B0 时 15 项，B6 起 **18**），所以「15/15 全过」这句话
在文档里的任何残留都只说明它写在 B6 之前。判据永远以**当场那次运行**的输出为准。

---

## 目录

```
app/
  main.py        入口。建 app、挂中间件、/health、按配置起 worker 线程。
  worker.py      B3：后台轮询循环（§8.3 的六条职责逐条落位）。
                 ⚠️ 它在 app/ 根下，不在 services/ —— 它是**进程入口**那一类
                 （和 main.py 同级），不是业务规则。
  logging_setup.py  让 aivideo.* 的日志在真进程里打得出来（见文件头）。
  config.py      全部配置（环境变量）。密钥只从这里读，且没有默认值。
  database.py    引擎与会话。SQLite 的 pragma 集中在 _configure_sqlite。
  models.py      B1 起：7 张表
  schemas.py     响应形状 —— 所有契约断言的依据
  enums.py       8 个任务状态的**唯一定义处**
  errors.py      AppError + 异常处理器（错误体顶层 {code,message} 在这里成形）
  security.py    bcrypt 与 JWT
  deps.py        鉴权依赖（get_db / get_current_user）
  routers/       13 条业务端点，按资源分文件（本层很薄，校验都在 services）
  services/      credits（记账）· generation（提交与状态机）· assets
                 · queue（B3：出队/位次/退避）· moderation（B5）
                 · marking（B5：隐式标识的内容与策略）
                 · provider_audit（B5：provider_calls 的冲刷与脱敏）
                 · storage（B4：Storage Protocol + LocalStorage；B6：S3Storage）
                 · transcode（B4：Pillow 探针 / ffprobe / ffmpeg 抽帧）
                   ⚠️ **Pillow 与 ffmpeg 只在这一个文件里被调用**
                 · transfer（B4：取件 + 魔数校验 + 转存流水线）
  providers/     base（Protocol）+ fake（永久测试夹具，不是脚手架）
                 + pricing（B6：冻结/结算算式**唯一的一份**）
                 + jimeng（B6）+ jimeng_sign（B6，已过真网关）
                 + minimax（B7.x：图生视频那一路，**未过真网关**）
                   【为什么 `build_provider` 要收 kind】因为图片与视频
                   可以是**两家**（`PROVIDER` / `VIDEO_PROVIDER`）。
                   这是本仓库唯一一处偏离「切真 provider 时调用方一行
                   不改」的地方，理由写在 providers/__init__.py 的
                   文件头 —— 关键在 `poll()` 拿不到 kind。
alembic/         迁移
scripts/         check_deps.py（依赖闸门）
                 check_storage.py（B7 后补：真桶冒烟 —— 写/读回/匿名下载/删。
                                   不花钱、不碰用户数据。**它是唯一能验
                                   「桶认不认」的东西**，本地替身永远绿。
                                   ⚠️ 它走的是 `curl`，**看不见 CORS** ——
                                   桶上那条规则掉了它照样全绿，见
                                   HANDOFF §2.6 第四件事 ③）
                 create_invite.py（B5：种邀请码 —— 非 TEST_MODE 的库上，
                                  这是**唯一**能造出用户的入口）
tests/           conftest.py 是夹具的地基，先读它
                 test_acceptance_b7.py（B7：§15.1 那条剧本的自动化版本。
                   别的文件验「某一个部件对不对」，它验「合起来还成立」）
```

⚠️ **这一段曾经是个谎，值得留着。** 早先的版本在 `scripts/` 那张表里列了
`grant_credits.py` 和 `create_invite.py` —— 它们**从来没有被写出来过**，
是计划阶段留在文档里的（`grant_credits` 只是 `tests/_helpers.py` 里的一个
测试辅助函数，不是给运维用的脚本）。代价很具体：在一个**不是** `TEST_MODE`
的库上，没有任何官方入口去种邀请码，于是新库上**注册不了任何用户**，
而 B3 的手工验收是靠一次性内联脚本直接插 `invite_codes` 一行绕过去的。

**B5 补上了 `create_invite.py`**；**发积分仍然没有脚本** —— 今天只有
`/__test/grant`，而它只在 `TEST_MODE` 下挂着（见 HANDOFF §6.2）。
写下来的教训是：文档里的目录树**要按「实际存在」写，不按「计划里有」写**，
否则下一个人会照着一个不存在的入口排一小时的错。

---

## 几条会咬人的约定

**响应体没有信封。** 体就是对象本身（`{"id":1,...}`），不是
`{"code":0,"data":{...}}`。错误时顶层放 `code` 和 `message`。
前端 `DioApiClient._decode` 建立在这条上，加任何统一包装的中间件都会
一次性打断所有接口。

**所有 ID 必须序列化成 JSON 整数。** 前端四个模型的 `fromJson` 都走
`requireInt()`，字符串会抛。所以主键一律 `INTEGER PRIMARY KEY`，不用 UUID。

**`available` 和 `provider_url` 永远不出现在响应里。** 前者由前端现算
（`balance − frozen`），后者是即梦的临时地址（**只活 1 小时**，不是资产真相）。
两条都有前端守卫测试盯着。

**未结算时 `settled_amount` 是 JSON `null`，不是 `0`。**
`queue_position` 只在 `status == "queued"` 时有值，其余为 `null`。

**`.ini` / `.cfg` 文件里不许出现非 ASCII 字符。** 它们是被 configparser
按**系统区域编码**读的，而中文 Windows 上是 GBK —— 一句中文注释就会让
工具在读配置阶段抛 `UnicodeDecodeError`，报错位置和病因完全无关。
中文说明写进 `.py` 文件（Python 源码按 UTF-8 读）。

**`/__test/*` 受 `TEST_MODE` 硬门禁。** 关着的时候这些路径**在路由表里
根本不存在**，不是「存在但返回 403」—— 差别在于前者要打开必须动那行
`if`，改动意图一眼可见。它们能凭空造积分、能删库。

---

## 铁律（来自项目级约束，不是本仓库的偏好）

- **AK/SK 只从环境变量读**，绝不写进 `.py`、绝不进 git。开发与生产用
  **不同**的密钥。提交前过一眼 `git diff --cached`。
- **AI 生成内容必须有「AI 生成」标识。** 前端负责可见角标，后端负责
  **隐式标识**（把生成信息写进文件元数据）—— 这是《人工智能生成合成内容
  标识办法》规定的法律义务，不是可选项。
- **v1 没有充值、支付、购买。** 不建任何相关接口。
- **任务状态不放在进程内存里。** 全部落库，否则重启就丢。
- 当前批次与进度看 `flutter_application_1/HANDOFF.md`。

---

## 字节去哪儿了（B4 起）

```
provider 造的产物      .provider_spool/     ← fake 也真的造；**只有这里能被读**
        │ 转存（transfer.py，魔数校验 + 限额）
        ▼
我们自己的存储          media/              ← STORAGE=local；StaticFiles 挂在 /media
        │
        ▼
响应的 public_url      /media/<storage_key>
```

两个目录都在 `.gitignore` 里，因为里面是**内容寻址的缓存和测试产物**。

**B6 起，第三条腿也是同一个形状**（`STORAGE=oss` 时）：

```
我们自己的存储          LocalStorage → media/            （本地静态挂载）
        │              S3Storage    → {S3_PUBLIC_BASE_URL}/{key}   （桶或 CDN）
        ▼
响应的 public_url      两者的**形状不同**，所以拼地址**必须走 store.url_for()**，
                       不许在任何地方自己拼 "/media/"。见上面 B6 那一段。
```

**一句话判据**：任何一次动了「字节链路」的改动，都要能通过这条：

```bash
# 起服务、生成一次，然后 —— 字节数不是 0、磁盘上看得见文件
curl -s "<assets[0].public_url>" | wc -c
ls media/
```

⚠️ 两条**只能靠真跑进程**才发现的事（pytest 里是绿的）：

- `public_url` 的主机来自 `PUBLIC_BASE_URL`，用别的端口起服务时它仍然
  写着默认的 `:8000` —— App 拿到会指向它自己。
- `/media` 的响应带 `X-Content-Type-Options: nosniff`（一个只对 `/media`
  生效的薄中间件）。**放的是用户上传的字节**，不关掉嗅探就是一次
  存储型 XSS。

---

## ffmpeg（**已解决**）

2026-10-13 起 B0 的依赖闸门**全绿**。`Gyan.FFmpeg 9.0.2 full_build` 装在

```
C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Packages\
  Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin
```

这个 `bin` 在**用户** PATH 里，`check_deps.py` 的 ffmpeg 项转 `[ok]`。
它用于「从视频抽封面帧」（§4.1 / §16），B4 抽帧直接可用；
**B5 起还多了一个身份**：隐式标识里的视频那一支（`-c copy` 重写 MP4 元数据）
也靠它，而且 ffmpeg 不在时**视频任务会失败**（合规优先，见 `services/transfer.py`）。

⚠️ 两处残留，将来排查时别被它们带跑：

- 那个路径**带版本号**（`ffmpeg-9.0.2-full_build`）。`winget upgrade`
  之后目录会换名，PATH 里这条就失效了 —— 症状又是 `FileNotFoundError`。
- 用户 PATH 里这一条**重复了两遍**（winget 写的 + 手工加的），无害，
  但 `where ffmpeg` 会打印两行，不是异常。

**这一段曾经是红的，而且当时的诊断是错的** —— 有人（本文件的历史版本）
断言过「两份注册表里都没有它，所以重开终端也不管用」，而那是一个
坏命令读出来的假结论：Git Bash 会把 `reg query ... /v Path` 里的 `/v`
当路径改写，命令其实**报错退出**了，却被 `2>/dev/null || echo "(没有)"`
翻译成了「查无此项」。完整经过与正确写法见 `HANDOFF.md` §6.1。

之所以把这条留在这里而不是删掉，是因为「跳过一项检查然后说全过」和
真全过看起来是一样的 —— 而反过来，「命令失败了」和「查无此项」
看起来也是一样的。
