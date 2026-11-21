// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

// 课程报告里的「原版」合约（对照用，不建议照抄）。
//
// 它只有一个角色：平台凭 CONSUMER_ROLE 直接调用 `_burn(user, amount)`。
// 三个问题：
//   1. `_burn` 是 OZ 的 internal 函数，直接传 user 意味着**不需要用户
//      approve**，平台可以烧掉任意地址的余额；
//   2. 报告 2.2 的测试流程写「用户调用 consume」—— 用户没有
//      CONSUMER_ROLE，这条流程在合约上跑不通，只能改由部署者调用；
//   3. 余额是「用户→平台→销毁」，退款只能靠 mint，销毁/增发的总量
//      在链上看起来和真实交付无关（mint 不花钱）。
//
// 保留它是因为：答辩时把两版放在一起对比，能直接讲清
// 「为什么托管式设计更好」，比只交一版更有说服力。
contract VideoCreditSimple is ERC20, AccessControl {
    bytes32 public constant CONSUMER_ROLE = keccak256("CONSUMER_ROLE");
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    event Consumed(address indexed user, uint256 amount, string videoId);

    constructor() ERC20("VideoCredit", "VCR") {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(MINTER_ROLE, msg.sender);
        _grantRole(CONSUMER_ROLE, msg.sender);
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        _mint(to, amount);
    }

    function consume(address user, uint256 amount, string calldata videoId)
        external
        onlyRole(CONSUMER_ROLE)
    {
        _burn(user, amount);
        emit Consumed(user, amount, videoId);
    }
}
