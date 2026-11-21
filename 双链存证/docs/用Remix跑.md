# 用在线 Remix 跑（**不需要 MetaMask**，也不需要 Truffle）

> 结论：**完全可以。** Remix 自带一条**浏览器内虚拟链（Remix VM）**，编译、部署、调用、看余额、看事件全在网页里完成，不需要装钱包、不需要连节点。
> 用不了 MetaMask 不影响任何关键结论：MetaMask 只是「钱包 + 签名弹窗 + 代币展示」的 UI，**不是链，也不是编译器**。
>
> 两条路线可以同时用：
> - **路线 A（零安装，交互演示）**：Remix + Remix VM → 截图进报告；
> - **路线 B（可重复证据）**：本仓库 `npm test` / `npm run test:evidence` / Ganache + 脚本 → 输出进报告。
>
> 本仓库已备好可直接粘进 Remix 的单文件源码（OpenZeppelin 依赖已内联，Remix 不需要联网拉包）：
> - [`remix/VideoCredit.flat.sol`](../remix/VideoCredit.flat.sol) —— 代币 + 托管/结算/退款
> - [`remix/VideoEvidence.flat.sol`](../remix/VideoEvidence.flat.sol) —— 单链存证
>
> 两个文件由 `node scripts/flatten.js` 生成，已用 solc-js 验证「拍平后编译出的字节码与 `artifacts/` 一致」。

---

## 0. 先把几个东西分清（很多人在这里绕晕）

| 东西 | 是什么 | 你需要吗 |
| --- | --- | --- |
| **Remix IDE** | 浏览器里的合约开发环境（编辑 + 编译 + 部署 + 调用函数） | ✅ 需要（这就是你用的） |
| **Remix VM** | Remix 内置的**虚拟链**，跑在浏览器里，自带 15 个各 100 ETH 的测试账户 | ✅ 需要（替代钱包 + 本地区块链的演示作用） |
| **Ganache** | 本地独立的以太坊链（`127.0.0.1:8545`），本仓库脚本连它 | 可选（想跑脚本证据时装） |
| **MetaMask** | 浏览器钱包：保管私钥、弹窗签名、显示代币 | ❌ 不需要（这就是你省掉的） |
| **Truffle** | 合约工程框架（migration + 测试） | ❌ 不需要 |

**关键点**：Remix VM 里所有账户都归 Remix 管，所以**调用时不需要任何人签名、不会弹窗**——你在 Remix 的 `ACCOUNT` 下拉里选哪个账户，就等于「以谁的身份调用」。这正好可以模拟「平台账户」和「用户账户」。

---

## 1. 路线 A：Remix VM 全流程（约 20 分钟）

### 1.1 打开并粘代码

1. 浏览器打开 <https://remix.ethereum.org>（需要能访问外网；打不开见 §5 的替代方案）。
2. 左侧 **File Explorer** → 新建文件 `VideoCredit.flat.sol`。
3. 用记事本/VSCode 打开 `G:\AIVideo\双链存证\remix\VideoCredit.flat.sol`，**全选复制**，粘进 Remix。

### 1.2 编译设置（两个地方别选错）

点左侧 **Solidity Compiler**（编译器图标）：

| 设置 | 选什么 | 为什么 |
| --- | --- | --- |
| **COMPILER** | `0.8.24` ~ `0.8.30` 之间任意一个 | 合约用了 OpenZeppelin 5.x，需要 ≥0.8.24 |
| **EVM VERSION** | `shanghai` | 和本仓库 `artifacts/`、Ganache 保持同一目标；选更新版本一般也能跑，但报告里要写一致 |
| **Auto compile** | 勾上 | 省手点 |
| Advanced → optimizer | 勾选，runs = `200` | 和本地编译一致，便于复现 |

点 **Compile**，看到绿色对勾即成功。出现 `Warning: This declaration shadows a builtin symbol` 可以忽略（参数名叫 `sha256` 的风格警告）。

### 1.3 选环境 + 部署

点左侧 **Deploy & Run Transactions**（以太坊图标）：

