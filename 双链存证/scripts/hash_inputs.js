// 给 Remix 准备输入参数。
//
// Remix 的函数输入框要求：
//   · bytes32 → 0x 开头的 64 位十六进制；
//   · uint64  → 十进制整数（不是 0x 十六进制！）；
//   · string  → 原样字符串；
//   · address → 0x 地址。
// 手动换算最容易错，所以用这个脚本生成「复制粘贴即可」的值。
//
// 用法：
//   node scripts/hash_inputs.js reserve <videoId> <amount> <userAddress>
//   node scripts/hash_inputs.js evidence <videoId> <sha256> <perceptualHash> <creatorAddress> [paramsJson]
//   node scripts/hash_inputs.js phash <perceptualHash>      # 只算 uint64 十进制
const { ethers } = require("ethers");

const toBytes32 = (hex) => "0x" + String(hex).replace(/^0x/, "").padStart(64, "0");

function printReserve(videoId, amount, userAddress) {
  console.log("VideoCredit.reserve(user, amount, videoIdHash) 的三个参数：");
  console.log(`  user        ${userAddress}`);
  console.log(`  amount      ${amount}`);
  console.log(`  videoIdHash ${ethers.id(videoId)}`);
  console.log("\nVideoCredit.consume 在推荐版里不存在；Approve 用 approve(spender, amount)：");
  console.log(`  spender     <平台地址>`);
  console.log(`  amount      ${amount}`);
}

function printEvidence(videoId, sha256, phash, creator, paramsJson = "{}") {
  const ph = String(phash).replace(/^0x/, "");
  if (!/^[0-9a-fA-F]{1,16}$/.test(ph)) throw new Error("感知哈希应为 1~16 位十六进制");
  const sha = String(sha256).replace(/^0x/, "");
  if (!/^[0-9a-fA-F]{64}$/.test(sha)) throw new Error("sha256 应为 64 位十六进制");
  console.log("VideoEvidence.recordEvidence 的参数（按顺序复制）：");
  console.log(`  videoIdHash    ${ethers.id(videoId)}`);
  console.log(`  sha256         ${toBytes32(sha)}`);
  console.log(`  perceptualHash ${BigInt("0x" + ph).toString()}   ← uint64 用十进制`);
  console.log(`  ipfsCid        <把 CID 字符串原样粘贴>`);
  console.log(`  creator        ${creator}`);
  console.log(`  paramsHash     ${ethers.id(paramsJson)}   ← keccak256(${JSON.stringify(paramsJson)})`);
  console.log("\nVideoEvidence.verifyExact 的参数：");
  console.log(`  videoIdHash    ${ethers.id(videoId)}`);
  console.log(`  candidateSha256 ${toBytes32(sha)}`);
  console.log("\nVideoEvidence.verifyPerceptual 的参数：");
  console.log(`  videoIdHash    ${ethers.id(videoId)}`);
  console.log(`  candidateHash  ${BigInt("0x" + ph).toString()}`);
  console.log(`  maxDistance    10`);
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === "reserve" && rest.length >= 3) return printReserve(...rest);
  if (cmd === "evidence" && rest.length >= 4) return printEvidence(...rest);
  if (cmd === "phash" && rest[0]) {
    console.log(BigInt("0x" + String(rest[0]).replace(/^0x/, "")).toString());
    return;
  }
  console.log(
    "用法：\n" +
      "  node scripts/hash_inputs.js reserve <videoId> <amount> <userAddress>\n" +
      "  node scripts/hash_inputs.js evidence <videoId> <sha256> <perceptualHash> <creatorAddress> [paramsJson]\n" +
      "  node scripts/hash_inputs.js phash <perceptualHash>\n"
  );
  process.exit(1);
}

main();
