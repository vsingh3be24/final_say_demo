# FinalSay Polygon Amoy setup

The contract and backend are implemented without testnet credentials. Public-chain anchoring stays disabled until the backend has a deployed contract address and a funded Amoy signing wallet. Local hash-chain anchoring remains the default.

Polygon's developer documentation currently lists Amoy as chain ID `80002`, public RPC `https://rpc-amoy.polygon.technology/`, currency `POL`, and explorer `https://amoy.polygonscan.com/` ([Polygon Remix guide](https://docs.polygon.technology/tools/dApp-development/common-tools/remix/)). Use a dedicated RPC URL if the public endpoint rate-limits your requests.

## Compile and run contract tests

Install Foundry (`forge` and `anvil`) using its official installer, then run:

```sh
cd contracts
forge build
forge test -vv
```

The tests cover owner-only writes, root and batch uniqueness, nonzero values, stored publisher/time, and lookup by root or batch. They run locally and do not submit transactions to Amoy.

## Wallet and deployment

1. Create a wallet for testnet use only. Add Polygon Amoy to the wallet with chain ID `80002` and the RPC/explorer above.
2. Request test POL from a Polygon Amoy faucet. Do not fund this test wallet with mainnet assets.
3. Copy the backend environment template to the ignored local file `backend/.env`. Set these values there; never paste the private key into chat or commit the file:

   ```dotenv
   FINALSAY_ANCHOR=polygon
   POLYGON_AMOY_RPC_URL=https://rpc-amoy.polygon.technology/
   POLYGON_AMOY_PRIVATE_KEY=<test-wallet-private-key>
   POLYGON_AMOY_CHAIN_ID=80002
   FINALSAY_ANCHOR_CONTRACT_ADDRESS=
   FINALSAY_POLYGON_RECEIPT_TIMEOUT=45
   ```

4. From `backend/`, run the read-only RPC and deployed-contract compatibility check:

   ```sh
   PYTHONPATH=. .venv/bin/python ../contracts/check_amoy.py
   ```

   This verifies the RPC response, chain ID, latest-block call, and (when configured) the contract's `getAnchor` read. It submits no transaction.
5. From `contracts/`, run `forge build` to create the artifact, then `forge test -vv`.
6. Deploy using the same wallet that the backend will use (the deploying wallet becomes the contract owner):

   ```sh
   cd ../backend
   PYTHONPATH=. .venv/bin/python ../contracts/deploy_amoy.py
   ```

   The script checks the connected chain, waits for a successful deployment receipt, reads `owner()` back, and prints the contract address and deployment transaction. It does not print the private key.
7. Put the reported contract address in `FINALSAY_ANCHOR_CONTRACT_ADDRESS` in `backend/.env`, restart the backend, and run the read-only check again. The app refuses to send transactions when the configured chain is not Amoy.
8. Publish or scrape an official notice, or use Admin → Integrity to build its UTC-day root. The workflow computes notice SHA-256 hashes and the Merkle root locally, submits the root, opaque batch ID, and opaque hash of the issuer set, waits for a receipt, and stores the transaction metadata in SQLite.
9. In the student result page, verify the matched official notice. The UI reports `VERIFIED` only after a live contract read matches the notice's recomputed hash, proof root, batch ID, and issuer-set hash. A local-only result is labeled `LOCAL_VERIFIED` and is not represented as public-chain verification.

Transaction links use `https://amoy.polygonscan.com/tx/<hash>`; contract links use `https://amoy.polygonscan.com/address/<address>`.

## Required backend variables

- `POLYGON_AMOY_RPC_URL`
- `POLYGON_AMOY_PRIVATE_KEY`
- `POLYGON_AMOY_CHAIN_ID`
- `FINALSAY_ANCHOR_CONTRACT_ADDRESS`

The backend also accepts the earlier `FINALSAY_POLYGON_*` aliases for local compatibility. The private key is marked secret in application settings and is never part of API schemas or frontend configuration.