1. **ENVIRONMENT** 选 **`Remix VM (Shanghai)`**（或列表里更新的 Remix VM，如 Cancun/Prague；它们都能执行 shanghai 编译的字节码）。
2. 这时 **ACCOUNT** 下拉会自动出现一批账户（Account #0 ~ #14），每个 100 ETH。**记住：Account #0 = 平台，Account #1 = 用户。**
3. **CONTRACT** 选 `VideoCredit`，构造函数参数 `transferable_` 填 `false`。
4. 点 **Deploy**。没有弹窗，直接成功；`Deployed Contracts` 出现新合约，底部终端打印交易记录。
5. 展开 `Deployed Contracts` 下的 `VideoCredit`，就能看到所有函数（橙色=写，蓝色=读）。

> 刷新页面后 Remix VM 的状态会重置（合约实例和余额都没了），演示时别刷新；要重复演示就重新 Deploy。

### 1.4 按顺序点一遍（逐步操作，照抄即可）

#### 第 0 小步：先准备 3 个值

| 值 | 从哪来 | 长什么样 |
| --- | --- | --- |
| **平台地址** | `ACCOUNT` 下拉选 `Account #0`，复制它的地址 | `0x5B38…`（Remix VM 默认值，以你页面为准） |
| **用户地址** | `ACCOUNT` 下拉选 `Account #1`，复制地址（复制完切回 #0） | `0xAb84…` |
| **videoIdHash** | 下面的脚本输出第三行 | `0x` + 64 位十六进制 |

```powershell
cd G:\AIVideo\双链存证
node scripts/hash_inputs.js reserve video-demo-001 10 0x<把用户地址粘这里>
0xAb8483F64d9C6d1EcF9b849Ae677dD3315835cb2
cd G:\AIVideo\双链存证
node scripts/hash_inputs.js reserve video-demo-002 20 0xAb8483F64d9C6d1EcF9b849Ae677dD3315835cb2
```

脚本只做算术（keccak + 格式化），不联网、不连链。输出三行，**只需要第三行 `videoIdHash`**。

0x5be6b4770265b59bab0bde0451a3e4a9a91b41e34435d91b25c4104715b1d676

#### 第 1 小步：认一下界面（30 秒，别点错地方）

- `Deployed Contracts` → 展开 `VideoCredit`，就是函数面板；
- **橙色按钮 = 写操作**（要执行一笔交易，会改变链上状态）；
- **蓝色按钮 = 只读操作**（点一下立即返回，不产生交易）；
- 蓝色函数的结果显示在**函数名下方**，形如 `0: uint256: 100`；
- 橙色函数的执行结果显示在**页面底部终端**（多一条交易，点开能看 `gasUsed`、事件日志）；
- 最顶上的 **ACCOUNT 下拉决定「现在是谁在调用」** —— 每次点橙色函数前先确认它选对了。

#### 第 2 小步：逐下点击（一共 7 下）

> 口诀：**先看 ACCOUNT，再填参数，最后点按钮。**

| # | ACCOUNT 选谁 | 点哪个函数 | 每个输入框填什么 | 点完你应该看到 |
| --- | --- | --- | --- | --- |
| ① | `Account #0`（平台） | `mint` | `to` = **用户地址**；`amount` = `100` | 无返回值；接着点蓝色 `balanceOf(用户地址)` → `100` |
| ② | **切成 `Account #1`（用户）** | `approve` | `spender` = **平台地址**；`amount` = `10` | 接着点 `allowance(用户地址, 平台地址)` → `10` |
| ③ | **切回 `Account #0`** | `reserve` | `user` = 用户地址；`amount` = `10`；`videoIdHash` = 脚本那行 | 用户余额 90、合约余额 10；`escrowOf(videoIdHash)` → `user`/`amount=10`/`createdAt`/`closed=false` |
| ④ | 不用切换 | 蓝色查询（不消耗 gas） | `balanceOf(用户地址)`、`balanceOf(合约地址)`、`totalSupply()` | 依次是 `90`、`10`、`100` |
| ⑤ | `Account #0` | `settle` | `videoIdHash` = 同一个 | 合约余额 0、`totalSupply()` = `90`、`escrowOf(...).closed` = `true` |
| ⑥ | 切 `#1` → 切 `#0` | `approve` → `reserve` → `refund` | `approve(spender=平台, 20)`；`reserve(user=用户, 20, **换一个新的 videoIdHash**)`；`refund(那个新 hash)` | 余额 `90 → 70 → 90`，合约余额 `20 → 0` |
| ⑦ | 不切换 | `totalSupply()` | — | 仍是 `90`（退款只是把托管额退回，不增发） |

