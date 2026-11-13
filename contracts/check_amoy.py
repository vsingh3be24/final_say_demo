#!/usr/bin/env python3
"""Read-only Polygon Amoy RPC and deployed-contract compatibility check."""

from __future__ import annotations

import json
from pathlib import Path

from finalsay.config import get_settings
from web3 import Web3


def main() -> int:
    settings = get_settings()
    if not settings.polygon_rpc_url:
        raise SystemExit("Set POLYGON_AMOY_RPC_URL in backend/.env.")
    w3 = Web3(
        Web3.HTTPProvider(settings.polygon_rpc_url, request_kwargs={"timeout": 15})
    )
    if not w3.is_connected():
        raise SystemExit("Polygon Amoy RPC is unavailable.")
    chain_id = int(w3.eth.chain_id)
    if chain_id != 80002 or chain_id != int(settings.polygon_chain_id):
        raise SystemExit(f"Wrong chain: expected 80002, connected to {chain_id}.")
    print(f"RPC connected: Polygon Amoy, chain ID {chain_id}")
    print(f"Latest block: {w3.eth.block_number}")

    if settings.polygon_contract:
        artifact_path = (
            Path(__file__).resolve().parent
            / "out"
            / "FinalSayAnchor.sol"
            / "FinalSayAnchor.json"
        )
        if not artifact_path.is_file():
            raise SystemExit("Compile the contract first with `cd contracts && forge build`.")
        artifact = json.loads(artifact_path.read_text())
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.polygon_contract),
            abi=artifact["abi"],
        )
        batch_id, issuer_id, publisher, timestamp = contract.functions.getAnchor(bytes(32)).call()
        print("Contract read call succeeded: getAnchor(bytes32)")
        print(
            "Empty-root record: "
            f"batch={bytes(batch_id).hex()}, issuer_set={bytes(issuer_id).hex()}, "
            f"timestamp={timestamp}, publisher={publisher}"
        )
    else:
        print("No contract address configured; skipped contract read call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
