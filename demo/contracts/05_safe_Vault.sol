// SPDX-License-Identifier: MIT
// Control sample: a small vault written defensively (checks-effects-interactions, Solidity 0.8 overflow
// checks, explicit owner). The audit should report no High-impact findings in this file.
pragma solidity 0.8.26;

contract Vault {
    address public immutable owner;
    mapping(address => uint256) public balance;
    bool private locked;

    event Deposited(address indexed who, uint256 amount);
    event Withdrawn(address indexed who, uint256 amount);

    constructor() {
        owner = msg.sender;
    }

    modifier nonReentrant() {
        require(!locked, "reentrant call");
        locked = true;
        _;
        locked = false;
    }

    function deposit() external payable {
        require(msg.value > 0, "nothing sent");
        balance[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    function withdraw(uint256 amount) external nonReentrant {
        require(balance[msg.sender] >= amount, "insufficient balance");
        balance[msg.sender] -= amount;                       // effect before the external call
        (bool ok, ) = payable(msg.sender).call{value: amount}("");
        require(ok, "transfer failed");
        emit Withdrawn(msg.sender, amount);
    }
}
