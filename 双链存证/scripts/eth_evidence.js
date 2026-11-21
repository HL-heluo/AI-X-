// 把 Python 侧产出的回执（evidence_receipt.json）写到以太坊存证合约。
//
// 用法：
//   node scripts/eth_evidence.js record receipt.json          # 没配地址就自动部署一个新合约
//   node scripts/eth_evidence.js verify <videoId> <sha256> <perceptualHash> [maxDistance]
//
// 环境变量：
//   RPC_URL          默认 http://127.0.0.1:8545
//   EVIDENCE_ADDRESS 已有合约地址；不填则部署新的并打印地址
//   CREATOR_ADDRESS  创作者钱包地址；不填用部署者地址（演示用）
//   PRIVATE_KEY      可选，用私钥签名；不填用节点第一个解锁账户
const fs = require("node:fs");
const path = require("node:path");
const { ethers } = require("ethers");

const artifact = require(path.join(__dirname, "..", "artifacts", "VideoEvidence.json"));
const videoIdHash = (s) => ethers.id(s);
const toBytes32 = (hex) => "0x" + String(hex).replace(/^0x/, "").padStart(64, "0");
const toUint64 = (hex) => BigInt("0x" + String(hex).replace(/^0x/, ""));

async function getContext() {
  const rpcUrl = process.env.RPC_URL || "http://127.0.0.1:8545";
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  await provider.getNetwork();
  const signer = process.env.PRIVATE_KEY
    ? new ethers.Wallet(process.env.PRIVATE_KEY, provider)
    : await provider.getSigner(0);
  return { provider, signer };
}

async function getRegistry(signer) {
  if (process.env.EVIDENCE_ADDRESS) {
    return new ethers.Contract(process.env.EVIDENCE_ADDRESS, artifact.abi, signer);
  }
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, signer);
  const registry = await factory.deploy();
  await registry.waitForDeployment();
  console.log(`（没有配置 EVIDENCE_ADDRESS，已部署新合约：${await registry.getAddress()}）`);
  console.log("  下次想复用，先 export EVIDENCE_ADDRESS=<上面的地址>\n");
  return registry;
}

async function cmdRecord(receiptPath) {
  const receipt = JSON.parse(fs.readFileSync(receiptPath, "utf8"));
  const fp = receipt.fingerprint || {};
  const sha = fp.sha256 || receipt.sha256;
  const ph = fp.perceptualHash || receipt.perceptualHash;
  if (!receipt.videoId || !sha || !ph) {
    throw new Error("回执里缺 videoId / fingerprint.sha256 / fingerprint.perceptualHash");
  }

  const { signer } = await getContext();
  const registry = await getRegistry(signer);
  const creator = process.env.CREATOR_ADDRESS || (await signer.getAddress());
  const paramsHash = ethers.id(receipt.generationParams || "{}");

  console.log(`videoId      ${receipt.videoId}`);
  console.log(`sha256       ${sha}`);
  console.log(`perceptual   ${ph}`);
  console.log(`ipfsCid      ${receipt.ipfsCid || "(空)"}`);
  console.log(`creator      ${creator}`);

  const tx = await registry.recordEvidence(
    videoIdHash(receipt.videoId), toBytes32(sha), toUint64(ph), receipt.ipfsCid || "", creator, paramsHash,
  );
  console.log(`\n已发送交易 ${tx.hash}，等待上链…`);
  const rc = await tx.wait();
  console.log(`已上链，区块 ${rc.blockNumber}，gasUsed ${rc.gasUsed}`);

  const rec = await registry.getEvidence(videoIdHash(receipt.videoId));
  console.log("\n读回：");
  console.log(`  sha256        ${rec.sha256}`);
  console.log(`  creator       ${rec.creator}`);
  console.log(`  recordedAt    ${new Date(Number(rec.recordedAt) * 1000).toISOString()}`);
  console.log(`  ipfsCid       ${rec.ipfsCid}`);
  console.log(`\n下一步验证：node scripts/eth_evidence.js verify ${receipt.videoId} ${sha} ${ph} 10`);
}

async function cmdVerify(videoId, sha, ph, maxDistance = "10") {
  const { signer } = await getContext();
  const registry = await getRegistry(signer);
  if (!process.env.EVIDENCE_ADDRESS) {
    console.log("提示：verify 通常应带上 EVIDENCE_ADDRESS，否则查的是刚部署的空合约。\n");
  }
  const key = videoIdHash(videoId);
  const [exact, recordedAt] = await registry.verifyExact(key, toBytes32(sha));
  const [similar, distance] = await registry.verifyPerceptual(key, toUint64(ph), Number(maxDistance));
  console.log(JSON.stringify({
    videoId,
    recordedAt: new Date(Number(recordedAt) * 1000).toISOString(),
    exactMatch: exact,
    perceptual: { distance: Number(distance), maxDistance: Number(maxDistance), match: similar },
  }, null, 2));
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === "record" && rest[0]) return cmdRecord(rest[0]);
  if (cmd === "verify" && rest.length >= 3) return cmdVerify(rest[0], rest[1], rest[2], rest[3]);
  console.log("用法：\n  node scripts/eth_evidence.js record <evidence_receipt.json>\n  node scripts/eth_evidence.js verify <videoId> <sha256> <perceptualHash> [maxDistance]\n");
  process.exit(1);
}

main().catch((e) => {
  console.error("失败：", e.shortMessage || e.message || e);
  process.exit(1);
});
