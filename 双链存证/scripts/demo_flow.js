// 在一条**已经在跑**的本地链上，把「充值 → 授权 → 冻结 → 结算 / 退款」全流程演一遍，
// 让你在终端里看到每一步交易和余额变化（不需要钱包）。
//
// 用法：
//   终端 A: npx ganache --chain.chainId 1337 --wallet.deterministic
//   终端 B: node scripts/deploy.js          # 记下输出的 VideoCredit 地址
//           node scripts/demo_flow.js 0x<VideoCredit 地址>
//
// 它用的是 ganache 默认解锁的前两个账户：accounts[0] = 平台，accounts[1] = 用户。
const path = require("path");
const { ethers } = require("ethers");

const artifact = require(path.join(__dirname, "..", "artifacts", "VideoCredit.json"));
const id = (s) => ethers.id(s);

function fmt(x) {
  return x.toString();
}

async function main() {
  const tokenAddr = process.argv[2];
  if (!tokenAddr) {
    console.log("用法：node scripts/demo_flow.js <VideoCredit 地址>");
    process.exit(1);
  }
  const provider = new ethers.JsonRpcProvider(process.env.RPC_URL || "http://127.0.0.1:8545");
  const accounts = await provider.listAccounts();
  const platform = await provider.getSigner(0);
  const alice = await provider.getSigner(1);
  const platformAddr = await platform.getAddress();
  const aliceAddr = await alice.getAddress();

  const token = new ethers.Contract(tokenAddr, artifact.abi, platform);
  console.log(`平台 ${platformAddr}\n用户 ${aliceAddr}\n代币 ${tokenAddr}\n`);

  const step = async (label, fn) => {
    const tx = await fn();
    const rc = await tx.wait();
    console.log(`✓ ${label}  tx=${tx.hash.slice(0, 12)}…  gas=${rc.gasUsed}`);
  };

  console.log("① 平台给用户充 100 VCR（用户余额应变成 100）");
  await step("mint", () => token.mint(aliceAddr, 100n));

  console.log("\n② 用户授权平台 10 VCR（会打印一笔 approve 交易）");
  const aliceToken = token.connect(alice);
  await step("approve", () => aliceToken.approve(platformAddr, 10n));

  console.log("\n③ 平台冻结 10 VCR —— 币转到合约托管，用户余额 90、合约余额 10");
  const vid1 = id("video-demo-001");
  await step("reserve", () => token.reserve(aliceAddr, 10n, vid1));
  console.log(`   用户余额 ${fmt(await token.balanceOf(aliceAddr))}，合约托管 ${fmt(await token.balanceOf(tokenAddr))}`);

  console.log("\n④ 视频交付成功 → 结算，托管额销毁，totalSupply 从 100 变 90");
  await step("settle", () => token.settle(vid1));
  console.log(`   totalSupply ${fmt(await token.totalSupply())}，合约余额 ${fmt(await token.balanceOf(tokenAddr))}`);

  console.log("\n⑤ 假设第二次生成失败 → 冻结后原路退款，余额回到 90");
  const vid2 = id("video-demo-002");
  await step("approve", () => aliceToken.approve(platformAddr, 20n));
  await step("reserve", () => token.reserve(aliceAddr, 20n, vid2));
  console.log(`   冻结后用户余额 ${fmt(await token.balanceOf(aliceAddr))}`);
  await step("refund", () => token.refund(vid2));
  console.log(`   退款后用户余额 ${fmt(await token.balanceOf(aliceAddr))}`);

  console.log("\n演示结束。终端里能看到上面每一笔交易 hash 与 gas，余额与 totalSupply 对得上。");
}

main().catch((e) => {
  console.error("失败：", e.shortMessage || e.message || e);
  process.exit(1);
});
