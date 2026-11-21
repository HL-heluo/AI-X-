// 部署到一条**已经在跑**的本地链（通常是 `npx ganache` 或 Ganache GUI），
// 这样 Remix / 区块浏览器 / 本地脚本才能看到 VCR 余额（不需要钱包）。
//
// 步骤：
//   终端 A: npx ganache --chain.chainId 1337 --wallet.totalAccounts 5
//   终端 B: npm run deploy
//
// 环境变量：
//   RPC_URL       默认 http://127.0.0.1:8545
//   PRIVATE_KEY   可选。不填就用节点第一个未锁定账户（ganache 默认都解锁）
//   TRANSFERABLE  可选，默认 false（不可转让积分）
const path = require("path");
const { ethers } = require("ethers");

const artifact = require(path.join(__dirname, "..", "artifacts", "VideoCredit.json"));

async function main() {
  const rpcUrl = process.env.RPC_URL || "http://127.0.0.1:8545";
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const network = await provider.getNetwork();

  const signer = process.env.PRIVATE_KEY
    ? new ethers.Wallet(process.env.PRIVATE_KEY, provider)
    : await provider.getSigner(0);
  const deployer = await signer.getAddress();

  const transferable = process.env.TRANSFERABLE === "true";
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, signer);
  const token = await factory.deploy(transferable);
  await token.waitForDeployment();
  const tokenAddr = await token.getAddress();

  console.log("部署完成：");
  console.log(`  RPC        ${rpcUrl}（chainId ${network.chainId}）`);
  console.log(`  部署者     ${deployer}`);
  console.log(`  VideoCredit ${tokenAddr}`);
  console.log(`  可转让     ${transferable}`);
  console.log("\n想查余额：Remix 里调 balanceOf，或写个脚本；以后接钱包时导入上面的地址即可。");
  console.log("第一个账户即平台账户，拥有 MINTER_ROLE / SETTLER_ROLE。");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
