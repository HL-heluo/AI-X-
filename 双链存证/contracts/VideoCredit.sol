// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

// 视频生成平台积分代币（VCR）—— 推荐版：托管 → 结算 → 退款三段式
//
// 这是对课程报告里 `consume(user, amount)` 直接 `_burn` 的修正：
//
//   报告版：平台凭 CONSUMER_ROLE 直接烧用户余额。
//           → 平台私钥可以在一瞬间清空任何用户的积分，链上只留下
//             “平台确实烧了”的证据，用户没有任何反制手段。
//           → 报告里“用户调用 consume”的测试流程在角色模型下也不成立
//             （用户没有 CONSUMER_ROLE）。
//
//   本版：用户先用 approve 授权，平台 reserve 把币**托管**进合约；
//         视频交付成功 → settle 销毁；生成失败 → refund 退回。
//         用户始终保留“授权额度”这一个否决权，而且托管额在任何时候
//         都能用 escrowOf 查出来，天然对应后端积分账本的
//         freeze / settle / refund 三段式（见 AIVideo 工程文档 §7.2）。
//
// 另外：`transferable=false` 时，本代币只能在用户↔平台之间流转
// （铸造、托管、结算、退款），不允许用户之间互转。这是把「积分」
// 和「可交易的加密资产」在合约层面切开，避免课程作业踩到
// 「代币发行 / 二级市场」的合规红线。
contract VideoCredit is ERC20, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    bytes32 public constant SETTLER_ROLE = keccak256("SETTLER_ROLE");

    /// @dev 是否允许用户之间自由转账。构造时固定，不可更改。
    bool public immutable transferable;

    struct Escrow {
        address user; // 谁的钱
        uint96 amount; // 冻结了多少（uint96 够大到不需要）
        uint64 createdAt; // 冻结时间（秒）
        bool closed; // 已结算或已退款
    }

    /// videoId 的 keccak256 → 托管记录
    mapping(bytes32 => Escrow) private _escrows;
    /// videoId 是否已经被用过（防止同一 videoId 重复冻结/刷单）
    mapping(bytes32 => bool) private _usedVideoId;
    mapping(bytes32 => bool) public shadowApplied;
    bytes32 public shadowDeployment;

    event Reserved(bytes32 indexed videoIdHash, address indexed user, uint256 amount);
    event Settled(bytes32 indexed videoIdHash, address indexed user, uint256 amount);
    event Refunded(bytes32 indexed videoIdHash, address indexed user, uint256 amount);
    /// 影子链模式：直接销毁用户已授权额度的积分（每笔消耗一条链上记录）
    event Consumed(address indexed user, uint256 amount, bytes32 indexed videoIdHash);
    event ShadowOperation(bytes32 indexed operationId, address indexed user, uint256 amount, bool credited);

    error VideoIdAlreadyUsed(bytes32 videoIdHash);
    error EscrowNotFound(bytes32 videoIdHash);
    error EscrowAlreadyClosed(bytes32 videoIdHash);
    error ZeroAmount();
    error TransfersDisabled();
    error InvalidShadowDeployment();
    error ShadowOperationAlreadyApplied(bytes32 operationId);

    constructor(bool transferable_) ERC20("VideoCredit", "VCR") {
        transferable = transferable_;
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(MINTER_ROLE, msg.sender);
        _grantRole(SETTLER_ROLE, msg.sender);
    }

    /// @dev 积分是整数，不要 18 位小数 —— 否则钱包/区块浏览器里会显示成 0.0000…1
    function decimals() public pure override returns (uint8) {
        return 0;
    }

    // ── 平台方：充值（法币兑换在链下完成，这里只演示铸造）──────────
    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        _mint(to, amount);
    }

    function configureShadow(bytes32 deployment) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (shadowDeployment != bytes32(0) || deployment == bytes32(0)) revert InvalidShadowDeployment();
        shadowDeployment = deployment;
    }

    function mintWithRef(address user, uint256 amount, bytes32 operationId) external onlyRole(MINTER_ROLE) {
        if (amount == 0) revert ZeroAmount();
        _recordShadowOperation(operationId);
        _mint(user, amount);
        emit ShadowOperation(operationId, user, amount, true);
    }

    // ── 影子链模式：按任务消耗（用户先 approve 一次「长期额度」）────
    // 与 reserve/settle 的区别：不托管、一步销毁。
    // 适合「链下积分即刻结算、链上留一条消耗凭证」的影子链演示。
    // 仍然强制 _spendAllowance —— 平台最多只能花用户授权过的额度。
    function consume(address user, uint256 amount, bytes32 videoIdHash)
        external
        onlyRole(SETTLER_ROLE)
        returns (bool)
    {
        if (amount == 0) revert ZeroAmount();
        _recordShadowOperation(videoIdHash);
        _spendAllowance(user, msg.sender, amount);
        _burn(user, amount);
        emit Consumed(user, amount, videoIdHash);
        emit ShadowOperation(videoIdHash, user, amount, false);
        return true;
    }

    function _recordShadowOperation(bytes32 operationId) private {
        if (shadowApplied[operationId]) revert ShadowOperationAlreadyApplied(operationId);
        shadowApplied[operationId] = true;
    }

    // ── 平台方：冻结（用户必须先 approve）──────────────────────────
    function reserve(address user, uint256 amount, bytes32 videoIdHash)
        external
        onlyRole(SETTLER_ROLE)
        returns (bool)
    {
        if (amount == 0) revert ZeroAmount();
        if (_usedVideoId[videoIdHash]) revert VideoIdAlreadyUsed(videoIdHash);

        // 没有授权额度会在这里 revert（ERC20InsufficientAllowance）
        _spendAllowance(user, msg.sender, amount);
        _usedVideoId[videoIdHash] = true;

        _transfer(user, address(this), amount);
        _escrows[videoIdHash] = Escrow({
            user: user,
            amount: uint96(amount),
            createdAt: uint64(block.timestamp),
            closed: false
        });

        emit Reserved(videoIdHash, user, amount);
        return true;
    }

    // ── 平台方：结算（视频已交付，托管额销毁）──────────────────────
    function settle(bytes32 videoIdHash) external onlyRole(SETTLER_ROLE) returns (bool) {
        Escrow storage e = _escrows[videoIdHash];
        if (e.user == address(0)) revert EscrowNotFound(videoIdHash);
        if (e.closed) revert EscrowAlreadyClosed(videoIdHash);

        e.closed = true;
        _burn(address(this), e.amount);
        emit Settled(videoIdHash, e.user, e.amount);
        return true;
    }

    // ── 平台方：退款（生成失败 / 超时 / 用户取消）──────────────────
    function refund(bytes32 videoIdHash) external onlyRole(SETTLER_ROLE) returns (bool) {
        Escrow storage e = _escrows[videoIdHash];
        if (e.user == address(0)) revert EscrowNotFound(videoIdHash);
        if (e.closed) revert EscrowAlreadyClosed(videoIdHash);

        e.closed = true;
        _transfer(address(this), e.user, e.amount);
        emit Refunded(videoIdHash, e.user, e.amount);
        return true;
    }

    // ── 只读：任何验证方都能查某个 videoId 的托管状态 ──────────────
    function escrowOf(bytes32 videoIdHash)
        external
        view
        returns (address user, uint256 amount, uint64 createdAt, bool closed)
    {
        Escrow storage e = _escrows[videoIdHash];
        return (e.user, e.amount, e.createdAt, e.closed);
    }

    // ── 转账限制：非自由转让的积分 ────────────────────────────────
    // OZ v5 用 `_update` 取代了 v4 的 `_beforeTokenTransfer`。
    function _update(address from, address to, uint256 value) internal override {
        if (!transferable) {
            bool allowed = from == address(0) // 铸造
                || to == address(0) // 销毁
                || from == address(this) // 退款
                || to == address(this); // 托管
            if (!allowed) revert TransfersDisabled();
        }
        super._update(from, to, value);
    }
}
