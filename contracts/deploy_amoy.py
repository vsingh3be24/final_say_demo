#!/usr/bin/env python3
"""Deploy the Foundry-compiled FinalSayAnchor artifact to Polygon Amoy.

Run from ``backend/`` so the backend's ignored ``.env`` is loaded. The wallet
key is read in-process and is never printed or added to a command argument.
"""

from __future__ import annotations

import json
from pathlib import Path

from finalsay.config import get_settings
from web3 import Web3


def main() -> int:
    settings = get_settings()
    if not settings.polygon_rpc_url or not settings.polygon_private_key:
        raise SystemExit(
            "Set POLYGON_AMOY_RPC_URL and POLYGON_AMOY_PRIVATE_KEY in backend/.env first."
        )

    artifact_path = (
        Path(__file__).resolve().parent
        / "out"
        / "FinalSayAnchor.sol"
        / "FinalSayAnchor.json"
    )
    if not artifact_path.is_file():
        raise SystemExit("Compile first: cd contracts && forge build")
    artifact = json.loads(artifact_path.read_text())
    w3 = Web3(
        Web3.HTTPProvider(settings.polygon_rpc_url, request_kwargs={"timeout": 20})
    )
    if not w3.is_connected():
        raise SystemExit("Polygon Amoy RPC is unavailable.")
    if int(w3.eth.chain_id) != 80002 or int(settings.polygon_chain_id) != 80002:
        raise SystemExit(f"Refusing deployment: expected Amoy chain ID 80002, got {w3.eth.chain_id}.")

    account = w3.eth.account.from_key(settings.polygon_private_key)
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    constructor = factory.constructor()
    tx = constructor.build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": 80002,
            "gas": 1_500_000,
            "gasPrice": int(w3.eth.gas_price),
        }
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180, poll_latency=3)
    if int(receipt.status) != 1 or not receipt.contractAddress:
        raise SystemExit("Deployment receipt failed; no contract address was recorded.")

    deployed = w3.eth.contract(
        address=Web3.to_checksum_address(receipt.contractAddress), abi=artifact["abi"]
    )
    if deployed.functions.owner().call().lower() != account.address.lower():
        raise SystemExit("Deployment receipt confirmed, but owner readback did not match.")

    print(f"Network: Polygon Amoy (chain ID {w3.eth.chain_id})")
    print(f"Contract address: {receipt.contractAddress}")
    print(f"Deployment transaction: {tx_hash.hex()}")
    print(f"Block: {receipt.blockNumber}")
    print(f"Explorer: https://amoy.polygonscan.com/tx/{tx_hash.hex()}")
    print("Set FINALSAY_ANCHOR_CONTRACT_ADDRESS to the contract address in backend/.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