**③ 和 ⑥ 里 `videoIdHash` 怎么来**：③ 用 `node scripts/hash_inputs.js reserve video-demo-001 10 <用户地址>`；⑥ 换个字符串重跑，例如 `reserve video-demo-002 20 <用户地址>`，拿新的 hash。**同一个 videoIdHash 不能用两次**（合约会 revert：`VideoIdAlreadyUsed`）。

**为什么 ③ 要填 `user`**：钱是从 `user` 这个地址扣的，`msg.sender` 是平台（#0）。两者不同：`msg.sender` 决定「谁有权限」，`user` 决定「扣谁的钱」——这正是托管式设计跟「平台直接烧」的区别。

#### 第 3 小步：顺手记 gas（报告第七章用）

每笔橙色交易在底部终端点开都能看到 `gasUsed`。本机实测值供你对照：

| 操作 | gasUsed |
| --- | --- |
| `mint` | 70,985 |
| `approve` | 46,336 |
| `reserve` | 124,360 |
| `settle` | 41,494 |
| `refund` | 41,638 |
| `recordEvidence`（带 CID） | 209,322 |

#### 第 4 小步：点错了会看到什么（对照排查）

| 终端报错 | 意思 | 怎么改 |
| --- | --- | --- |
| `AccessControlUnauthorizedAccount` | 用非平台账户调了 `mint`/`reserve`/`settle` | 切回 `Account #0` |
| `ERC20InsufficientAllowance` | 用户没 approve，或这次 approve 的额度已用完 | 切 `#1` 重新 `approve` |
| `ERC20InsufficientBalance` | 用户余额不够（`mint` 没做 / `to` 填错地址） | 检查 ① 的 `to` 是否用户地址 |
| `VideoIdAlreadyUsed` | 同一个 `videoIdHash` 又 reserve 了一次 | 换 `video-demo-002` 重新生成 hash |
| `missing revert data` | Ganache/VM 没解出自定义错误名，看终端上下文 | 通常是上面某条的前置条件没满足 |

### 1.5 换存证合约（`VideoEvidence`）

1. 再建一个文件 `VideoEvidence.flat.sol`，粘贴 [`remix/VideoEvidence.flat.sol`](../remix/VideoEvidence.flat.sol)。
2. 编译设置同上（0.8.24+ / shanghai）。
3. Environment 保持 Remix VM；**CONTRACT 选 `VideoEvidence`**，无构造参数，Deploy。
4. `recordEvidence` 有 6 个参数，用脚本生成后照抄：

```powershell
node scripts/hash_inputs.js evidence vid_demo_001 <sha256> <16位感知哈希> 0x<Account #0 地址> '{"model":"demo","seed":42}'
```

输出会逐行告诉你每个框填什么（`videoIdHash`、`sha256`、`perceptualHash` **十进制**、`ipfsCid`、`creator`、`paramsHash`）。没做 IPFS 时 `ipfsCid` 填 `""` 即可。

5. 验证：
   - `verifyExact(videoIdHash, sha256)` → `matched: true`；
   - 把 `sha256` 改一个字符再调 → `matched: false`（篡改检测）；
   - `verifyPerceptual(videoIdHash, 转码副本的十进制感知哈希, 10)` → 返回 `matched` 与 `distance`（本机实测转码副本距离 11：阈值 10 判 false，改成 12 判 true）。

### 1.6 截图清单（报告「实验与结果」用这 6 张）

1. Compiler 面板：版本 + `EVM VERSION = shanghai` + 绿色编译成功；
2. Deploy 面板：Environment = Remix VM、合约地址、部署交易；
3. `mint` + `balanceOf` 的返回值（用户 100）；
4. `reserve` 后的 `escrowOf`（user/amount/createdAt/closed）与两个 `balanceOf`（90 / 10）；
5. `settle` 后 `totalSupply = 90`、合约余额 0；
6. `verifyExact` 篡改前后两次返回值（true / false）。

加上本地 `npm test` / `npm run test:evidence` 的输出截图，就同时有「交互可行」和「结果可重复」两类证据。

---

## 2. 路线 B：本地脚本证据（不需要 MetaMask，但需要一条链）

**注意**：Ganache 不是 MetaMask。Ganache 是一条链，脚本直接用它的测试账户签名，所以**全程没有钱包、没有弹窗**。

