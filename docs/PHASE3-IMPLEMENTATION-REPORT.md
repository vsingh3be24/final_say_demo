# Phase 3 Implementation Report

> This report records the Phase 3 evidence snapshot from 3 November 2026.
> For current source ingestion, database state, tests, and launch gaps, read the
> [end-to-end implementation report](END-TO-END-IMPLEMENTATION-REPORT.md).

**Project:** FinalSay prototype  
**Report date:** 3 November 2026  
**Scope:** Polygon Amoy provenance integration and independent reviewer benchmarking

## Summary

The implementation is locally testable and the complete backend and frontend test/build checks pass. The repository contains an append-only Solidity anchoring contract, an Amoy backend adapter, additive database migration fields, provenance API/UI changes, deployment guidance, and contract/adapter tests. Local-only provenance remains available. No public testnet deployment or on-chain transaction has been confirmed.

The current checkout is **not deployed to a public chain**. Issuer-set hashes flow through root construction, persistence, retry, read-back comparisons, API responses, and both student/Admin provenance displays. Foundry has now been installed and the contract compiles and passes its local tests. The official Amoy RPC hostname still fails system DNS resolution, and no wallet, contract address, deployment, or on-chain transaction is configured or claimed.

## Implemented

### Provenance and blockchain

- Added `contracts/FinalSayAnchor.sol`, an owner-controlled append-only root registry with duplicate root/batch rejection and stored batch, issuer-set hash, publisher, and timestamp.
- Added a Foundry test file covering successful storage, owner restrictions, duplicate identifiers, and empty inputs.
- Added a Polygon Amoy backend adapter with chain ID validation, receipt handling, transaction retry handling, contract read-back, and an explicit local fallback before broadcast.
- Added configuration names for Amoy RPC URL, private key, chain ID, and contract address. The private-key setting is marked secret and excluded from settings representation; no key is configured in this environment.
- Added persistence fields and startup migration support for network, contract, publisher, batch, block, timestamp, submission time, status, and error.
- Added the persisted and returned issuer-set hash and require it to match during public read-back verification.
- Added admin root retry/API support and UI presentation of public chain metadata and explorer links.
- Automatic root building is connected to issuer publishing and official-notice ingestion. Student-submitted notices are excluded from public commitments.
- Added deployment and testnet setup instructions in `docs/POLYGON-AMOY-DEPLOYMENT.md`.
- Installed Foundry v1.8.7 from the [official `foundry-rs/foundryup` installer](https://github.com/foundry-rs/foundryup) with signature/attestation verification enabled; `forge --version` reported commit `985eeea031d79922cd654d4e94e6c3701e1c7d73`.
- Added an explicit uint64 timestamp bounds check in the contract before storing the block timestamp.

### Reviewer benchmarking

The existing benchmark interface and API support two independent reviewer accounts labeling the same corpus. Labels are scoped to the authenticated account, hidden from the other reviewer, and locked when a reviewer submits a complete pass. Cohen’s Kappa is withheld until two reviewers complete the same corpus fingerprint. The full backend suite includes an API integration test that signs in two distinct reviewer accounts, verifies label isolation, completes both passes, and checks Kappa `0.615385` from their submitted annotations. This is automated integration-test evidence; it is not evidence that two real people have completed a production benchmark pass.

## Verification evidence and limits

| Area | Evidence | Result |
|---|---|---|
| Backend suite | `backend/.venv/bin/python -m pytest backend/finalsay/tests -q` | **117 passed** after the backend integration, issuer-hash comparison, and failed-receipt verification regression test |
| Reviewer integration | `backend/finalsay/tests/test_reviewer.py::test_benchmark_annotate_and_kappa` in the full suite | Two authenticated reviewer accounts labeled the same pairs independently; Kappa computed from those account-bound annotations as `0.615385` |
| Frontend build | `npm run build` in `apps/web` after issuer-set-hash response/UI changes | Passed (TypeScript and Vite production build) |
| Python syntax | `backend/.venv/bin/python -m compileall -q backend/finalsay` | Passed |
| Deployment/check script syntax | `backend/.venv/bin/python -m py_compile contracts/check_amoy.py contracts/deploy_amoy.py` | Passed |
| Database migration | Ran `run_migrations(engine)` against local `backend/finalsay.db` and inspected `merkle_root` columns | Passed; `anchor_issuer_id` exists |
| Foundry installation | Official `foundryup` installed v1.8.7 for macOS ARM64; release and binary attestations verified | `forge`, `cast`, `anvil`, `chisel`, and `solar` installed and version reported |
| Solidity compilation | `/Users/raginikalra/.foundry/bin/forge build` | Passed with Solc 0.8.24; compiler output: `Compiler run successful!` |
| Contract tests | `/Users/raginikalra/.foundry/bin/forge test -vv` | **4 passed, 0 failed, 0 skipped**: stores root/batch/issuer/publisher/time, blocks unauthorized writes, rejects duplicates, rejects empty identifiers |
| Amoy RPC | Read-only `eth_chainId` request to `https://rpc-amoy.polygon.technology/` using Web3 8.0.0; system-resolver control lookup for `github.com` | Amoy hostname returns DNS `gaierror`; GitHub resolves. No JSON-RPC response. Network security settings were not changed. `backend/requirements.txt` declares `web3>=7,<8`, unlike the installed 8.0.0 client |
| Deployment configuration | Sanitized settings check: `anchor_mode=local`, RPC/signer/contract all unset, configured chain ID 80002 | Public anchoring remains unconfigured |
| On-chain confirmation | No transaction hash or receipt was produced | No deployment or public anchor is claimed |
| API restart | Reviewed original Uvicorn PID/command/cwd and runtime configuration, created `/private/tmp/finalsay-prephase3-restart.db` with mode `0600` and SQLite integrity `ok`, then ran `backend/.venv/bin/python -m uvicorn finalsay.main:app --host 127.0.0.1 --port 8000` | New API PID 51678 is running on `127.0.0.1:8000`; no `.env` file or Amoy/database overrides were present |
| API health/readiness/docs | Live GETs to `/api/health`, `/api/health/ready`, `/docs`, and `/openapi.json` | All returned HTTP 200; OpenAPI includes issuer publish, candidate retrieval, provenance retry, and `anchor_issuer_id` response field |
| Frontend | Existing Node PID 46231 on `127.0.0.1:5173`; live GET to `/FinalSay-prototype/notices`; `npm run build` | Route returned HTTP 200; production build passed |
| Backend regression suite | `backend/.venv/bin/python -m pytest backend/finalsay/tests -q` after restart | **117 passed** |
| Database preservation | Compared the backup with current SQLite data for users, notices, institutions, relation edges, Merkle roots, and proofs | No IDs/rows were lost or added. Core tables were byte-value identical except 28 existing notices whose `retrieved_at` timestamps refreshed during the scheduled poll; all other notice fields matched |
| Scheduled scraping | Startup poll log and latest `scrape_run` records | Poll ran: 28 unchanged, 0 created/modified, 2 partial-source errors. Thapar fetched 23 unchanged notices with `SourceFetchError`; IIT Bombay fetched 5 unchanged notices and logged `PDF had no extractable text`. Both failures were stored in `scrape_run` |

## Remaining gaps and operating limits

1. Polygon Amoy DNS/RPC must become reachable from this host before live chain compatibility can be verified. The official endpoint is configured in deployment instructions; the machine's DNS currently fails for that hostname.
2. Public anchoring requires a dedicated test wallet with test POL and a deployed contract. No wallet settings are currently present; no deployment was attempted.
3. Scraping remains operational but reported two source-specific partial errors in the startup poll: one PDF text extraction failure and one Thapar source fetch error. The 28 fetched notices were unchanged and were not duplicated.
4. Real reviewer accounts have not completed a human benchmark pass; the independent-account API integration flow is verified by automated tests.

## Next steps to complete Phase 3

1. Resolve/allow DNS access to the official Amoy RPC endpoint without relaxing general network security, then rerun the read-only `eth_chainId` check.
2. When ready for wallet-based deployment, add `POLYGON_AMOY_RPC_URL`, `POLYGON_AMOY_PRIVATE_KEY`, and `POLYGON_AMOY_CHAIN_ID=80002` to the ignored `backend/.env`; do not send the key in chat. After deployment, set `FINALSAY_ANCHOR_CONTRACT_ADDRESS` from the confirmed deployment result.
3. Deploy only after wallet configuration and test POL funding are complete. Record the contract address and transaction hash, wait for a successful receipt, and verify the deployed contract by reading it back.
4. Have two real reviewers complete their own blind passes if a human benchmark result is required; the endpoint will then calculate Kappa from their account-bound annotations.

## Deployment statement

Foundry installation, compilation, and local tests are verified. **The contract has not been deployed, and no on-chain transaction is claimed by this report.**
