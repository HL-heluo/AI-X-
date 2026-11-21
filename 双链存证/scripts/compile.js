// 用 solc-js 编译合约，输出 artifacts/<Contract>.json（abi + bytecode）。
//
// 为什么不用 Truffle / Hardhat：
//   1. Truffle & Ganache 已于 2023-09-21 被 Consensys 宣布日落，
//      2023-12-20 起代码库冻结为公开存档、Ganache 不再跟进硬分叉；
//   2. Hardhat 会额外下载 solc 原生二进制到用户缓存目录，国内网络经常卡住；
//   3. solc-js 是纯 JS（wasm），npm 装完即可离线编译，Windows / WSL / macOS 都一样。
//
// 用法：npm install && npm run compile
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const ROOT = path.join(__dirname, "..");
const CONTRACTS = path.join(ROOT, "contracts");
const NODE_MODULES = path.join(ROOT, "node_modules");
const OUT = path.join(ROOT, "artifacts");

function readSources() {
  const sources = {};
  for (const name of fs.readdirSync(CONTRACTS)) {
    if (name.endsWith(".sol")) {
      sources[name] = { content: fs.readFileSync(path.join(CONTRACTS, name), "utf8") };
    }
  }
  return sources;
}

// solc-js 不会自己去 node_modules 找 @openzeppelin，必须给这个回调。
function findImports(importPath) {
  const candidates = [path.join(NODE_MODULES, importPath), path.join(CONTRACTS, importPath)];
  for (const p of candidates) {
    if (fs.existsSync(p)) return { contents: fs.readFileSync(p, "utf8") };
  }
  return { error: `import not found: ${importPath}` };
}

function main() {
  const input = {
    language: "Solidity",
    sources: readSources(),
    settings: {
      optimizer: { enabled: true, runs: 200 },
      // 必须显式指定 EVM 版本：solc 0.8.30+ 默认目标是最新硬分叉（Cancun/Prague），
      // 会用 MCOPY 等新 opcode，而 Ganache 7.9.2（2023 年最后版本）只支持到 Shanghai，
      // 结果就是链上执行报 "invalid opcode"。钉成 shanghai 才能本地跑通。
      evmVersion: "shanghai",
      outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
    },
  };

  const output = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));

  const errors = (output.errors || []).filter((e) => e.severity === "error");
  if (errors.length > 0) {
    for (const e of errors) console.error(e.formattedMessage);
    process.exit(1);
  }
  for (const e of output.errors || []) console.warn(e.formattedMessage);

  fs.mkdirSync(OUT, { recursive: true });
  for (const [file, contracts] of Object.entries(output.contracts || {})) {
    for (const [name, c] of Object.entries(contracts)) {
      // 抽象合约（ERC20 / AccessControl 等）没有 bytecode，跳过，只留我们自己的两个。
      if (!c.evm.bytecode.object) continue;
      const artifact = {
        contractName: name,
        source: file,
        solc: solc.version(),
        abi: c.abi,
        bytecode: "0x" + c.evm.bytecode.object,
      };
      fs.writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify(artifact, null, 2));
      console.log(`✓ ${name}  (${file})  bytecode ${c.evm.bytecode.object.length / 2} bytes`);
    }
  }
}

main();
