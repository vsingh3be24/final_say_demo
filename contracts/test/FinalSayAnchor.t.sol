// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../FinalSayAnchor.sol";

contract UnauthorizedPublisher {
    function publish(FinalSayAnchor target, bytes32 root, bytes32 batchId, bytes32 issuerId) external {
        target.anchorRoot(root, batchId, issuerId);
    }
}

contract FinalSayAnchorTest {
    function testRecordsRootBatchPublisherAndTimestamp() external {
        FinalSayAnchor target = new FinalSayAnchor();
        bytes32 root = keccak256("root");
        bytes32 batchId = keccak256("batch");
        bytes32 issuerId = keccak256("issuer");

        target.anchorRoot(root, batchId, issuerId);
        (bytes32 storedBatch, bytes32 storedIssuer, address publisher, uint64 anchoredAt) = target.getAnchor(root);

        require(storedBatch == batchId, "batch mismatch");
        require(storedIssuer == issuerId, "issuer mismatch");
        require(publisher == address(this), "publisher mismatch");
        require(anchoredAt != 0, "timestamp missing");
        require(target.getRootForBatch(batchId) == root, "batch lookup mismatch");
    }

    function testRejectsUnauthorizedPublisher() external {
        FinalSayAnchor target = new FinalSayAnchor();
        UnauthorizedPublisher caller = new UnauthorizedPublisher();
        (bool success,) = address(caller).call(
            abi.encodeCall(
                UnauthorizedPublisher.publish,
                (target, keccak256("root"), keccak256("batch"), keccak256("issuer"))
            )
        );
        require(!success, "unauthorized publication succeeded");
    }

    function testRejectsDuplicateRootAndBatch() external {
        FinalSayAnchor target = new FinalSayAnchor();
        bytes32 root = keccak256("root");
        bytes32 batchId = keccak256("batch");
        bytes32 issuerId = keccak256("issuer");
        target.anchorRoot(root, batchId, issuerId);

        (bool duplicateRootSucceeded,) = address(target).call(
            abi.encodeCall(FinalSayAnchor.anchorRoot, (root, keccak256("other batch"), issuerId))
        );
        (bool duplicateBatchSucceeded,) = address(target).call(
            abi.encodeCall(FinalSayAnchor.anchorRoot, (keccak256("other root"), batchId, issuerId))
        );
        require(!duplicateRootSucceeded, "duplicate root succeeded");
        require(!duplicateBatchSucceeded, "duplicate batch succeeded");
    }

    function testRejectsEmptyValues() external {
        FinalSayAnchor target = new FinalSayAnchor();
        (bool emptyRootSucceeded,) = address(target).call(
            abi.encodeCall(FinalSayAnchor.anchorRoot, (bytes32(0), keccak256("batch"), keccak256("issuer")))
        );
        (bool emptyBatchSucceeded,) = address(target).call(
            abi.encodeCall(FinalSayAnchor.anchorRoot, (keccak256("root"), bytes32(0), keccak256("issuer")))
        );
        (bool emptyIssuerSucceeded,) = address(target).call(
            abi.encodeCall(FinalSayAnchor.anchorRoot, (keccak256("root"), keccak256("batch"), bytes32(0)))
        );
        require(!emptyRootSucceeded, "empty root succeeded");
        require(!emptyBatchSucceeded, "empty batch succeeded");
        require(!emptyIssuerSucceeded, "empty issuer succeeded");
    }
}
