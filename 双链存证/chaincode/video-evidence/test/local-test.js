"use strict";

// 不需要 Docker / Fabric 的本地链码测试：用内存假 stub 模拟 ctx。
//
// 运行：node test/local-test.js（或 npm test）
// 验证：写入、读回、按作者查、全量查、按哈希反查、精确校验、幂等、参数校验、历史。
//
// 注意：这不能替代真实 Fabric 的背书/共识验证，只验证链码的**业务逻辑**。

const assert = require("node:assert/strict");
const Contract = require("../lib/videoEvidence");
const { makeCtx } = require("./fake-stub");

function recordJson(overrides = {}) {
  return JSON.stringify({
    videoId: "vid_20261108_001",
    sha256: "e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297",
    ipfsCid: "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    ownerId: "user_1001",
    generationParams: '{"model":"jimeng","seed":42,"promptSha256":"abc"}',
    providerTaskId: "jimeng_task_123",
    mediaMeta: '{"sizeBytes":300335,"durationMs":3000}',
    width: 640,
    height: 360,
    durationMs: 3000,
    ...overrides,
  });
}

async function main() {
  const contract = new Contract();
  const ctx = makeCtx();

  // 1. 写入 + 字段完整性
  const created = JSON.parse(await contract.CreateVideoRecord(ctx, recordJson()));
  assert.equal(created.videoId, "vid_20261108_001");
  assert.equal(created.ownerId, "user_1001");
  assert.equal(created.perceptualHash, null); // MVP 不再需要感知哈希
  assert.equal(created.recorderOrg, "Org1MSP"); // 由链码填，不信客户端
  assert.equal(created.ledgerTxId, "tx_0001");
  assert.equal(created.createdAtTx, "2026-11-08T10:00:00.000Z"); // 取交易时间
  assert.equal(ctx.events.length, 1);
  assert.equal(ctx.events[0].name, "VideoRecordCreated");
  assert.ok(ctx.store.has("VIDEO_vid_20261108_001"));
  assert.equal([...ctx.store.keys()].filter((k) => k.startsWith("owner~videoId")).length, 1);
  assert.equal([...ctx.store.keys()].filter((k) => k.startsWith("sha256~videoId")).length, 1);
  console.log("✓ 1. 写入成功：记录/两个索引/事件齐全，时间与组织由链码填");

  // 2. 读回
  const read = JSON.parse(await contract.ReadVideoRecord(ctx, "vid_20261108_001"));
  assert.deepEqual(read, created);
  assert.equal(await contract.VideoRecordExists(ctx, "vid_20261108_001"), "true");
  console.log("✓ 2. ReadVideoRecord / VideoRecordExists 正常");

  // 3. 作者查询（含旧函数名别名）
  const byOwner = JSON.parse(await contract.QueryRecordsByOwner(ctx, "user_1001"));
  assert.equal(byOwner.count, 1);
  const byCreatorAlias = JSON.parse(await contract.QueryRecordsByCreator(ctx, "user_1001"));
  assert.equal(byCreatorAlias.count, 1);
  console.log("✓ 3. 按作者查：QueryRecordsByOwner（及旧名 QueryRecordsByCreator）命中 1 条");

  // 4. 平台查询全量（含 limit）
  await contract.CreateVideoRecord(
    ctx,
    recordJson({
      videoId: "vid_20261108_002",
      sha256: "11".repeat(32),
      ownerId: "user_2002",
      ipfsCid: undefined,
    })
  );
  const all = JSON.parse(await contract.QueryAllRecords(ctx, "100"));
  assert.equal(all.count, 2);
  const limited = JSON.parse(await contract.QueryAllRecords(ctx, "1"));
  assert.equal(limited.count, 1);
  console.log("✓ 4. 平台全量查询：2 条；limit=1 时返回 1 条");

  // 5. 凭文件哈希反查
  const bySha = JSON.parse(
    await contract.FindVideoIdsBySha256(
      ctx,
      "e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297"
    )
  );
  assert.deepEqual(bySha.videoIds, ["vid_20261108_001"]);
  const unknown = JSON.parse(await contract.FindVideoIdsBySha256(ctx, "22".repeat(32)));
  assert.equal(unknown.count, 0);
  console.log("✓ 5. FindVideoIdsBySha256：命中 1 条；未知哈希返回 0 条");

  // 6. 精确校验
  const ok = JSON.parse(
    await contract.VerifyExactHash(
      ctx,
      "vid_20261108_001",
      "e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297"
    )
  );
  assert.equal(ok.matched, true);
  const tampered = JSON.parse(
    await contract.VerifyExactHash(
      ctx,
      "vid_20261108_001",
      "f7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297"
    )
  );
  assert.equal(tampered.matched, false);
  console.log("✓ 6. VerifyExactHash：原哈希 true，改一个字符 false");

  // 7. 历史版本
  const history = JSON.parse(await contract.GetRecordHistory(ctx, "vid_20261108_001"));
  assert.equal(history.count, 1);
  assert.equal(history.history[0].txId, "tx_first");
  console.log("✓ 7. GetRecordHistory 返回版本历史");

  // 8. 负向：同一 videoId 重复写入
  await assert.rejects(() => contract.CreateVideoRecord(ctx, recordJson()), /VIDEO_RECORD_EXISTS/);
  console.log("✓ 8. 重复 videoId 被拒（幂等失败，不覆盖）");

  // 9. 负向：缺 sha256 / videoId 非法 / ownerId 为空
  await assert.rejects(() => contract.CreateVideoRecord(ctx, recordJson({ sha256: undefined })), /sha256/);
  await assert.rejects(() => contract.CreateVideoRecord(ctx, recordJson({ videoId: "含 空格" })), /videoId/);
  await assert.rejects(() => contract.CreateVideoRecord(ctx, recordJson({ ownerId: "" })), /ownerId/);
  console.log("✓ 9. 参数校验：缺 sha256 / videoId 非法 / owner 为空 全部拒绝");

  // 10. 旧字段兼容：传 creator 也能写入
  const legacy = JSON.parse(
    await contract.CreateVideoRecord(
      ctx,
      recordJson({ videoId: "vid_legacy_001", ownerId: undefined, creator: "user_legacy" })
    )
  );
  assert.equal(legacy.ownerId, "user_legacy");
  console.log("✓ 10. 旧字段 creator 兼容映射为 ownerId");

  const registry = JSON.parse(await contract.ConfigureRegistry(ctx, "demo-chain"));
  assert.equal(registry.networkId, "demo-chain");
  assert.equal(JSON.parse(await contract.GetRegistryInfo(ctx)).schemaVersion, 3);
  assert.equal(JSON.parse(await contract.GetVideoRecord(ctx, "missing")), null);
  await assert.rejects(contract.ConfigureRegistry(ctx, "different-chain"), /REGISTRY_NETWORK_MISMATCH/);
  await assert.rejects(contract.CreateVideoRecord(makeCtx({ role: "audit" }), recordJson()), /EVIDENCE_ACCESS_DENIED/);
  await assert.rejects(contract.QueryAllRecords(makeCtx({ role: "recorder" }), "10"), /EVIDENCE_ACCESS_DENIED/);
  await assert.rejects(contract.GetRegistryInfo(makeCtx({ mspId: "UnknownMSP" })), /EVIDENCE_ACCESS_DENIED/);
  console.log("✓ 11. 测试链标识与登记/审计权限");

  const firstTrade = {
    tradeId: "trade_1", videoId: created.videoId, sequence: 1,
    fromHolder: created.ownerId, toHolder: "user_1002", price: 50,
  };
  const secondTrade = {
    ...firstTrade, tradeId: "trade_2", sequence: 2, fromHolder: "user_1002", toHolder: "user_1003",
  };
  const submit = (trade) => contract.RecordWorkTransfer(ctx, JSON.stringify(trade));
  await assert.rejects(submit(secondTrade), /WORK_TRANSFER_OUT_OF_ORDER/);
  const first = await submit(firstTrade);
  assert.equal(await submit(firstTrade), first);
  assert.equal(await contract.GetWorkTransfer(ctx, firstTrade.tradeId), first);
  await assert.rejects(submit({ ...firstTrade, price: 51 }), /WORK_TRANSFER_CONFLICT/);
  await submit(secondTrade);
  assert.equal(await submit(firstTrade), first);
  assert.equal(JSON.parse(await contract.ReadVideoRecord(ctx, created.videoId)).ownerId, created.ownerId);
  assert.equal(ctx.store.get("HOLDING_" + created.videoId), JSON.stringify({ holder: "user_1003", sequence: 2 }));
  await assert.rejects(
    contract.RecordWorkTransfer(makeCtx({ role: "audit" }), JSON.stringify(firstTrade)),
    /EVIDENCE_ACCESS_DENIED/,
  );
  console.log("✓ 12. 转让按顺序记录、幂等重试并保留原作者");

  console.log("\n全部通过（本地假 stub，不涉及 Docker/Fabric）。");
}

main().catch((e) => {
  console.error("失败：", e);
  process.exit(1);
});
