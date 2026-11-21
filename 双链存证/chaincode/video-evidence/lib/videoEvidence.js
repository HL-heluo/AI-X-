"use strict";

const { Contract } = require("fabric-contract-api");

// ─────────────────────────────────────────────────────────────
// 视频创作信息存证链码（MVP 版）
//
// 改动原因：需求收敛为「用户在本平台生成视频后，把创作信息写进 Fabric，
// 之后作者和平台都能查到」。因此删掉了「转码副本检测」相关的全部能力：
//   · 不再校验感知哈希（perceptualHash 变成可选字段，可留空）；
//   · 删除 VerifyPerceptualHash / 汉明距离计算；
//   · 创作者标识改为业务系统的 ownerId（用户 ID），不再用钱包地址。
//
// 仍然保留的工程纪律（都是踩过坑之后的选择）：
//   1. 返回值只能是 string 或 Uint8Array（fabric-shim 限制），布尔值要包成 JSON；
//   2. 时间戳取 ctx.stub.getTxTimestamp()，不取客户端传参；
//   3. leveldb 不能按字段查询，所以写入时自己建复合键索引；
//   4. 写操作幂等失败（videoId 已存在就报错，不覆盖）；
//   5. videoId 限制为 ASCII 安全字符集，这样 QueryAllRecords 的
//      范围查询边界（`VIDEO_` 到 `VIDEO_~`）才可靠。
// ─────────────────────────────────────────────────────────────

const RECORD_PREFIX = "VIDEO_";
const OWNER_INDEX = "owner~videoId";
const SHA256_INDEX = "sha256~videoId";
const REGISTRY_KEY = "AIVIDEO_REGISTRY";
const TRADE_PREFIX = "TRADE_";
const HOLDING_PREFIX = "HOLDING_";
const SCHEMA_VERSION = 3;

const HEX64 = /^[0-9a-f]{64}$/;
const HEX16 = /^[0-9a-f]{16}$/;
const VIDEO_ID = /^[A-Za-z0-9._-]{1,128}$/;

const MAX_ALL_RECORDS = 500;

class VideoEvidenceContract extends Contract {
  constructor() {
    super("VideoEvidenceContract");
  }

  /** 初始化（可选）：写一个 schema 版本标记，方便运维确认链码已部署 */
  async InitLedger(ctx) {
    this._requireRole(ctx, "recorder");
    await ctx.stub.putState(
      "SCHEMA_VERSION",
      Buffer.from(JSON.stringify({ version: SCHEMA_VERSION, updatedAt: this._now(ctx).iso }))
    );
    return JSON.stringify({ ok: true, version: SCHEMA_VERSION });
  }

