"use strict";

// 内存假 stub：模拟 fabric-contract-api 的 ctx，用于无 Docker 的本地链码测试。
// 只实现链码用到的子集：getState / putState / 复合键 / 范围查询 / 历史 / 时间戳 / 事件。

const OWNER_INDEX = "owner~videoId";
const SHA256_INDEX = "sha256~videoId";

function makeIterator(items) {
  let i = -1;
  return {
    async next() {
      i += 1;
      return i < items.length ? { done: false, value: items[i] } : { done: true, value: undefined };
    },
    async close() {},
  };
}

function makeCtx(options = {}) {
  const store = new Map();
  const events = [];
  let txCounter = 0;
  const fixedNow = options.now ? new Date(options.now) : new Date("2026-11-08T10:00:00Z");
  const mspId = options.mspId || "Org1MSP";

  const stub = {
    async getState(key) {
      return store.has(key) ? Buffer.from(store.get(key), "utf8") : Buffer.alloc(0);
    },
    async putState(key, value) {
      store.set(key, Buffer.from(value).toString("utf8"));
    },
    async createCompositeKey(type, attrs) {
      return `${type}\x00${attrs.join("\x00")}\x00`;
    },
    async splitCompositeKey(key) {
      const parts = key.split("\x00");
      return { objectType: parts[0], attributes: parts.slice(1).filter(Boolean) };
    },
    async getStateByRange(start, end) {
      const keys = [...store.keys()].filter((k) => k >= start && k < end).sort();
      return makeIterator(keys.map((k) => ({ key: k, value: Buffer.from(store.get(k), "utf8") })));
    },
    async getStateByPartialCompositeKey(type, attrs) {
      const prefix = `${type}\x00${attrs.join("\x00")}\x00`;
      const keys = [...store.keys()].filter((k) => k.startsWith(prefix)).sort();
      return makeIterator(keys.map((k) => ({ key: k, value: Buffer.from([0x00]) })));
    },
    async getHistoryForKey(key) {
      const raw = store.get(key);
      return makeIterator([
        {
          txId: "tx_first",
          isDelete: false,
          timestamp: { seconds: { toString: () => String(Math.floor(fixedNow.getTime() / 1000)) }, nanos: 0 },
          value: raw ? Buffer.from(raw, "utf8") : Buffer.alloc(0),
        },
      ]);
    },
    getTxTimestamp() {
      return {
        seconds: { toString: () => String(Math.floor(fixedNow.getTime() / 1000)) },
        nanos: 0,
      };
    },
    getTxID() {
      txCounter += 1;
      return `tx_${String(txCounter).padStart(4, "0")}`;
    },
    getChannelID() {
      return "videochannel";
    },
    setEvent(name, payload) {
      events.push({ name, payload: Buffer.from(payload).toString("utf8") });
    },
  };

  return {
    stub,
    clientIdentity: {
      getMSPID: () => mspId,
      getAttributeValue: (name) => name === "evidence.role" ? (options.role ?? "operator") : null,
    },
    events,
    store,
    indexes: { OWNER_INDEX, SHA256_INDEX },
  };
}

module.exports = { makeCtx, makeIterator };
