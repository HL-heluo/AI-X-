// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

// ─────────────────────────────────────────────────────────────
// 单链降级版：视频存证登记表（以太坊侧）
//
// 为什么需要它：
//   如果课程截止前 Fabric 环境（WSL2 + Docker + 双组织）搭不起来，
//   你需要一个「真实可运行」的存证层，而不是只在报告里画图。
//   这个合约把 Fabric 链码里的核心字段（sha256 / 感知哈希 / IPFS CID /
//   创作者 / 参数哈希）落到以太坊上，功能等价、成本高、隐私差，
//   但演示完全够用——而且它和 `VideoCredit` 在同一条链上，
//   演示时只需要一条 ganache。
//
// 与 Fabric 版的差别（报告里要如实写）：
//   · 没有多组织背书，写入权限集中在 `RECORDER_ROLE`（平台）；
//   · 记录公开可见，CID 与哈希会暴露给所有人；
//   · 每条记录要付 gas（本地链为 0，测试网按实际价格算）。
//
// 设计上的两个刻意选择：
//   · 记录**不可覆盖**（videoId 已存在就 revert）——存证的价值在“第一次”；
//   · 感知哈希用 `uint64` 存（64 bit 正好一个字），比较时用异或 + popcount。
// ─────────────────────────────────────────────────────────────
contract VideoEvidence is AccessControl {
    bytes32 public constant RECORDER_ROLE = keccak256("RECORDER_ROLE");

    struct Record {
        bytes32 sha256; // 精确指纹（32 字节）
        uint64 perceptualHash; // 感知指纹（64 bit）
        uint64 recordedAt; // 写入时间（区块时间）
        address creator; // 创作者/用户地址
        bytes32 paramsHash; // 生成参数摘要（模型、seed、prompt 的哈希）
        string ipfsCid; // 视频文件在 IPFS 的内容标识
        address recorder; // 实际写入者（平台运营地址）
    }

    mapping(bytes32 => Record) private _records; // keccak256(videoId) => 记录

    // 反向索引：sha256(文件字节) => videoIdHash。
    // 为什么必须有它：用户上传一个文件来「查来源」时，我们手里只有文件哈希，
    // 没有 videoId；没有这张表就只能遍历所有记录（链上做不到）。
    // 同一份内容若被登记多次，保留第一次的映射（first-writer wins）。
    mapping(bytes32 => bytes32) private _videoIdBySha256;

    event EvidenceRecorded(
        bytes32 indexed videoIdHash,
        address indexed creator,
        bytes32 sha256,
        uint64 perceptualHash,
        string ipfsCid
    );

    error AlreadyRecorded(bytes32 videoIdHash);
    error NotFound(bytes32 videoIdHash);
    error InvalidArgument();

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(RECORDER_ROLE, msg.sender);
    }

    /// 平台写入存证。videoIdHash = keccak256(UTF-8 的 videoId 字符串)。
    function recordEvidence(
        bytes32 videoIdHash,
        bytes32 sha256,
        uint64 perceptualHash,
        string calldata ipfsCid,
        address creator,
        bytes32 paramsHash
    ) external onlyRole(RECORDER_ROLE) {
        if (videoIdHash == bytes32(0) || sha256 == bytes32(0) || creator == address(0)) {
            revert InvalidArgument();
        }
        if (bytes(ipfsCid).length > 128) revert InvalidArgument();
        if (_records[videoIdHash].creator != address(0)) {
            revert AlreadyRecorded(videoIdHash);
        }

        _records[videoIdHash] = Record({
            sha256: sha256,
            perceptualHash: perceptualHash,
            recordedAt: uint64(block.timestamp),
            creator: creator,
            paramsHash: paramsHash,
            ipfsCid: ipfsCid,
            recorder: msg.sender
        });

        emit EvidenceRecorded(videoIdHash, creator, sha256, perceptualHash, ipfsCid);

        // 建反向索引：以后只给 sha256 也能找到这份内容的存证记录
        if (_videoIdBySha256[sha256] == bytes32(0)) {
            _videoIdBySha256[sha256] = videoIdHash;
        }
    }

    /// 按文件 SHA-256 反查 videoIdHash（找不到返回 bytes32(0)）。
    /// 这是「用户上传一个副本，问它是不是平台生成的」这条流程的入口。
    function videoIdBySha256(bytes32 sha256Hash) external view returns (bytes32) {
        return _videoIdBySha256[sha256Hash];
    }

    function exists(bytes32 videoIdHash) external view returns (bool) {
        return _records[videoIdHash].creator != address(0);
    }

    function getEvidence(bytes32 videoIdHash)
        external
        view
        returns (
            bytes32 sha256,
            uint64 perceptualHash,
            uint64 recordedAt,
            address creator,
            bytes32 paramsHash,
            string memory ipfsCid,
            address recorder
        )
    {
        Record storage r = _records[videoIdHash];
        if (r.creator == address(0)) revert NotFound(videoIdHash);
        return (
            r.sha256,
            r.perceptualHash,
            r.recordedAt,
            r.creator,
            r.paramsHash,
            r.ipfsCid,
            r.recorder
        );
    }

    /// 精确校验：文件字节是否与登记的一致
    function verifyExact(bytes32 videoIdHash, bytes32 candidateSha256)
        external
        view
        returns (bool matched, uint64 recordedAt)
    {
        Record storage r = _records[videoIdHash];
        if (r.creator == address(0)) revert NotFound(videoIdHash);
        return (r.sha256 == candidateSha256, r.recordedAt);
    }

    /// 感知校验：返回是否在阈值内 + 实际汉明距离
    function verifyPerceptual(bytes32 videoIdHash, uint64 candidateHash, uint8 maxDistance)
        external
        view
        returns (bool matched, uint8 distance)
    {
        Record storage r = _records[videoIdHash];
        if (r.creator == address(0)) revert NotFound(videoIdHash);
        distance = _popcount64(r.perceptualHash ^ candidateHash);
        matched = distance <= maxDistance;
    }

    function _popcount64(uint64 x) internal pure returns (uint8 count) {
        while (x != 0) {
            count += uint8(x & 1);
            x >>= 1;
        }
    }
}
