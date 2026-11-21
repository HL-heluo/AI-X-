// 手动铸币：给某个地址发 VCR（只有 MINTER_ROLE 能调，也就是部署者账户）。
//
// 用法：
//   node scripts/mint.js <代币地址> <收款地址> <数量>
//   node scripts/mint.js 0xABC... 0xDEF... 100
//
// 前提：本地链在跑（npx ganache），且 RPC 为 http://127.0.0.1:8545（可用 RPC_URL 覆盖）。
const path = require("path");
const { ethers } = require("ethers");

const artifact = require(path.join(__dirname, "..", "artifacts", "VideoCredit.json"));

async function main() {
  const [tokenAddr, to, amountArg] = process.argv.slice(2);
  if (!tokenAddr || !to || !amountArg) {
    console.log("用法：node scripts/mint.js <代币地址> <收款地址> <数量>");
    process.exit(1);
  }
  const provider = new ethers.JsonRpcProvider(process.env.RPC_URL || "http://127.0.0.1:8545");
  const signer = await provider.getSigner(0);
  const token = new ethers.Contract(tokenAddr, artifact.abi, signer);

  const amount = BigInt(amountArg);
  const tx = await token.mint(to, amount);
  console.log(`mint(${to}, ${amount}) → 交易 ${tx.hash}`);
  const rc = await tx.wait();
  console.log(`已上链，区块 ${rc.blockNumber}；现在余额：${await token.balanceOf(to)} VCR`);
}

main().catch((e) => {
  console.error("失败：", e.shortMessage || e.message || e);
  process.exit(1);
});
