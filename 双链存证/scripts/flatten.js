// 把带 import 的合约「拍平」成单文件，方便直接粘到在线 Remix（remix.ethereum.org）。
//
// 为什么需要：
//   · Remix 里 import "@openzeppelin/..." 会走 unpkg/npm CDN，国内网络经常拉不动；
//   · 打开 Remix 本来就要网，能少一个外部依赖就少一个失败点；
//   · 单文件也让报告附录可以直接贴源码，评阅人不用装环境。
//
// 用法：node scripts/flatten.js
// 产物：remix/VideoCredit.flat.sol、remix/VideoEvidence.flat.sol
// 并用 solc-js 重新编译，验证拍平后的 bytecode 与 artifacts 里完全一致。
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const ROOT = path.join(__dirname, "..");
const CONTRACTS = path.join(ROOT, "contracts");
const NODE_MODULES = path.join(ROOT, "node_modules");
const OUT = path.join(ROOT, "remix");

const IMPORT_RE = /^import\s+(?:\{[^}]*\}\s+from\s+)?["']([^"']+)["']\s*;/gm;
const PRAGMA_RE = /^pragma\s+solidity[^;]*;/gm;
const SPDX_RE = /^\/\/\s*SPDX-License-Identifier:.*$/gm;

function resolveImport(fromFile, spec) {
  if (spec.startsWith(".")) {
    return path.resolve(path.dirname(fromFile), spec);
  }
  if (spec.startsWith("@openzeppelin/")) {
    // @openzeppelin/contracts/xxx.sol → node_modules/@openzeppelin/contracts/xxx.sol
    return path.join(NODE_MODULES, spec);
  }
  return path.resolve(path.dirname(fromFile), spec);
}

function collect(entry, seen, order) {
  const abs = path.resolve(entry);
  if (seen.has(abs)) return;
  seen.add(abs);
  const source = fs.readFileSync(abs, "utf8");
  const deps = [];
  let m;
  IMPORT_RE.lastIndex = 0;
  while ((m = IMPORT_RE.exec(source)) !== null) {
    deps.push(resolveImport(abs, m[1]));
  }
  for (const dep of deps) collect(dep, seen, order);
  order.push(abs); // 后序：依赖先出现，被依赖的合约先定义
}

function stripBoilerplate(source) {
  return source
    .replace(SPDX_RE, "")
    .replace(PRAGMA_RE, "")
    .replace(IMPORT_RE, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function flatten(entryName, pragma) {
  const entry = path.join(CONTRACTS, entryName);
  const seen = new Set();
  const order = [];
  collect(entry, seen, order);

  const body = order
    .map((file) => {
      const rel = path.relative(ROOT, file).split(path.sep).join("/");
      return `// ─────────────────────────────────────────────────────────────\n// 来源：${rel}\n// ─────────────────────────────────────────────────────────────\n${stripBoilerplate(fs.readFileSync(file, "utf8"))}\n`;
    })
    .join("\n");

  return `// SPDX-License-Identifier: MIT\n${pragma}\n\n// 本文件由 scripts/flatten.js 自动生成，供在线 Remix 使用（把 OpenZeppelin 依赖内联进来）。\n// 不要手改；改 contracts/ 下的源文件后重跑 node scripts/flatten.js。\n\n${body}\n`;
}

// Solidity 会在 bytecode 末尾追加 CBOR 元数据（含源文件名/内容哈希），
// 拍平后源文件名变了，元数据必然不同 —— 比较时要先把尾巴切掉。
function stripMetadata(hex) {
  const b = String(hex).replace(/^0x/, "");
  if (b.length < 4) return b;
  const len = parseInt(b.slice(-4), 16);
  if (!Number.isFinite(len) || len * 2 + 4 > b.length) return b;
  return b.slice(0, b.length - 4 - len * 2);
}

// 用 solc-js 编译拍平后的单文件，和 artifacts 里的 bytecode 对比
function verify(flatSource, contractName, pragma) {
  const input = {
    language: "Solidity",
    sources: { [`${contractName}.flat.sol`]: { content: flatSource } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: "shanghai",
      outputSelection: { "*": { "*": ["evm.bytecode.object"] } },
    },
  };
  const out = JSON.parse(solc.compile(JSON.stringify(input)));
  const errors = (out.errors || []).filter((e) => e.severity === "error");
  if (errors.length) {
    for (const e of errors) console.error(e.formattedMessage);
    throw new Error(`拍平后的 ${contractName} 编译失败`);
  }
  const flatBytecode = "0x" + out.contracts[`${contractName}.flat.sol`][contractName].evm.bytecode.object;
  const artifactPath = path.join(ROOT, "artifacts", `${contractName}.json`);
  const expected = JSON.parse(fs.readFileSync(artifactPath, "utf8")).bytecode;
  if (stripMetadata(flatBytecode) !== stripMetadata(expected)) {
    throw new Error(`${contractName} 拍平后 bytecode 与 artifacts 不一致（依赖版本或编译设置不同？）`);
  }
  return flatBytecode.length / 2 - 1;
}

function main() {
  fs.mkdirSync(OUT, { recursive: true });
  // VideoCredit / VideoEvidence 的入口文件里 pragma 都是 ^0.8.24
  const jobs = [
    ["VideoCredit.sol", "VideoCredit", "pragma solidity ^0.8.24;"],
    ["VideoEvidence.sol", "VideoEvidence", "pragma solidity ^0.8.24;"],
  ];
  for (const [file, name, pragma] of jobs) {
    const flat = flatten(file, pragma);
    const outFile = path.join(OUT, `${name}.flat.sol`);
    fs.writeFileSync(outFile, flat);
    const size = verify(flat, name, pragma);
    console.log(`✓ ${name}.flat.sol  ${Math.round(flat.length / 1024)} KB  bytecode ${size} bytes（与 artifacts 一致）`);
  }
  console.log(`\n产物在 ${OUT}，直接粘到 Remix 即可。`);
}

main();
