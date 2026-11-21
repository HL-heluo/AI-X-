"use strict";

// ─────────────────────────────────────────────────────────────
// 为什么需要这个东西：
//
// Hyperledger Fabric 的官方 Gateway 客户端只有 Go / Node / Java 三种。
// 本项目的后端是 Python（FastAPI），如果直接找 Python SDK，会落到
// 早已停止维护的 fabric-sdk-py 上。最省事也最稳的做法：
//
//   Python(FastAPI)  ──HTTP──▶  本文件(Node)  ──gRPC──▶  peer
//
// 这个 Node 进程只管两件事：submitTransaction（写）和
// evaluateTransaction（读）。20 行 HTTP 路由 + 30 行连接配置，
// 不引入 express，避免多一个依赖。
//
// 运行前提：fabric-samples/test-network 已经 up，链码已部署。
// 环境变量见文件底部默认值；在 WSL 里跑最省事（证书路径都是 Linux 路径）。
// ─────────────────────────────────────────────────────────────

const http = require("node:http");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const { connect, signers, hash } = require("@hyperledger/fabric-gateway");
const grpc = require("@grpc/grpc-js");

// ── 配置（全部可用环境变量覆盖）──────────────────────────────
const SAMPLES = process.env.FABRIC_SAMPLES_DIR || path.join(process.env.HOME || ".", "fabric-samples");
const CRYPTO = process.env.CRYPTO_PATH ||
  path.join(SAMPLES, "test-network", "organizations", "peerOrganizations", "org1.example.com");

const PEER_ENDPOINT = process.env.PEER_ENDPOINT || "localhost:7051";
const PEER_HOST_ALIAS = process.env.PEER_HOST_ALIAS || "peer0.org1.example.com";
const MSP_ID = process.env.MSP_ID || "Org1MSP";
const CHANNEL = process.env.CHANNEL || "videochannel";
const CHAINCODE = process.env.CHAINCODE || "video-evidence";
const PORT = Number(process.env.PORT || 8801);
const NETWORK_ID = process.env.FABRIC_NETWORK_ID || "local-fabric";
const TOKEN = process.env.FABRIC_BRIDGE_TOKEN || "";
const VIDEO_ID = /^[A-Za-z0-9._-]{1,128}$/;
const EVIDENCE_FIELDS = [
  "videoId", "sha256", "ownerId", "schemaVersion", "generationParams", "mediaMeta",
  "width", "height", "durationMs",
];
const READ_METHODS = new Set([
  "ReadVideoRecord", "GetVideoRecord", "VerifyExactHash", "QueryRecordsByOwner",
  "QueryRecordsByCreator", "QueryAllRecords", "FindVideoIdsBySha256", "GetRecordHistory",
  "GetWorkTransfer",
]);

const TLS_CERT = process.env.TLS_CERT_PATH ||
  path.join(CRYPTO, "peers", "peer0.org1.example.com", "tls", "ca.crt");
const USER_MSP = process.env.USER_MSP_PATH ||
  path.join(CRYPTO, "users", "User1@org1.example.com", "msp");
const CERT_PATH = process.env.CERT_PATH ||
  path.join(USER_MSP, "signcerts", "User1@org1.example.com-cert.pem");
const KEY_DIR = process.env.KEY_DIR || path.join(USER_MSP, "keystore");

function findPrivateKey(dir) {
  // keystore 里的文件名是随机的（priv_sk 或一串 hash），只能按目录找。
  const files = fs.readdirSync(dir);
  const hit = files.find((f) => f.endsWith("_sk") || f === "priv_sk" || !f.includes("."));
  if (!hit) throw new Error(`keystore 目录里找不到私钥文件: ${dir}`);
  return path.join(dir, hit);
}

