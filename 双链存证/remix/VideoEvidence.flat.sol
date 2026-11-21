// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// 本文件由 scripts/flatten.js 自动生成，供在线 Remix 使用（把 OpenZeppelin 依赖内联进来）。
// 不要手改；改 contracts/ 下的源文件后重跑 node scripts/flatten.js。

// ─────────────────────────────────────────────────────────────
// 来源：node_modules/@openzeppelin/contracts/access/IAccessControl.sol
// ─────────────────────────────────────────────────────────────
// OpenZeppelin Contracts (last updated v5.4.0) (access/IAccessControl.sol)

/**
 * @dev External interface of AccessControl declared to support ERC-165 detection.
 */
interface IAccessControl {
    /**
     * @dev The `account` is missing a role.
     */
    error AccessControlUnauthorizedAccount(address account, bytes32 neededRole);

    /**
     * @dev The caller of a function is not the expected one.
     *
     * NOTE: Don't confuse with {AccessControlUnauthorizedAccount}.
     */
    error AccessControlBadConfirmation();

    /**
     * @dev Emitted when `newAdminRole` is set as ``role``'s admin role, replacing `previousAdminRole`
     *
     * `DEFAULT_ADMIN_ROLE` is the starting admin for all roles, despite
     * {RoleAdminChanged} not being emitted to signal this.
     */
    event RoleAdminChanged(bytes32 indexed role, bytes32 indexed previousAdminRole, bytes32 indexed newAdminRole);

    /**
     * @dev Emitted when `account` is granted `role`.
     *
     * `sender` is the account that originated the contract call. This account bears the admin role (for the granted role).
     * Expected in cases where the role was granted using the internal {AccessControl-_grantRole}.
     */
    event RoleGranted(bytes32 indexed role, address indexed account, address indexed sender);

    /**
     * @dev Emitted when `account` is revoked `role`.
     *
     * `sender` is the account that originated the contract call:
     *   - if using `revokeRole`, it is the admin role bearer
     *   - if using `renounceRole`, it is the role bearer (i.e. `account`)
     */
    event RoleRevoked(bytes32 indexed role, address indexed account, address indexed sender);

    /**
     * @dev Returns `true` if `account` has been granted `role`.
     */
    function hasRole(bytes32 role, address account) external view returns (bool);

    /**
     * @dev Returns the admin role that controls `role`. See {grantRole} and
     * {revokeRole}.
     *
     * To change a role's admin, use {AccessControl-_setRoleAdmin}.
     */
    function getRoleAdmin(bytes32 role) external view returns (bytes32);

    /**
     * @dev Grants `role` to `account`.
     *
     * If `account` had not been already granted `role`, emits a {RoleGranted}
     * event.
     *
     * Requirements:
     *
     * - the caller must have ``role``'s admin role.
     */
    function grantRole(bytes32 role, address account) external;

    /**
     * @dev Revokes `role` from `account`.
     *
     * If `account` had been granted `role`, emits a {RoleRevoked} event.
     *
     * Requirements:
     *
     * - the caller must have ``role``'s admin role.
     */
    function revokeRole(bytes32 role, address account) external;

    /**
     * @dev Revokes `role` from the calling account.
     *
     * Roles are often managed via {grantRole} and {revokeRole}: this function's
     * purpose is to provide a mechanism for accounts to lose their privileges
     * if they are compromised (such as when a trusted device is misplaced).
     *
     * If the calling account had been granted `role`, emits a {RoleRevoked}
     * event.
     *
     * Requirements:
     *
     * - the caller must be `callerConfirmation`.
     */
    function renounceRole(bytes32 role, address callerConfirmation) external;
}

// ─────────────────────────────────────────────────────────────
// 来源：node_modules/@openzeppelin/contracts/utils/Context.sol
// ─────────────────────────────────────────────────────────────
// OpenZeppelin Contracts (last updated v5.0.1) (utils/Context.sol)

/**
 * @dev Provides information about the current execution context, including the
 * sender of the transaction and its data. While these are generally available
 * via msg.sender and msg.data, they should not be accessed in such a direct
 * manner, since when dealing with meta-transactions the account sending and
 * paying for execution may not be the actual sender (as far as an application
 * is concerned).
 *
 * This contract is only required for intermediate, library-like contracts.
 */
abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }

    function _msgData() internal view virtual returns (bytes calldata) {
        return msg.data;
    }

    function _contextSuffixLength() internal view virtual returns (uint256) {
        return 0;
    }
}

