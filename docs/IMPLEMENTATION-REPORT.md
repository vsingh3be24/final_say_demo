# FinalSay implementation report

> Historical snapshot from 3 November 2026. Its database counts, source
> statuses, and local credentials are superseded. See the
> [current end-to-end report](END-TO-END-IMPLEMENTATION-REPORT.md).

**Evidence snapshot:** 3 November 2026  
**Application:** local research/demo prototype  
**Repository:** current `FinalSay-prototype-main` checkout

## Executive summary

FinalSay is implemented as a locally runnable notice comparison prototype. A
student can submit text or a supported document; the backend extracts and
redacts its text, retrieves current official notices for the selected
institution, compares the submission with the best candidate, and saves a
relationship result and evidence. Uncertain results can enter a reviewer
queue. Administrators manage source polling and issuer grants. Issuers with an
active grant can publish official test records.

The repository also includes public-source scrapers for Thapar and IIT Bombay,
an NIT Jalandhar adapter that is currently paused, synthetic model evaluation,
local hash-chain/Merkle provenance, an optional Polygon Amoy integration, and
blind reviewer benchmarking. The current default provenance mode is local.
There is no confirmed testnet deployment or transaction, and there are no
independent human benchmark labels yet.

## Architecture and implemented workflow

| Layer | Implementation | Main files |
|---|---|---|
| Frontend | React, TypeScript, Vite PWA; student, reviewer, admin, and issuer routes | `apps/web/src/App.tsx`, `apps/web/src/pages/` |
| API | FastAPI with role-protected routes and bearer-token authentication | `backend/finalsay/main.py`, `backend/finalsay/api/`, `backend/finalsay/auth.py` |
| Database | SQLAlchemy models; SQLite local default, PostgreSQL configured as an option | `backend/finalsay/models.py`, `backend/finalsay/db.py`, `backend/finalsay/migrations.py` |
| Extraction | Pasted text and PDF extraction; optional Tesseract OCR; field extraction and PII redaction | `backend/finalsay/services/extraction.py` |
| Scraping | Per-institution HTML/PDF or JSON/PDF adapters; scheduled and manual polling | `backend/finalsay/adapters/live.py`, `backend/finalsay/services/scrape_runtime.py` |
| Comparison | Semantic retrieval and local NLI by default; deterministic mock and optional legacy HF classifier | `backend/finalsay/services/comparison.py`, `backend/finalsay/models_iface/semantic_model.py`, `backend/finalsay/models_iface/comparison_model.py` |
| Provenance | SHA-256 notice hashes, daily Merkle proofs, local hash-chain anchor; Polygon adapter is opt-in | `backend/finalsay/services/provenance.py`, `backend/finalsay/models_iface/anchor.py`, `contracts/FinalSayAnchor.sol` |
| Review and evaluation | Human review queue, blind pair annotation, kappa service, synthetic holdout evaluation | `backend/finalsay/api/reviewer.py`, `backend/finalsay/services/kappa.py`, `backend/finalsay/eval/` |

The main data flow is:

1. A student submits pasted text or a PDF; image OCR is available only when a
   Tesseract binary is installed.
2. Extraction normalizes text, identifies selected fields, and redacts
   recognized personal data before storage.
3. The comparison service retrieves current official candidates from the same
   institution. Semantic embeddings rank candidates; a local NLI model
   compares notice claims and records evidence.
4. The service saves a relation edge. Low-confidence or unsupported outcomes
   remain `unresolved` and can create a reviewer case.
5. Provenance hashes and daily Merkle proofs support later integrity checks.
   Local hash-chain anchoring is the default.

The supported relationship labels are `consistent`, `contradictory`,
`superseded`, and `unresolved`, with the additional existing labels `corrected`,
`extended`, and `cancelled` retained for compatibility.

## Implemented capabilities

### Authentication and publishing

Passwords are hashed and API sessions use signed bearer tokens. Public
self-registration creates student accounts only. Privileged roles are
provisioned through the seed process or the reviewer-only account provisioning
command. Issuers can publish only for an active institution that an admin has
explicitly granted to them. The local issuer publishing UI and
`POST /api/issuer/publish` share the same ingestion pipeline.

The requested end-semester examination test record is saved as official notice
**#189** in the local database. Its `example.test` source URL is a placeholder;
the record is synthetic and is not evidence that Thapar published it.

### Public institutional scraping

Two official sources have populated the database:

