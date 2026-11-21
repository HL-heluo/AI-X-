// 在进程内起一条 Ganache 链，把合约的 5 组关键路径全部跑一遍。
//
//   npm run test
//
// 不需要单独开 ganache-cli，也不需要写 migration —— 一条命令跑完。
// 所有断言都是「链上真实状态」，不是 mock。
const assert = require("node:assert/strict");
const path = require("path");
const { ethers } = require("ethers");
const { provider: ganacheProvider } = require("ganache");

const artifact = require(path.join(__dirname, "..", "artifacts", "VideoCredit.json"));

const id = (s) => ethers.id(s); // 任意字符串 → bytes32，链上只存 32 字节
const lc = (a) => String(a).toLowerCase();

async function expectRevert(label, fn) {
  try {
    await fn();
  } catch (e) {
    const msg = (e.shortMessage || e.message || String(e)).split("\n")[0];
    console.log(`  ✓ ${label} —— 按预期 revert（${msg.slice(0, 80)}）`);
    return;
  }
  assert.fail(`${label}：应该失败，但交易成功了`);
}

async function main() {
  // ① 进程内起链：chainId 1337（本地链约定，和 Ganache / Remix VM 一致）
  const provider = ganacheProvider({
    logging: { quiet: true },
    chain: { chainId: 1337 },
    wallet: { totalAccounts: 4, defaultBalance: 1000 },
  });
  const browser = new ethers.BrowserProvider(provider);
  const accounts = await browser.send("eth_accounts", []);
  const platform = await browser.getSigner(accounts[0]);
  const alice = await browser.getSigner(accounts[1]);
  const bob = await browser.getSigner(accounts[2]);
  const platformAddr = lc(accounts[0]);
  const aliceAddr = lc(accounts[1]);
  const bobAddr = lc(accounts[2]);

  // ② 部署：transferable=false，即「积分不可用户间转让」
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, platform);
  const token = await factory.deploy(false);
  await token.waitForDeployment();
  const tokenAddr = lc(await token.getAddress());
  console.log(`\n链 ID 1337 · 代币部署在 ${tokenAddr}\n`);

  // ── 用例 1：mint + decimals ───────────────────────────────────
  await (await token.mint(aliceAddr, 100n)).wait();
  assert.equal(await token.balanceOf(aliceAddr), 100n);
  assert.equal(await token.decimals(), 0n); // 积分是整数，不是 18 位小数
  console.log("✓ 1. mint 100 VCR，decimals = 0");

  // ── 用例 2：reserve（用户先 approve，平台把币托管进合约）──────
  const id1 = id("video-001"); // 对应后端 tasks.id + 视频，真实系统里用 uuid
  await (await token.connect(alice).approve(platformAddr, 10n)).wait();
  await (await token.reserve(aliceAddr, 10n, id1)).wait();

  assert.equal(await token.balanceOf(aliceAddr), 90n);
  assert.equal(await token.balanceOf(tokenAddr), 10n); // 币在合约里，不在平台私钥手里
  const esc1 = await token.escrowOf(id1);
  assert.equal(lc(esc1.user), aliceAddr);
  assert.equal(esc1.amount, 10n);
  assert.equal(esc1.closed, false);
  console.log("✓ 2. reserve 10 VCR：用户 90，合约托管 10，escrowOf 可查");

  // ── 用例 3：settle（视频已交付 → 销毁托管额）─────────────────
  await (await token.settle(id1)).wait();
  assert.equal(await token.balanceOf(tokenAddr), 0n);
  assert.equal(await token.totalSupply(), 90n); // 100 - 10
  assert.equal((await token.escrowOf(id1)).closed, true);
  console.log("✓ 3. settle：托管清零，totalSupply 100 → 90（销毁 = 交付完成）");

  // ── 用例 4：refund（生成失败 → 原路退回）────────────────────
  const id2 = id("video-002");
  await (await token.connect(alice).approve(platformAddr, 20n)).wait();
  await (await token.reserve(aliceAddr, 20n, id2)).wait();
  assert.equal(await token.balanceOf(aliceAddr), 70n);
  await (await token.refund(id2)).wait();
  assert.equal(await token.balanceOf(aliceAddr), 90n); // 回到 reserve 之前
  console.log("✓ 4. reserve → refund：90 → 70 → 90，生成失败不扣钱");

  // ── 用例 5：负向路径 ─────────────────────────────────────────
  console.log("5. 负向路径：");

  // 5.1 同一 videoId 不能冻结两次（防重放/刷单）
  await expectRevert("同一 videoId 重复 reserve", async () => {
    await (await token.connect(alice).approve(platformAddr, 10n)).wait();
    await (await token.reserve(aliceAddr, 10n, id1)).wait();
  });

  // 5.2 没有 approve 额度 → 平台无法扣任何人的钱
  await expectRevert("无授权额度时 reserve", async () => {
    await (await token.reserve(bobAddr, 1n, id("video-003"))).wait();
  });

  // 5.3 普通用户没有 SETTLER_ROLE，不能自己发起扣款
  await expectRevert("普通用户调用 reserve", async () => {
    await (await token.connect(alice).reserve(bobAddr, 1n, id("video-004"))).wait();
  });

  // 5.4 transferable=false 时用户之间不能互转
  await expectRevert("用户之间 transfer", async () => {
    await (await token.connect(alice).transfer(bobAddr, 1n)).wait();
  });

  // 5.5 consume 也强制 allowance：没有授权的地址不能被销毁
  await expectRevert("无授权时 consume", async () => {
    await (await token.consume(bobAddr, 1n, id("video-005"))).wait();
  });
  console.log("  ✓ consume 没有跳过 allowance，平台最多只能花用户授权过的额度");

  // ── 用例 6：影子链模式 consume（用户先 approve，平台按任务销毁）──
  const id3 = id("video-003");
  await (await token.connect(alice).approve(platformAddr, 5n)).wait();
  await (await token.consume(aliceAddr, 5n, id3)).wait();
  assert.equal(await token.balanceOf(aliceAddr), 85n); // 用例 4 之后是 90
  assert.equal(await token.totalSupply(), 85n);
  console.log("✓ 6. consume：授权 5 → 销毁 5，用户余额 90 → 85、totalSupply 90 → 85");

  const grantId = id("local-credit-1");
  await (await token.mintWithRef(aliceAddr, 7n, grantId)).wait();
  await expectRevert("重复流水不会再次铸币", async () => {
    await (await token.mintWithRef(aliceAddr, 7n, grantId)).wait();
  });
  await (await token.connect(alice).approve(platformAddr, 15n, { gasLimit: 60_000n })).wait();
  await expectRevert("重复流水不会再次销毁", async () => {
    await (await token.consume(aliceAddr, 5n, id3)).wait();
  });
  assert.equal(await token.balanceOf(aliceAddr), 92n);
  assert.equal(await token.shadowApplied(grantId), true);

  console.log("\n全部通过。报告里的「实验过程」可以直接引用上面的输出。");
  process.exit(0);
}

main().catch((e) => {
  console.error("失败：", e);
  process.exit(1);
});