// ─────────────────────────────────────────────────────────────
// 来源：node_modules/@openzeppelin/contracts/utils/introspection/IERC165.sol
// ─────────────────────────────────────────────────────────────
// OpenZeppelin Contracts (last updated v5.4.0) (utils/introspection/IERC165.sol)

/**
 * @dev Interface of the ERC-165 standard, as defined in the
 * https://eips.ethereum.org/EIPS/eip-165[ERC].
 *
 * Implementers can declare support of contract interfaces, which can then be
 * queried by others ({ERC165Checker}).
 *
 * For an implementation, see {ERC165}.
 */
interface IERC165 {
    /**
     * @dev Returns true if this contract implements the interface defined by
     * `interfaceId`. See the corresponding
     * https://eips.ethereum.org/EIPS/eip-165#how-interfaces-are-identified[ERC section]
     * to learn more about how these ids are created.
     *
     * This function call must use less than 30 000 gas.
     */
    function supportsInterface(bytes4 interfaceId) external view returns (bool);
}

// ─────────────────────────────────────────────────────────────
// 来源：node_modules/@openzeppelin/contracts/utils/introspection/ERC165.sol
// ─────────────────────────────────────────────────────────────
// OpenZeppelin Contracts (last updated v5.4.0) (utils/introspection/ERC165.sol)

/**
 * @dev Implementation of the {IERC165} interface.
 *
 * Contracts that want to implement ERC-165 should inherit from this contract and override {supportsInterface} to check
 * for the additional interface id that will be supported. For example:
 *
 * ```solidity
 * function supportsInterface(bytes4 interfaceId) public view virtual override returns (bool) {
 *     return interfaceId == type(MyInterface).interfaceId || super.supportsInterface(interfaceId);
 * }
 * ```
 */
abstract contract ERC165 is IERC165 {
    /// @inheritdoc IERC165
    function supportsInterface(bytes4 interfaceId) public view virtual returns (bool) {
        return interfaceId == type(IERC165).interfaceId;
    }
}

// ─────────────────────────────────────────────────────────────
// 来源：node_modules/@openzeppelin/contracts/access/AccessControl.sol
// ─────────────────────────────────────────────────────────────
// OpenZeppelin Contracts (last updated v5.6.0) (access/AccessControl.sol)

/**
 * @dev Contract module that allows children to implement role-based access
 * control mechanisms. This is a lightweight version that doesn't allow enumerating role
 * members except through off-chain means by accessing the contract event logs. Some
 * applications may benefit from on-chain enumerability, for those cases see
 * {AccessControlEnumerable}.
 *
 * Roles are referred to by their `bytes32` identifier. These should be exposed
 * in the external API and be unique. The best way to achieve this is by
 * using `public constant` hash digests:
 *
 * ```solidity
 * bytes32 public constant MY_ROLE = keccak256("MY_ROLE");
 * ```
 *
 * Roles can be used to represent a set of permissions. To restrict access to a
 * function call, use {hasRole}:
 *
 * ```solidity
 * function foo() public {
 *     require(hasRole(MY_ROLE, msg.sender));
 *     ...
 * }
 * ```
 *
 * Roles can be granted and revoked dynamically via the {grantRole} and
 * {revokeRole} functions. Each role has an associated admin role, and only
 * accounts that have a role's admin role can call {grantRole} and {revokeRole}.
 *
 * By default, the admin role for all roles is `DEFAULT_ADMIN_ROLE`, which means
 * that only accounts with this role will be able to grant or revoke other
 * roles. More complex role relationships can be created by using
 * {_setRoleAdmin}.
 *
 * WARNING: The `DEFAULT_ADMIN_ROLE` is also its own admin: it has permission to
 * grant and revoke this role. Extra precautions should be taken to secure
 * accounts that have been granted it. We recommend using {AccessControlDefaultAdminRules}
 * to enforce additional security measures for this role.
 */