  async ConfigureRegistry(ctx, networkId) {
    this._requireRole(ctx, "recorder");
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(networkId)) {
      throw new Error("INVALID_ARGUMENT: networkId");
    }
    const existing = await ctx.stub.getState(REGISTRY_KEY);
    if (existing.length && existing.toString("utf8") !== networkId) {
      throw new Error("REGISTRY_NETWORK_MISMATCH");
    }
    if (!existing.length) await ctx.stub.putState(REGISTRY_KEY, Buffer.from(networkId));
    return JSON.stringify({ schemaVersion: SCHEMA_VERSION, networkId, channel: ctx.stub.getChannelID() });
  }

  async GetRegistryInfo(ctx) {
    this._requireRole(ctx, "recorder", "audit");
    const value = await ctx.stub.getState(REGISTRY_KEY);
    return JSON.stringify({
      schemaVersion: SCHEMA_VERSION,
      networkId: value.length ? value.toString("utf8") : null,
      channel: ctx.stub.getChannelID(),
    });
  }

  /**
   * 写入一条创作信息存证。
   *
   * @param {string} recordJson 形如：
   *   {
   *     "videoId": "vid_20261108_001",
   *     "sha256": "64 个小写十六进制",
   *     "ipfsCid": "bafy...（可选）",
   *     "ownerId": "user_1001",            // 作者（业务系统用户 ID）
   *     "perceptualHash": "（可选，16 位十六进制；MVP 不再使用，留空即可）",
   *     "generationParams": "{\"model\":\"jimeng\",\"seed\":42,\"promptSha256\":\"...\"}",
   *     "providerTaskId": "即梦任务ID（可选，用于和 provider 账单对账）",
   *     "mediaMeta": "{\"sizeBytes\":123,\"durationMs\":5000}（可选）",
   *     "width": 1280, "height": 720, "durationMs": 5000
   *   }
   */
  async CreateVideoRecord(ctx, recordJson) {
    this._requireRole(ctx, "recorder");
    const input = this._parse(recordJson);
    const videoId = this._requireVideoId(input.videoId);
    const sha256 = this._requireHex(input.sha256, "sha256", HEX64);
    const ownerId = this._requireStr(
      input.ownerId !== undefined ? input.ownerId : input.creator,
      "ownerId",
      128
    );

    const key = RECORD_PREFIX + videoId;
    const existing = await ctx.stub.getState(key);
    if (existing && existing.length > 0) {
      throw new Error(`VIDEO_RECORD_EXISTS: videoId=${videoId}`);
    }

    const { iso, epochMs } = this._now(ctx);
    const record = {
      videoId,
      sha256,
      ownerId,
      schemaVersion: input.schemaVersion === SCHEMA_VERSION ? SCHEMA_VERSION : 2,
      ipfsCid: this._optionalStr(input.ipfsCid, 128),
      // MVP 不再需要感知哈希；留字段是为了兼容旧记录与未来扩展
      perceptualHash: this._optionalHex(input.perceptualHash, "perceptualHash", HEX16),
      generationParams: this._optionalStr(input.generationParams, 2048) || "",
      providerTaskId: this._optionalStr(input.providerTaskId, 128),
      mediaMeta: this._optionalStr(input.mediaMeta, 512),
      width: Number.isFinite(input.width) ? input.width : null,
      height: Number.isFinite(input.height) ? input.height : null,
      durationMs: Number.isFinite(input.durationMs) ? input.durationMs : null,
      // 以下字段由链码填，客户端传了也会被覆盖
      createdAtTx: iso,
      createdAtEpochMs: epochMs,
      ledgerTxId: ctx.stub.getTxID(),
      recorderOrg: ctx.clientIdentity.getMSPID(),
    };

    await ctx.stub.putState(key, Buffer.from(JSON.stringify(record)));

    // 索引 1：作者 → 作品（作者查自己的全部存证）
    const ownerKey = await ctx.stub.createCompositeKey(OWNER_INDEX, [ownerId, videoId]);
    await ctx.stub.putState(ownerKey, Buffer.from([0x00]));

    // 索引 2：文件哈希 → videoId（拿到文件反查是哪一条记录）
    const shaKey = await ctx.stub.createCompositeKey(SHA256_INDEX, [sha256, videoId]);
    await ctx.stub.putState(shaKey, Buffer.from([0x00]));

    ctx.stub.setEvent(
      "VideoRecordCreated",
      Buffer.from(JSON.stringify({ videoId, sha256, ownerId }))
    );

    return JSON.stringify(record);
  }

  /** 按 videoId 读完整记录 */
  async ReadVideoRecord(ctx, videoId) {
    this._requireRole(ctx, "recorder", "audit");
    return JSON.stringify(await this._readRecord(ctx, videoId));
  }

  async GetVideoRecord(ctx, videoId) {
    this._requireRole(ctx, "recorder", "audit");
    const raw = await ctx.stub.getState(RECORD_PREFIX + this._requireVideoId(videoId));
    return raw.length ? raw.toString("utf8") : "null";
  }

  async VideoRecordExists(ctx, videoId) {
    this._requireRole(ctx, "recorder", "audit");
    const raw = await ctx.stub.getState(RECORD_PREFIX + this._requireVideoId(videoId));
    return raw && raw.length > 0 ? "true" : "false";
  }

  async GetWorkTransfer(ctx, tradeId) {
    this._requireRole(ctx, "recorder", "audit");
    const raw = await ctx.stub.getState(TRADE_PREFIX + this._requireVideoId(tradeId));
    return raw.length ? raw.toString("utf8") : "null";
  }

  async RecordWorkTransfer(ctx, transferJson) {
    this._requireRole(ctx, "recorder");
    const input = this._parse(transferJson);
    const fields = {
      tradeId: this._requireVideoId(input.tradeId),
      videoId: this._requireVideoId(input.videoId),
      sequence: input.sequence,
      fromHolder: this._requireStr(input.fromHolder, "fromHolder", 128),
      toHolder: this._requireStr(input.toHolder, "toHolder", 128),
      price: input.price,
    };
    if (
      !Number.isSafeInteger(fields.sequence) || fields.sequence < 1 ||
      !Number.isSafeInteger(fields.price) || fields.price < 1 || fields.price > 1000000000 ||
      fields.fromHolder === fields.toHolder
    ) {
      throw new Error("INVALID_ARGUMENT: work transfer");
    }

    const key = TRADE_PREFIX + fields.tradeId;
    const existing = await ctx.stub.getState(key);
    if (existing.length) {
      const record = JSON.parse(existing.toString("utf8"));
      if (Object.keys(fields).some((field) => fields[field] !== record[field])) {
        throw new Error("WORK_TRANSFER_CONFLICT");
      }
      return JSON.stringify(record);
    }

    const work = await this._readRecord(ctx, fields.videoId);
    const holdingKey = HOLDING_PREFIX + fields.videoId;
    const raw = await ctx.stub.getState(holdingKey);
    const holding = raw.length
      ? JSON.parse(raw.toString("utf8"))
      : { holder: work.ownerId, sequence: 0 };
    if (fields.fromHolder !== holding.holder || fields.sequence !== holding.sequence + 1) {
      throw new Error("WORK_TRANSFER_OUT_OF_ORDER");
    }

    const record = { ...fields, ledgerTxId: ctx.stub.getTxID(), createdAtTx: this._now(ctx).iso };
    await ctx.stub.putState(key, Buffer.from(JSON.stringify(record)));
    await ctx.stub.putState(holdingKey, Buffer.from(JSON.stringify({
      holder: fields.toHolder, sequence: fields.sequence,
    })));
    return JSON.stringify(record);
  }

  /** 精确完整性校验：文件字节是否与登记的一致 */
  async VerifyExactHash(ctx, videoId, sha256) {
    this._requireRole(ctx, "recorder", "audit");
    const record = await this._readRecord(ctx, videoId);
    const expected = this._requireHex(sha256, "sha256", HEX64);
    return JSON.stringify({
      videoId: record.videoId,
      matched: record.sha256 === expected,
      ledgerTxId: record.ledgerTxId,
      createdAtTx: record.createdAtTx,
    });
  }

  /** 按作者查全部作品（作者视角） */
  async QueryRecordsByOwner(ctx, ownerId) {
    this._requireRole(ctx, "audit");
    const owner = this._requireStr(ownerId, "ownerId", 128);
    const records = await this._queryByIndex(ctx, OWNER_INDEX, owner);
    return JSON.stringify({ ownerId: owner, count: records.length, records });
  }

  /** 兼容旧名字（之前的文档/脚本用的是 ByCreator） */
  async QueryRecordsByCreator(ctx, creator) {
    return this.QueryRecordsByOwner(ctx, creator);
  }

  /**
   * 平台视角：列出全部存证记录。
   * 用 getStateByRange 扫 `VIDEO_` 前缀；因为 videoId 被限定为 ASCII 安全字符，
   * 所以上界用 `VIDEO_~` 不会漏（`~` 是 0x7E，大于所有允许字符）。
   */
  async QueryAllRecords(ctx, limit) {
    this._requireRole(ctx, "audit");
    const max = this._clampLimit(limit);
    const iterator = await ctx.stub.getStateByRange(RECORD_PREFIX, RECORD_PREFIX + "~");
    const records = [];
    try {
      let res = await iterator.next();
      while (!res.done) {
        if (records.length >= max) break;
        const raw = res.value.value;
        if (raw && raw.length > 0) {
          try {
            records.push(JSON.parse(raw.toString("utf8")));
          } catch (e) {
            // 跳过非本链码写入的同前缀脏数据
          }
        }
        res = await iterator.next();
      }
    } finally {
      await iterator.close();
    }
    return JSON.stringify({ count: records.length, limit: max, records });
  }

  /** 凭文件 SHA-256 反查 videoId（可能多条，见注释） */
  async FindVideoIdsBySha256(ctx, sha256) {
    this._requireRole(ctx, "audit");
    const digest = this._requireHex(sha256, "sha256", HEX64);
    const videoIds = await this._queryIndexKeys(ctx, SHA256_INDEX, digest);
    return JSON.stringify({ sha256: digest, count: videoIds.length, videoIds });
  }

  /** 某条记录的全部历史版本（审计用） */
  async GetRecordHistory(ctx, videoId) {
    this._requireRole(ctx, "audit");
    const key = RECORD_PREFIX + this._requireVideoId(videoId);
    const iterator = await ctx.stub.getHistoryForKey(key);
    const out = [];
    try {
      let res = await iterator.next();
      while (!res.done) {
        const h = res.value;
        out.push({
          txId: h.txId,
          isDelete: h.isDelete,
          timestampIso: new Date(Number(h.timestamp.seconds.toString()) * 1000).toISOString(),
          record: h.isDelete ? null : JSON.parse(h.value.toString("utf8")),
        });
        res = await iterator.next();
      }
    } finally {
      await iterator.close();
    }
    return JSON.stringify({ videoId, count: out.length, history: out });
  }

  // ── 内部工具 ────────────────────────────────────────────────

  _requireRole(ctx, ...roles) {
    const org = ctx.clientIdentity.getMSPID();
    const role = ctx.clientIdentity.getAttributeValue("evidence.role");
    if (org === "Org1MSP" && role === "operator") return;
    if (org === "Org1MSP" && roles.includes("recorder") && role === "recorder") return;
    if (["Org1MSP", "Org2MSP"].includes(org) && roles.includes("audit") && role === "audit") return;
    throw new Error("EVIDENCE_ACCESS_DENIED");
  }

  async _readRecord(ctx, videoId) {
    const vid = this._requireVideoId(videoId);
    const raw = await ctx.stub.getState(RECORD_PREFIX + vid);
    if (!raw || raw.length === 0) {
      throw new Error(`VIDEO_RECORD_NOT_FOUND: videoId=${vid}`);
    }
    return JSON.parse(raw.toString("utf8"));
  }

  /** 按复合键索引查记录（用于 QueryRecordsByOwner） */
  async _queryByIndex(ctx, indexName, value) {
    const records = [];
    const iterator = await ctx.stub.getStateByPartialCompositeKey(indexName, [value]);
    try {
      let res = await iterator.next();
      while (!res.done) {
        const { attributes } = await ctx.stub.splitCompositeKey(res.value.key);
        const videoId = attributes[1];
        if (videoId) {
          const raw = await ctx.stub.getState(RECORD_PREFIX + videoId);
          if (raw && raw.length > 0) {
            try {
              records.push(JSON.parse(raw.toString("utf8")));
            } catch (e) {
              // 忽略脏数据
            }
          }
        }
        res = await iterator.next();
      }
    } finally {
      await iterator.close();
    }
    return records;
  }

  /** 只取索引里的第二段（videoId），用于 sha256 反查 */
  async _queryIndexKeys(ctx, indexName, value) {
    const out = [];
    const iterator = await ctx.stub.getStateByPartialCompositeKey(indexName, [value]);
    try {
      let res = await iterator.next();
      while (!res.done) {
        const { attributes } = await ctx.stub.splitCompositeKey(res.value.key);
        if (attributes[1]) out.push(attributes[1]);
        res = await iterator.next();
      }
    } finally {
      await iterator.close();
    }
    return out;
  }

  _parse(recordJson) {
    if (typeof recordJson !== "string" || recordJson.trim() === "") {
      throw new Error("INVALID_ARGUMENT: recordJson 不能为空");
    }
    let input;
    try {
      input = JSON.parse(recordJson);
    } catch (e) {
      throw new Error(`INVALID_JSON: ${e.message}`);
    }
    if (!input || typeof input !== "object" || Array.isArray(input)) {
      throw new Error("INVALID_ARGUMENT: recordJson 必须是对象");
    }
    return input;
  }

  _requireVideoId(v) {
    if (typeof v !== "string" || !VIDEO_ID.test(v)) {
      throw new Error("INVALID_ARGUMENT: videoId 必须是 1~128 位 [A-Za-z0-9._-]");
    }
    return v;
  }

  _requireStr(v, name, maxLen) {
    if (typeof v !== "string" || v.trim() === "") {
      throw new Error(`INVALID_ARGUMENT: ${name} 必须是非空字符串`);
    }
    if (v.length > maxLen) {
      throw new Error(`INVALID_ARGUMENT: ${name} 超过 ${maxLen} 字符`);
    }
    return v;
  }

  _optionalStr(v, maxLen) {
    if (v === undefined || v === null || v === "") return null;
    if (typeof v !== "string") throw new Error("INVALID_ARGUMENT: 需要字符串");
    if (v.length > maxLen) throw new Error(`INVALID_ARGUMENT: 超过 ${maxLen} 字符`);
    return v;
  }

  _requireHex(v, name, re) {
    if (typeof v !== "string") {
      throw new Error(`INVALID_ARGUMENT: ${name} 必须是字符串`);
    }
    const normalized = v.toLowerCase().replace(/^0x/, "");
    if (!re.test(normalized)) {
      throw new Error(`INVALID_ARGUMENT: ${name} 格式不对（应为 ${re.source}）`);
    }
    return normalized;
  }

  _optionalHex(v, name, re) {
    if (v === undefined || v === null || v === "") return null;
    return this._requireHex(v, name, re);
  }

  _clampLimit(limit) {
    const n = Number(limit);
    if (!Number.isFinite(n) || n <= 0) return 100;
    return Math.min(Math.floor(n), MAX_ALL_RECORDS);
  }

  _now(ctx) {
    const ts = ctx.stub.getTxTimestamp();
    const seconds = Number(ts.seconds.toString());
    const nanos = Number(ts.nanos || 0);
    const epochMs = seconds * 1000 + Math.floor(nanos / 1e6);
    return { epochMs, iso: new Date(epochMs).toISOString() };
  }
}

module.exports = VideoEvidenceContract;