```powershell
# 终端 A：起链
cd G:\AIVideo\双链存证
npx ganache --chain.chainId 1337 --wallet.deterministic --server.port 8545

# 终端 B：跑证据
cd G:\AIVideo\双链存证
npm test                      # VideoCredit 五组用例
npm run test:evidence         # VideoEvidence 六组用例
node scripts/deploy.js        # 部署并打印地址
node scripts/demo_flow.js 0x<VideoCredit 地址>   # 一条命令跑完 mint→approve→reserve→settle/refund
node scripts/eth_evidence.js record evidence_receipt.json
```

这些命令都不需要 MetaMask、不需要浏览器，输出的交易 hash / gas / 余额变化可以直接进报告。

> 只想快速验证合约逻辑、连 Ganache 都不想开？`npm test` 和 `npm run test:evidence` 用的是**进程内 Ganache**，跑完即销毁，一条命令搞定。

---

## 3. 报告里怎么写（把 MetaMask 那句改掉）

原报告 2.2 末尾写「MetaMask 集成方式：将部署后的合约地址添加至 MetaMask 自定义代币列表」。如果你实际没做钱包集成，就不要写成已完成。可以改成：

> 合约开发使用 Remix IDE 完成编译与交互式验证，运行环境采用 Remix 内置虚拟机（Remix VM）与本地 Ganache 双环境；ERC-20 余额通过合约 `balanceOf` 查询验证。面向终端用户的钱包集成（MetaMask / WalletConnect）属于后续工作，本文未展开实测。

如果以后要补钱包集成，再写「通过 MetaMask 添加自定义网络（RPC + chainId）并导入代币地址即可展示余额」作为方案描述——但标注为「方案」而不是「已验证」。

---

## 4. 两种环境怎么选

| 场景 | 用哪个 |
| --- | --- |
| 答辩现场演示「点一下就扣费」 | Remix VM（零依赖、无弹窗、不怕断网后钱包连不上） |
| 想证明「结果可重复」 | 本地 `npm test` / `npm run test:evidence`（输出可贴进报告） |
| 想留一笔真实可查的链上记录 | Ganache + `deploy.js` / `eth_evidence.js`（脚本里能查交易 hash） |
| 以后做前端钱包集成 | 才需要 MetaMask/WalletConnect |

---

## 5. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| Remix 打不开 / 编译很慢 | 需要从 CDN 拉编译器，网络问题 | 换网络重试；或完全用本仓库本地编译（`npm run compile`），只把 Remix 当粘贴查看器 |
| `invalid opcode` | 编译目标 EVM 比运行环境新（选到 Cancun/Prague 却部署到老 Ganache） | Remix 里把 EVM VERSION 改 `shanghai`；或换更新的 Remix VM |
| 刷新后合约和余额都没了 | Remix VM 是内存链，刷新即重置 | 演示时别刷新；要重复就重新 Deploy |
| `Gas estimation failed` / revert | 参数错或前置条件没满足（没 approve 就 reserve、videoId 重复、账户选错） | 按 §1.4 顺序来；检查 ACCOUNT 是否是拥有 `SETTLER_ROLE` 的 #0 |
| `bytes32` 输入报 invalid | 填了不足 64 位的十六进制 | 用 `hash_inputs.js` 生成 `0x`+64 位 |
| `uint64` 报错 | 填了 `0x...` | uint64 只收十进制整数，脚本会直接给出十进制值 |
| `AccessControlUnauthorizedAccount` | 用错账户调用 `reserve`/`settle`/`recordEvidence` | 切回 Account #0（部署者，拥有角色） |
| 部署时提示账户余额不足 | Remix VM 重置过 / 账户没选 | 重新选 Environment，确认账户有 100 ETH |

---

## 6. 这个方案的边界（写进报告「局限」）

- **Remix VM 不是真链**：状态只在浏览器内存里，刷新即消失，不能当「链上持久化」的证据。持久化证据用 Ganache 脚本或测试网。
- **没有真实签名流程**：账户由 Remix 托管，所以演示不了「用户点钱包确认」这一交互；如果课程要求钱包交互，需要另找可用的钱包（如 WalletConnect 手机端），但**不影响合约功能本身**。
- **Remix 不能替代自动化测试**：截图无法进入 CI、没有断言。报告里「实验」最好以本地测试输出为主、Remix 截图作为交互验证补充。