abstract contract AccessControl is Context, IAccessControl, ERC165 {
    struct RoleData {
        mapping(address account => bool) hasRole;
        bytes32 adminRole;
    }

    mapping(bytes32 role => RoleData) private _roles;

    bytes32 public constant DEFAULT_ADMIN_ROLE = 0x00;

    /**
     * @dev Modifier that checks that an account has a specific role. Reverts
     * with an {AccessControlUnauthorizedAccount} error including the required role.
     */
    modifier onlyRole(bytes32 role) {
        _checkRole(role);
        _;
    }

    /// @inheritdoc ERC165
    function supportsInterface(bytes4 interfaceId) public view virtual override returns (bool) {
        return interfaceId == type(IAccessControl).interfaceId || super.supportsInterface(interfaceId);
    }

    /**
     * @dev Returns `true` if `account` has been granted `role`.
     */
    function hasRole(bytes32 role, address account) public view virtual returns (bool) {
        return _roles[role].hasRole[account];
    }

    /**
     * @dev Reverts with an {AccessControlUnauthorizedAccount} error if `_msgSender()`
     * is missing `role`. Overriding this function changes the behavior of the {onlyRole} modifier.
     */
    function _checkRole(bytes32 role) internal view virtual {
        _checkRole(role, _msgSender());
    }

    /**
     * @dev Reverts with an {AccessControlUnauthorizedAccount} error if `account`
     * is missing `role`.
     */
    function _checkRole(bytes32 role, address account) internal view virtual {
        if (!hasRole(role, account)) {
            revert AccessControlUnauthorizedAccount(account, role);
        }
    }

    /**
     * @dev Returns the admin role that controls `role`. See {grantRole} and
     * {revokeRole}.
     *
     * To change a role's admin, use {_setRoleAdmin}.
     */
    function getRoleAdmin(bytes32 role) public view virtual returns (bytes32) {
        return _roles[role].adminRole;
    }

    /**
     * @dev Grants `role` to `account`.
     *
     * If `account` had not been already granted `role`, emits a {RoleGranted}
     * event.
     *
     * Requirements:
     *
     * - the caller must have ``role``'s admin role.
     *
     * May emit a {RoleGranted} event.
     */
    function grantRole(bytes32 role, address account) public virtual onlyRole(getRoleAdmin(role)) {
        _grantRole(role, account);
    }

    /**
     * @dev Revokes `role` from `account`.
     *
     * If `account` had been granted `role`, emits a {RoleRevoked} event.
     *
     * Requirements:
     *
     * - the caller must have ``role``'s admin role.
     *
     * May emit a {RoleRevoked} event.
     */
    function revokeRole(bytes32 role, address account) public virtual onlyRole(getRoleAdmin(role)) {
        _revokeRole(role, account);
    }

    /**
     * @dev Revokes `role` from the calling account.
     *
     * Roles are often managed via {grantRole} and {revokeRole}: this function's
     * purpose is to provide a mechanism for accounts to lose their privileges
     * if they are compromised (such as when a trusted device is misplaced).
     *
     * If the calling account had been revoked `role`, emits a {RoleRevoked}
     * event.
     *
     * Requirements:
     *
     * - the caller must be `callerConfirmation`.
     *
     * May emit a {RoleRevoked} event.
     */
    function renounceRole(bytes32 role, address callerConfirmation) public virtual {
        if (callerConfirmation != _msgSender()) {
            revert AccessControlBadConfirmation();
        }

        _revokeRole(role, callerConfirmation);
    }

    /**
     * @dev Sets `adminRole` as ``role``'s admin role.
     *
     * Emits a {RoleAdminChanged} event.
     */
    function _setRoleAdmin(bytes32 role, bytes32 adminRole) internal virtual {
        bytes32 previousAdminRole = getRoleAdmin(role);
        _roles[role].adminRole = adminRole;
        emit RoleAdminChanged(role, previousAdminRole, adminRole);
    }

    /**
     * @dev Attempts to grant `role` to `account` and returns a boolean indicating if `role` was granted.
     *
     * Internal function without access restriction.
     *
     * May emit a {RoleGranted} event.
     */
    function _grantRole(bytes32 role, address account) internal virtual returns (bool) {
        if (!hasRole(role, account)) {
            _roles[role].hasRole[account] = true;
            emit RoleGranted(role, account, _msgSender());
            return true;
        } else {
            return false;
        }
    }

    /**
     * @dev Attempts to revoke `role` from `account` and returns a boolean indicating if `role` was revoked.
     *
     * Internal function without access restriction.
     *
     * May emit a {RoleRevoked} event.
     */
    function _revokeRole(bytes32 role, address account) internal virtual returns (bool) {
        if (hasRole(role, account)) {
            _roles[role].hasRole[account] = false;
            emit RoleRevoked(role, account, _msgSender());
            return true;
        } else {
            return false;
        }
    }
}

// ─────────────────────────────────────────────────────────────
// 来源：contracts/VideoEvidence.sol
// ─────────────────────────────────────────────────────────────
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

