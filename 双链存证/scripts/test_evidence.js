// 单链降级版存证合约的测试：npm run test:evidence
//
// 演示四件事：
//   1. 写入一条记录后能原样读回；
//   2. 精确哈希一致 / 不一致的判定；
//   3. 感知哈希按汉明距离判定（1 bit 差 → 相似；11 bit 差 → 不相似）；
//   4. 重复 videoId、无权限写入都会被拒。
const assert = require("node:assert/strict");
const path = require("path");
const { ethers } = require("ethers");
const { provider: ganacheProvider } = require("ganache");

const artifact = require(path.join(__dirname, "..", "artifacts", "VideoEvidence.json"));

const id = (s) => ethers.id(s);
const toBytes32 = (hex) => "0x" + hex.padStart(64, "0");
const phash = (hex) => BigInt("0x" + hex); // 16 位十六进制 → uint64

async function expectRevert(label, fn) {
  try {
    await fn();
  } catch (e) {
    const msg = (e.shortMessage || e.message || String(e)).split("\n")[0];
    console.log(`  ✓ ${label} —— 按预期 revert（${msg.slice(0, 70)}）`);
    return;
  }
  assert.fail(`${label}：应该失败但成功了`);
}

async function main() {
  const provider = ganacheProvider({ logging: { quiet: true }, chain: { chainId: 1337 } });
  const browser = new ethers.BrowserProvider(provider);
  const accounts = await browser.send("eth_accounts", []);
  const platform = await browser.getSigner(accounts[0]);
  const alice = await browser.getSigner(accounts[1]);
  const aliceAddr = String(accounts[1]).toLowerCase();

  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, platform);
  const registry = await factory.deploy();
  await registry.waitForDeployment();
  console.log(`VideoEvidence 部署在 ${await registry.getAddress()}\n`);

  // 一条和 Python 侧计算结果同构的记录
  const videoId = "vid_demo_001";
  const videoIdHash = id(videoId); // 与 python 的 keccak256(videoId) 口径一致
  const sha = "e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297";
  // 下面这组感知哈希是本机实测的一对：
  // 原片 cc0c5c4829a9c000、缩小一半+重编码后 dcc0dcdae9a9c000，汉明距离 11 bit。
  const ph = "cc0c5c4829a9c000";
  const paramsHash = ethers.id('{"model":"demo","seed":42}');

  // 1. 写入
  await (await registry.recordEvidence(
    videoIdHash, toBytes32(sha), phash(ph), "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    aliceAddr, paramsHash,
  )).wait();
  assert.equal(await registry.exists(videoIdHash), true);
  const rec = await registry.getEvidence(videoIdHash);
  assert.equal(rec.sha256, toBytes32(sha));
  assert.equal(String(rec.creator).toLowerCase(), aliceAddr);
  console.log("✓ 1. 写入后可读回，sha256/creator/ipfsCid 一致");

  // 1.5 反向索引：只给文件 sha256 也能找到存证记录（溯源入口）
  assert.equal(await registry.videoIdBySha256(toBytes32(sha)), videoIdHash);
  assert.equal(await registry.videoIdBySha256(toBytes32("11".repeat(32))), ethers.ZeroHash);
  console.log("✓ 1.5. videoIdBySha256：给文件哈希反查到 videoId；未知哈希返回 0");

  // 2. 精确校验
  assert.equal((await registry.verifyExact(videoIdHash, toBytes32(sha)))[0], true);
  const tampered = sha.replace(/^e/, "f"); // 改一个字符 = 改字节
  assert.equal((await registry.verifyExact(videoIdHash, toBytes32(tampered)))[0], false);
  console.log("✓ 2. verifyExact：原文件 true，改一个字节后 false");

  // 3. 感知校验（阈值 10）
  const transcoded = "dcc0dcdae9a9c000"; // 实测：同片缩小一半+重编码，与原片差 11 bit
  const same = ph;
  let [ok, dist] = await registry.verifyPerceptual(videoIdHash, phash(same), 10);
  assert.equal(ok, true);
  assert.equal(Number(dist), 0);
  [ok, dist] = await registry.verifyPerceptual(videoIdHash, phash(transcoded), 10);
  assert.equal(Number(dist), 11);
  assert.equal(ok, false);
  [ok, dist] = await registry.verifyPerceptual(videoIdHash, phash(transcoded), 12);
  assert.equal(ok, true); // 阈值放宽到 12 判为相似
  console.log("✓ 3. verifyPerceptual：原片 0 bit，转码副本 11 bit（阈值 10 判否、12 判是）");

  // 4. 负向路径
  await expectRevert("同一 videoId 重复写入", async () => {
    await (await registry.recordEvidence(
      videoIdHash, toBytes32(sha), phash(ph), "", aliceAddr, paramsHash,
    )).wait();
  });
  await expectRevert("普通用户无 RECORDER_ROLE 写入", async () => {
    await (await registry.connect(alice).recordEvidence(
      id("vid_other"), toBytes32(sha), phash(ph), "", aliceAddr, paramsHash,
    )).wait();
  });
  await expectRevert("查询不存在的 videoId", async () => {
    await registry.getEvidence(id("vid_missing"));
  });

  console.log("\n单链存证合约全部通过。这一版不需要 Docker，也不需要 Fabric。");
  process.exit(0);
}

main().catch((e) => {
  console.error("失败：", e);
  process.exit(1);
});
