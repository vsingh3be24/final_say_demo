// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FinalSayAnchor
/// @notice Append-only commitments to batches of official notices.
/// @dev Only roots, opaque batch IDs, the publisher wallet and block time are
///      written on-chain. Notice contents and personal information stay off-chain.
contract FinalSayAnchor {
    address public immutable owner;

    struct AnchorRecord {
        bytes32 batchId;
        bytes32 issuerId;
        address publisher;
        uint64 anchoredAt;
    }

    mapping(bytes32 root => AnchorRecord record) private _anchors;
    mapping(bytes32 batchId => bytes32 root) private _batchRoots;

    event RootAnchored(
        bytes32 indexed root,
        bytes32 indexed batchId,
        bytes32 indexed issuerId,
        address publisher,
        uint64 anchoredAt
    );

    error OnlyOwner();
    error EmptyRoot();
    error EmptyBatchId();
    error EmptyIssuerId();
    error TimestampOverflow();
    error RootAlreadyAnchored();
    error BatchAlreadyAnchored();

    constructor() {
        owner = msg.sender;
    }

    function _timestampToUint64(uint256 timestamp) private pure returns (uint64) {
        if (timestamp > type(uint64).max) revert TimestampOverflow();
        // The explicit bound check above guarantees this conversion cannot truncate.
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint64(timestamp);
    }

    function anchorRoot(bytes32 root, bytes32 batchId, bytes32 issuerId) external {
        if (msg.sender != owner) revert OnlyOwner();
        if (root == bytes32(0)) revert EmptyRoot();
        if (batchId == bytes32(0)) revert EmptyBatchId();
        if (issuerId == bytes32(0)) revert EmptyIssuerId();
        if (_anchors[root].anchoredAt != 0) revert RootAlreadyAnchored();
        if (_batchRoots[batchId] != bytes32(0)) revert BatchAlreadyAnchored();

        uint64 anchoredAt = _timestampToUint64(block.timestamp);
        _anchors[root] = AnchorRecord({
            batchId: batchId,
            issuerId: issuerId,
            publisher: msg.sender,
            anchoredAt: anchoredAt
        });
        _batchRoots[batchId] = root;
        emit RootAnchored(root, batchId, issuerId, msg.sender, anchoredAt);
    }

    function getAnchor(bytes32 root)
        external
        view
        returns (bytes32 batchId, bytes32 issuerId, address publisher, uint64 anchoredAt)
    {
        AnchorRecord memory record = _anchors[root];
        return (record.batchId, record.issuerId, record.publisher, record.anchoredAt);
    }

    function getRootForBatch(bytes32 batchId) external view returns (bytes32) {
        return _batchRoots[batchId];
    }
}