async function newClient() {
  const tlsRootPem = fs.readFileSync(TLS_CERT);
  const credentials = grpc.credentials.createSsl(tlsRootPem);
  return new grpc.Client(PEER_ENDPOINT, credentials, {
    "grpc.ssl_target_name_override": PEER_HOST_ALIAS,
  });
}

function newIdentity() {
  return {
    mspId: MSP_ID,
    credentials: fs.readFileSync(CERT_PATH),
  };
}

function newSigner() {
  const pem = fs.readFileSync(findPrivateKey(KEY_DIR));
  return signers.newPrivateKeySigner(crypto.createPrivateKey(pem));
}

// ── HTTP 路由 ───────────────────────────────────────────────
class RequestError extends Error {}

async function readJson(req) {
  const chunks = [];
  let length = 0;
  for await (const chunk of req) {
    length += chunk.length;
    if (length > 16_384) throw new RequestError("request_too_large");
    chunks.push(chunk);
  }
  let body;
  try {
    body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new RequestError("invalid_json");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new RequestError("invalid_body");
  return body;
}

function isAuthorized(req) {
  const actual = Buffer.from(req.headers.authorization || "");
  const expected = Buffer.from(`Bearer ${TOKEN}`);
  return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}

function validateEvidence(body) {
  if (Object.keys(body).length !== EVIDENCE_FIELDS.length ||
      !EVIDENCE_FIELDS.every((key) => Object.hasOwn(body, key)) ||
      body.schemaVersion !== 3 || typeof body.videoId !== "string" || !VIDEO_ID.test(body.videoId) ||
      typeof body.ownerId !== "string" || !/^[0-9a-f]{32}$/.test(body.ownerId) ||
      typeof body.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(body.sha256) ||
      typeof body.generationParams !== "string" || body.generationParams.length > 2048 ||
      typeof body.mediaMeta !== "string" || body.mediaMeta.length > 512 ||
      [body.width, body.height, body.durationMs].some((n) => n !== null && (!Number.isSafeInteger(n) || n < 0))) {
    throw new RequestError("invalid_evidence");
  }
}

function validateTrade(body) {
  const params = ["tradeId", "videoId", "sequence", "fromHolder", "toHolder", "price"];
  if (Object.keys(body).length !== params.length ||
      !params.every((key) => Object.hasOwn(body, key)) ||
      [body.tradeId, body.videoId].some((id) => typeof id !== "string" || !VIDEO_ID.test(id)) ||
      [body.fromHolder, body.toHolder].some((id) => typeof id !== "string" || !/^[0-9a-f]{32}$/.test(id)) ||
      body.fromHolder === body.toHolder ||
      !Number.isSafeInteger(body.sequence) || body.sequence < 1 ||
      !Number.isSafeInteger(body.price) || body.price < 1 || body.price > 1000000000) {
    throw new RequestError("invalid_trade");
  }
}

function send(res, code, obj) {
  const payload = JSON.stringify(obj);
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function main() {
  const initialize = process.argv.includes("--initialize");
  if (!initialize && TOKEN.length < 24) throw new Error("请配置独立的 FABRIC_BRIDGE_TOKEN（至少 24 字符）");
  const client = await newClient();
  const gateway = connect({
    client,
    identity: newIdentity(),
    signer: newSigner(),
    hash: hash.sha256,
    evaluateOptions: () => ({ deadline: Date.now() + 4_000 }),
    endorseOptions: () => ({ deadline: Date.now() + 6_000 }),
    submitOptions: () => ({ deadline: Date.now() + 5_000 }),
    commitStatusOptions: () => ({ deadline: Date.now() + 6_000 }),
  });
  const network = gateway.getNetwork(CHANNEL);
  const contract = network.getContract(CHAINCODE);
  const evaluateJson = async (fn, ...args) =>
    JSON.parse(Buffer.from(await contract.evaluateTransaction(fn, ...args)).toString("utf8"));
  const registry = async () => {
    const info = await evaluateJson("GetRegistryInfo");
    if (info.networkId !== NETWORK_ID || info.channel !== CHANNEL || info.schemaVersion !== 3) {
      throw new Error("Fabric 登记配置与账本不一致");
    }
    return { ...info, chaincode: CHAINCODE };
  };

  if (initialize) {
    try {
      await contract.submitTransaction("ConfigureRegistry", NETWORK_ID);
      console.log(await registry());
    } finally {
      gateway.close();
      client.close();
    }
    return;
  }

  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url === "/health") {
        return send(res, 200, { ok: true });
      }
      if (!isAuthorized(req)) return send(res, 401, { error: "unauthorized" });
      if (req.method === "GET" && req.url === "/v1/registry") {
        return send(res, 200, await registry());
      }
      if (req.method === "GET" && req.url.startsWith("/v1/records/")) {
        const id = req.url.slice("/v1/records/".length);
        if (!VIDEO_ID.test(id)) throw new RequestError("invalid_video_id");
        return send(res, 200, { record: await evaluateJson("GetVideoRecord", id) });
      }
      if (req.method === "POST" && req.url === "/v1/records") {
        const body = await readJson(req);
        validateEvidence(body);
        await registry();
        const submitted = await contract.submitAsync("CreateVideoRecord", { arguments: [JSON.stringify(body)] });
        return send(res, 202, { txId: submitted.getTransactionId() });
      }
      if (req.method === "GET" && req.url.startsWith("/v1/trades/")) {
        const id = req.url.slice("/v1/trades/".length);
        if (!VIDEO_ID.test(id)) throw new RequestError("invalid_trade_id");
        return send(res, 200, { record: await evaluateJson("GetWorkTransfer", id) });
      }
      if (req.method === "POST" && req.url === "/v1/trades") {
        const body = await readJson(req);
        validateTrade(body);
        await registry();
        const submitted = await contract.submitAsync("RecordWorkTransfer", {
          arguments: [JSON.stringify(body)],
        });
        return send(res, 202, { txId: submitted.getTransactionId() });
      }
      // The standalone sample scripts use these two authenticated compatibility routes.
      if (req.method === "POST" && ["/invoke", "/evaluate"].includes(req.url)) {
        const { fn, args } = await readJson(req);
        if (!Array.isArray(args) || args.length > 2 || !args.every((arg) => typeof arg === "string")) {
          throw new RequestError("invalid_arguments");
        }
        if (req.url === "/invoke" && fn === "CreateVideoRecord") {
          await registry();
          const result = await contract.submitTransaction(fn, ...args);
          return send(res, 200, { ok: true, fn, result: Buffer.from(result).toString("utf8") });
        }
        if (req.url === "/evaluate" && READ_METHODS.has(fn)) {
          const result = await contract.evaluateTransaction(fn, ...args);
          return send(res, 200, { ok: true, fn, result: Buffer.from(result).toString("utf8") });
        }
      }
      return send(res, 404, { error: "not_found" });
    } catch (e) {
      if (e instanceof RequestError) return send(res, 400, { error: e.message });
      const messages = Array.isArray(e.details) ? [e.message, ...e.details.map((detail) => detail.message)] : [e.message];
      if (messages.some((message) => /WORK_TRANSFER_CONFLICT/.test(message))) {
        return send(res, 409, { error: "work_transfer_conflict" });
      }
      console.warn("Fabric request failed", e.name, e.code ?? "");
      return send(res, 503, { error: "fabric_unavailable" });
    }
  });

  server.listen(PORT, "127.0.0.1", () => {
    console.log(`Fabric Gateway bridge 监听 http://127.0.0.1:${PORT}`);
    console.log(`  channel=${CHANNEL} chaincode=${CHAINCODE} msp=${MSP_ID}`);
  });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, () => {
      server.close();
      gateway.close();
      client.close();
    });
  }
}

main().catch((e) => {
  console.error("启动失败：", e);
  process.exit(1);
});