| Source | Adapter | Stored versions | Current notices |
|---|---|---:|---:|
| [Thapar Dean Academics Notice Board](https://www.thapar.edu/students/pages/dean-academics-notice-board) | `thapar_html` | 50 | 24 |
| [IIT Bombay Academic Office Circulars](https://acad.iitb.ac.in/circulars) | `iitb_html` | 23 | 15 |

The local DB also has an NIT Jalandhar JSON/PDF adapter configured, but that
source is paused after a connection reset and has no saved notices. Across the
two working sources, 73 official version rows are stored, 39 current. A
publication date was extracted for 23 of those rows.

The latest manual source poll reported zero new, zero revised, 28 unchanged,
and two source errors. The Thapar run was partial because one linked PDF
returned HTTP 404. The IIT Bombay run was partial because two linked PDFs had
no extractable text. Recorded poll counters include repeated observations:
they are not unique-notice counts. Changes are stored as linked versions;
unchanged notices are deduplicated. Retrieval time, source URL, content hash,
and recognized publication date are saved with notice records.

The admin source page uses backend values for source state, poll history,
counts, errors, and notice browsing. Manual and scheduled polling share a
process lock. The scheduler runs at startup and every six hours by default.
Source requests use HTTPS, host allowlists, DNS checks against non-public
addresses, robots rules, same-host redirects, request/size limits, per-host
spacing, and bounded retry behavior.

More source and scrape-run detail is in the [Phase 2 scraping report](PHASE2-SCRAPING-REPORT.md).

### Semantic model and evaluation

Semantic candidate retrieval and local NLI are the default configured path.
`MockComparisonModel` remains available for offline deterministic checks;
`HFComparisonModel` is optional. Low confidence remains `unresolved`. Model
scores are comparative scores, not calibrated probabilities.

The existing synthetic evaluation reports 30 validation pairs and 21 pairs in
each holdout. The semantic model's macro-F1 was **0.295** on the temporal
holdout and **0.686** on the institution holdout. These small generated-fixture
results are regression diagnostics, not real-world performance estimates.
The generated benchmark kappa is not human agreement.

One direct local retrieval check used student submission #289. Scraped Thapar
notice #288 ranked first with combined rank score 1.0 and embedding cosine
0.689945; the persisted relation is `unresolved`. This verifies retrieval and
does not claim a correct resolved classification.

### Reviewer benchmarking

The local database has two distinct reviewer accounts and a shared 308-pair
corpus. Each authenticated reviewer sees only their own saved labels. A
completed pass is locked, and Cohen's kappa is hidden until two distinct
reviewer accounts complete the same corpus. Generated seed annotations are
excluded from that calculation.

At this snapshot, the database has 616 generated annotations, **zero
account-bound human annotations**, and zero completed passes. Therefore no
human kappa has been measured. The demo accounts are for workflow testing; an
academic study should use two actual reviewers with separate credentials and
independently collected labels.

### Provenance and optional blockchain integration

Official and submitted notices receive content hashes. Daily Merkle roots and
proofs are stored in the application database; the current local database has
8 roots, 8 local anchor-chain blocks, and 251 proofs. The default local anchor
does not provide an external blockchain receipt.

`FinalSayAnchor.sol` stores the Merkle root, opaque batch and issuer-set hashes,
publisher address, and timestamp.
The backend's Polygon Amoy adapter can submit a root and check the contract
mapping when the Web3 dependency, RPC URL, test wallet, deployed contract
address, and Amoy funds are configured. Mocked tests exercise transaction
confirmation, pending receipt, revert, and local fallback paths. The local
environment has no configured contract or wallet and no confirmed on-chain
transaction is recorded. See the Polygon deployment steps in the
[integrated demo guide](integrated-demo-guide.md).

## Database snapshot

The local SQLite database currently contains:

| Entity | Rows |
|---|---:|
| Institutions | 6 |
| Users | 5 |
| Notices | 289 (205 official, 84 submissions) |
| Notice fields | 1,445 |
| Relation edges | 84 |
| Review cases | 43 |
| Benchmark pairs | 308 |
| Generated benchmark annotations | 616 |
| Account-bound reviewer annotations | 0 |
| Scrape runs | 18 |
| Merkle roots / proofs | 8 / 251 |
| Local anchor-chain blocks | 8 |

These values are a local snapshot and will change as the application is used.

## Verification and local access

- Backend test suite: **108 passed** with `(cd backend && .venv/bin/pytest finalsay/tests -q)`.
- Frontend TypeScript/Vite production build: passed with `cd apps/web && npm run build`.
- Direct semantic retrieval: notice #288 ranked first for submission #289.
- Admin source UI: manual poll showed the two real-source results and their
  partial-run errors.
- Local runtime: frontend at <http://localhost:5173>, API readiness at
  <http://localhost:8000/api/health/ready>, and API documentation at
  <http://localhost:8000/docs>.

Seeded local demo credentials are listed in the repository [README](../README.md).

## Known limitations and next work

1. Fix or exclude the stale and non-text PDFs; investigate OCR for scanned
   notices if it is needed for the selected sites.
2. Re-test the NITJ feed when its host is reachable before enabling polling.
3. Collect real notice-pair labels independently from two reviewers before
   reporting human agreement or real-world model performance.
4. For a real testnet run, install the configured Web3 dependency, deploy the
   contract to Amoy, configure a dedicated funded test wallet and RPC endpoint,
   then verify a transaction receipt and contract state. No deployment is
   claimed in this report.
5. Expand source and held-out evaluation coverage before making claims about
   institutional completeness or generalization.

The prototype is locally operational for demonstrations and integration
testing. It is not yet a validated institutional decision system.
