"use strict";

// 跨语言一致性测试：把 Python（python/creation_record.py）产出的记录 JSON
// 直接喂给链码 CreateVideoRecord，验证「Python 生成的字段能被链码接受」。
//
// 运行：
//   python python/creation_record.py sample.mp4 --video-id vid_demo_001 --owner user_1001 \
//       --model jimeng --seed 42 --prompt "..." --out record.json
//   node chaincode/video-evidence/test/from-python-record.js record.json

const fs = require("node:fs");
const assert = require("node:assert/strict");
const Contract = require("../lib/videoEvidence");
const { makeCtx } = require("./fake-stub");

async function main() {
  const recordPath = process.argv[2];
  if (!recordPath) {
    console.log("用法：node test/from-python-record.js <record.json>");
    process.exit(1);
  }
  const recordJson = fs.readFileSync(recordPath, "utf8");
  const expected = JSON.parse(recordJson);

  const contract = new Contract();
  const ctx = makeCtx();
  const created = JSON.parse(await contract.CreateVideoRecord(ctx, recordJson));

  // 字段透传检查
  assert.equal(created.videoId, expected.videoId);
  assert.equal(created.ownerId, expected.ownerId);
  assert.equal(created.sha256, expected.sha256);
  assert.equal(created.mediaMeta, expected.mediaMeta);
  assert.equal(created.generationParams, expected.generationParams);

  // 查询链路检查
  const byOwner = JSON.parse(await contract.QueryRecordsByOwner(ctx, expected.ownerId));
  assert.equal(byOwner.count, 1);
  const bySha = JSON.parse(await contract.FindVideoIdsBySha256(ctx, expected.sha256));
  assert.deepEqual(bySha.videoIds, [expected.videoId]);
  const all = JSON.parse(await contract.QueryAllRecords(ctx, "10"));
  assert.equal(all.count, 1);
  const exact = JSON.parse(await contract.VerifyExactHash(ctx, expected.videoId, expected.sha256));
  assert.equal(exact.matched, true);

  console.log(`✓ Python 记录被链码接受：videoId=${created.videoId} owner=${created.ownerId}`);
  console.log("✓ 按作者/按哈希/全量/精确校验 全部命中");
}

main().catch((e) => {
  console.error("失败：", e);
  process.exit(1);
});
