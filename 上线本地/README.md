# 上线本地（积分功能验收环境）

> 当前双链和独立演示数据库的启动步骤见 [本地双链启动](双链启动.md)。以下保留旧演示的验收记录。

> 📌 **换会话/换人接手先读**：[`..\交接文档-2026-11-10.md`](../交接文档-2026-11-10.md)（全局状态、恢复步骤、已知问题、下一步）
>
> 状态：**已在本机跑通**（2026-11-10）。后端用 **fake provider + local storage**，不花钱、不依赖外部服务。
> 积分链路验收脚本 `accept_credits.py`：**24 项全部通过（含链上对账）**。
>
> 目录：
> - 后端：`G:\AIVideo\backend`（FastAPI + SQLite，端口 8000）
> - 前端：`G:\AIVideo\flutter_application_1`（Flutter web，端口 8080）
> - 本目录：启动/停止脚本、验收脚本、本说明

---

## 1. 现在怎么用

| 地址 | 是什么 |
| --- | --- |
| <http://127.0.0.1:8080> | 前端页面（Flutter web） |
| <http://127.0.0.1:8000/health> | 后端健康检查（应显示 `provider: fake` / `storage: local`） |
| <http://127.0.0.1:8000/docs> | Swagger，可直接调所有接口 |
| <http://127.0.0.1:8545> | 本机 Ganache（影子链，chainId 1337） |
| `GET /credits/chain` | 链上凭证：钱包地址 / 合约地址 / 链上余额 / 最近上链交易 |

**邀请码**：`AIV-2026-01`（可用 20 次，永不过期；验收已用掉若干次）
**验收账号**：用演示邀请码注册，或使用验收脚本为本次运行创建的测试账号。

## 2. 启动 / 停止

```powershell
# 0) 先起本机链（新开一个终端窗口，保持不关）
cd G:\AIVideo\双链存证
npx ganache --chain.chainId 1337 --wallet.deterministic

# 启动后端（新开一个终端窗口，保持不关；脚本内已设置演示环境变量）
powershell -ExecutionPolicy Bypass -File "G:\AIVideo\上线本地\start-backend.ps1"

# 启动前端（再开一个终端窗口；会自动检查/构建 build\web）
powershell -ExecutionPolicy Bypass -File "G:\AIVideo\上线本地\start-web.ps1"

# 停止（按端口杀进程）
powershell -ExecutionPolicy Bypass -File "G:\AIVideo\上线本地\stop-all.ps1"
```

> 当前这两个进程是我在会话里以后台任务起的；**会话结束后会消失**。
> 要长期跑：用上面的脚本各开一个终端，或把 `start-backend.ps1` 配成开机任务。

## 3. 积分链路怎么验收（已跑过，可复跑）

```powershell
cd G:\AIVideo\backend
.venv\Scripts\python.exe ..\上线本地\accept_credits.py
```

它会自动：注册（+50）→ 查余额 → 文生图（冻结 4 / 结算 4，余额 46）→ 查流水（grant/freeze/settle）
→ 失败退款（`__FAIL__`，余额不变）→ 上传参考图 + 图生视频（冻结 32 / 结算 24，余额 22）→ 余额不足拦截。

**本次实测结果：24 项全部通过（其中 5 项是影子链对账）。** 关键数字：

| 阶段 | 余额 | 说明 |
| --- | --- | --- |
| 注册 | 50 | 邀请码 + 注册赠送 |
| 文生图成功 | 46 | 冻结 4 → 结算 4 |
| 失败退款（`__FAIL__`） | 46 | 全额退回，余额不变 |
| 图生视频成功 | 22 | 冻结 32、实际结算 24、退还 8 |
| 再次提交视频 | 400 `INSUFFICIENT_CREDITS` | 余额不足被拦 |

## 3.1 本次构建踩到的坑（记录一下，下次别再踩）

1. **`flutter build web` 一开始整片报错**（`Matrix4 isn't a type`、`WidgetRef isn't a type` 等，连 Flutter 框架源码都报）。
   根因不是代码：`.dart_tool\package_config.json` 是 10 月 12 日的旧文件，与当前 Flutter 3.47.5 不匹配。
   修复：`cd G:\AIVideo\flutter_application_1; flutter pub get` 后重新 `flutter build web`，一次通过。
2. `flutter pub get` 会提示「Building with plugins requires symlink support / 请开启开发者模式」——
   本次 **web 构建没有受影响**；以后要跑 Windows 桌面或某些插件时，才需要去「设置 → 隐私和安全性 → 开发者选项」打开开发者模式。

## 4. 本次做了什么（改动清单）

