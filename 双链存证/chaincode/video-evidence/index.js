"use strict";

// Fabric 链码入口。fabric-contract-api 会读 `contracts` 数组来注册合约。
// peer 容器内的 Node 运行时（fabric-nodeenv）负责加载这个文件，
// 和你本机装的 Node 版本无关。
const VideoEvidenceContract = require("./lib/videoEvidence");

module.exports.contracts = [VideoEvidenceContract];