| 项 | 内容 |
| --- | --- |
| 备份 | `backend\backups\20261110-115038\`（`env.bak` + `aivideo.db.bak`，SQLite backup API 一致快照） |
| `.env` | 只改了 3 个键：`PROVIDER=fake`、`VIDEO_PROVIDER=fake`、`STORAGE=local`；其余密钥原样保留 |
| 数据库 | **保留现有数据**（8 用户 / 55 流水 / 21 任务），未清库 |
| 邀请码 | 新增 `AIV-2026-01`（20 次） |
| 服务 | 后端 8000、前端 8080（本次会话后台任务） |
| 验收 | 19/19 通过，新注册 4 个 `credits_*` 账号（邀请码已用 4/20） |
| 前端构建 | `flutter pub get` 修复了旧的 `.dart_tool` 后，`flutter build web` 通过（真后端模式，API 指向 127.0.0.1:8000） |

## 5. 想切回「真实生成」时

编辑 `G:\AIVideo\backend\.env`，改回这三行后重启后端：

```ini
PROVIDER=jimeng
VIDEO_PROVIDER=minimax
STORAGE=oss
```

或者直接还原备份：`copy backend\backups\20261110-115038\env.bak backend\.env`
（⚠️ 还原会覆盖当前 fake 配置；改完必须重启后端才生效。）

真实 provider 会**产生真实费用**，验收时建议只在确认积分链路 OK 后切。

## 6. 已知限制（如实记录）

1. **fake provider 出的是合成图片/视频**（用 Pillow/ffmpeg 造的），不是真 AI 产物——够验积分，不适合对外演示“AI 能力”。
2. 前端当前是 `flutter build web` 产物 + `python -m http.server`，只适合本机验收；对外要上 HTTPS（否则登录会卡在安全上下文）。
3. 后端是**单进程**（worker 是进程内线程），不要开多 worker。
4. 当前数据库仍是本地 SQLite；多用户并发压力大了再换 PostgreSQL。
5. 邀请码是**唯一注册入口**；用完了用 `backend\scripts\create_invite.py` 再种。

## 7. 下一步（可选）

- 换成真 provider 跑一轮真图/真视频，确认转存与 OSS CORS 没问题；
- 用 `backend\scripts\deploy-backend.sh` + `flutter_application_1\scripts\build-web.sh --mode real` 上云（宝塔 + HTTPS）；
- 把「创作信息上链」MVP 接进 `finish_transferred`（新表 + worker 相位，不动积分逻辑）。


---

## 8. 方案 B：影子链（积分 ↔ 链上 VCR 1:1 映射）—— 本次新增

> 目的：让用户能**自己到链上核对**「我扣掉的那 4 积分，确实对应一笔链上销毁」。
> 不改积分业务逻辑，只在旁边加一条**影子链**：账本仍是权威，链上留同额凭证。

### 8.1 做了什么

| 层 | 内容 |
| --- | --- |
| 合约 | `VideoCredit.consume(user, amount, videoIdHash)`：仅 `SETTLER_ROLE` 可调，但**强制 `_spendAllowance`**（平台最多花用户授权过的额度）；新增 `Consumed` 事件 |
| 数据表 | `chain_wallets`（每个用户一个影子钱包）、`chain_ops`（待上链的 mint/consume，`ref` 幂等）、`chain_state`（合约地址） |
| 服务 | `app/services/chain_credits.py`：部署合约、建钱包、一次性 `approve`、mint/consume、worker 重试、对账 |
| 钩子 | `credits.grant/adjust/settle_and_refund/charge_frozen` 只**登记**上链意图（写 `chain_ops`），不发交易 |
| worker | 新增相位：把 pending 的 `chain_ops` 逐条上链，失败重试 5 次 |
| API | `GET /credits/chain`：钱包、合约、链上余额、平台余额、最近上链记录（含 tx hash） |
| 前端 | 积分页新增「链上凭证（影子链）」卡片：链上余额 vs 平台余额对账标记、钱包/合约地址、最近 3 笔交易 |

### 8.2 用户怎么「自己验证」

1. 打开积分页，抄下卡片里的**钱包地址**和**合约地址**；
2. 到任意以太坊工具（Remix、MetaMask「导入代币」、区块浏览器）用钱包地址查 **VCR 余额**；
3. 点开最近一笔消耗的 **tx hash**，能看到 `Consumed(user, amount, videoIdHash)` 事件；
4. 页面上「链上余额 = 平台余额」的标记，就是平台不敢单方面改账的证明。

> 本地演示没有区块浏览器，但可以用 Remix → 粘 `remix/VideoCredit.flat.sol` → 在 `At Address` 填合约地址 → 调 `balanceOf(钱包)`，看到的就是链上真实余额。

### 8.3 实测数据（2026-11-10）

```
注册            赠 50     链上 mint 50   tx=0x5f2b38c7…
文生图成功      扣 4      链上 consume 4   tx=0xd5b1ebe7…
失败退款        不变      无链上操作
图生视频成功    扣 24     链上 consume 24  tx=0xcc7991ff…
链上余额 22 = 平台余额 22 = totalSupply 增量对得上
```

验收脚本输出：**24 项通过 / 0 失败**。

### 8.4 怎么切回「真实 provider」

演示用的 fake/local/链开关**不在** `backend\.env` 里，而在 `start-backend.ps1` 的环境变量里。
要跑真生成：把脚本里那几行去掉，让 `.env`（jimeng + minimax + oss）生效即可；
**链开关 `CHAIN_ENABLED`** 相应改成 0/1。

### 8.5 已知限制（演示版，别当真上线）

1. **影子钱包私钥明文存在数据库**（`chain_wallets.private_key`）——生产必须用户自持或 KMS 托管；
2. **链是影子**：余额以链下账本为准，链上暂不可用时用户照常下单，worker 事后补链；
3. **Ganache 重启会清空链**：数据库里记的合约地址失效，下次访问会自动重新部署 + 把差额补 mint；
4. **单进程**：worker 与 web 同进程，不能开多 worker；
5. 真做到「余额以链为准」是方案 C（充值 mint、消耗 burn、退款 refund 全链上），需要支付通道与合规评估，不在本次范围。

### 8.6 测试状态

| 套件 | 结果 |
| --- | --- |
| 前端 `flutter test` | ✅ 141 通过（新增链上凭证卡片后重跑） |
| 后端 `pytest` | ✅ 退出码 0（`chain_enabled=0`，并把本机 `.env` 临时移开——见下） |
| 积分验收 `accept_credits.py` | ✅ 24/24（含链上余额对账与 tx hash） |

> 为什么后端测试要把 `.env` 移开：本机 `.env` 里有 `VIDEO_PROVIDER=minimax`，而测试套件假设该项**未设置**（2 条 TestFollowProvider 用例会因此变红）。这是 `.env` 与测试假设的既有冲突，不是本次改动引入的；CI/干净环境没有 `.env`，测试全绿。
