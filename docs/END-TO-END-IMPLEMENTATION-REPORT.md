# FinalSay end-to-end implementation report

**Evidence date:** 11 November 2026 (Asia/Kolkata)  
**Environment:** local development runtime with the existing SQLite database

**Live-state refresh (11 November, 00:20 IST):** FastAPI PID 77320 is listening
on `127.0.0.1:8000` and `/api/health/ready` returns `{"status":"ok"}`; Vite PID
46231 serves the login page on `127.0.0.1:5173` (HTTP 200). The SQLite database
has 2,204 official notice versions (2,084 current, 120 historical). The three
selected sources have 2,045 current records: VTU 640, Delhi 415, and Mumbai
990. Delhi's backfill is complete; VTU and Mumbai remain incomplete. The latest
selected-source query found no current publication-date gaps or duplicate
current source keys. Extraction quality is 1,264 extracted, 263 listing-only,
517 unknown, and one unextractable. There are still 45 real unlabeled benchmark
pairs, zero product users, zero student submissions, zero relation edges, and
zero human annotations.

The API restart applied the additive `source_content_sha256` migration without
changing notice rows; the pre-migration SQLite backup at
`/private/tmp/finalsay-before-revision-flow-migration-20261111.db` passes
`PRAGMA integrity_check`. New PDF/image source fetches retain a raw-file hash
separate from the normalized notice hash, allowing a changed file at the same
URL to create a version even if extracted text is identical. Existing rows
establish that fingerprint baseline on their next unchanged poll. The API's
scheduled poll is enabled at two-hour intervals; its startup poll was deferred
because the checkpointed VTU backfill process (PID 72839) held the shared scrape
lock, and the scheduler is retrying the lock every 60 seconds.

Revision-flow verification used an isolated test database: an original and a
clearly titled revised exam notice at different URLs were stored, then a
student submitted the older 30 November text. Candidate retrieval selected the
new revised notice and the API returned `superseded`; no test rows were written
to the product database. A separate offline probe of the configured semantic
model also returned `superseded` for the 30 November / 5 December wording with
contradiction score 0.999 (an uncalibrated model score). This proves the local
integration with controlled text, not that a real portal has published that
specific pair. The full backend suite and frontend production build pass.

**Earlier snapshot (10 November, 03:41 IST):** The API and frontend both
returned HTTP 200 on localhost. After fixing backward Delhi pagination, the
API startup poll completed in runs 142–144, adding 35 current notices (10 VTU,
0 Delhi, 25 Mumbai) and no revisions. Delhi is marked backfill-complete; VTU
and Mumbai continue. The database has 1,404 versions (1,290 current, 114
historical), including 260 current VTU, 376 Delhi, and 615 Mumbai notices.
The scheduler also refreshed six unknown documents into separately hashed
sidecars without changing notice hashes or versions; three more were applied
from a dry-run-validated batch. There are now 9 sidecars and 586 unknown
current notices. Read-only semantic retrieval used the new supplements and
ranked their matching notices #298 (VTU), #397 (Delhi), and #426 (Mumbai)
first, with cosine scores 0.939, 0.990, and 0.871. There are zero duplicate
current keys and zero current selected-source date gaps.

Current extraction-quality split by source: VTU 258 `extracted`, 3
`listing_only`, 99 `unknown`; Delhi 19 `extracted`, 159 `listing_only`, 198
`unknown`; Mumbai 573 `extracted`, 46 `listing_only`, 1 `unextractable`, 245
`unknown`. Overall, 850 selected-source current records are marked extracted,
208 listing-only, 542 unknown, and 1 unextractable. Unknown rows contain stored
text, but that alone does not prove it came from the underlying document. The
scheduled extraction refresher stores separately hashed, redacted sidecars
used by semantic retrieval; 53 sidecars currently exist.

The 586 unknown current rows have 117 VTU post-page URLs, 66 Delhi same-host
PDF URLs, 250 Mumbai same-host PDF URLs, 13 Mumbai image URLs, and 140 Delhi
Google Drive URLs. This identifies candidates for a bounded extraction
refresh; it does not prove those files are available or extractable. The Drive
URLs remain unfetched under the current source-host policy.

## What the project does

FinalSay checks whether a student's notice agrees with, contradicts, or has
been superseded by an official institutional notice. It ingests public source
notices, extracts and redacts text, retrieves relevant official candidates,
classifies their temporal relationship, and routes uncertain results to human
review. Local Merkle proofs provide tamper evidence; a public blockchain
transaction is an optional future deployment step.

## Current implementation

| Area | Current state | Evidence |
|---|---|---|
| Selected sources | VTU, University of Delhi Examination, University of Mumbai enabled; older Thapar and IIT Bombay sources are inactive and retained as real history | SQLite `institution` rows |
| Source records | 2,204 official-source versions; 2,084 current and 120 historical rows. Selected-source counts: VTU 640, Delhi 415, Mumbai 990. Older real Thapar and IIT Bombay records remain inactive | SQLite `notice` and `institution` queries, 11 Nov 2026 |
| Synthetic product data | At the latest DB check there are 45 unlabeled real revision pairs, no users/submissions/annotations, and zero duplicate current keys. Synthetic data and fictional fixture adapters are excluded from the production image; seed execution remains guarded to isolated test databases. | `clean_synthetic_data` preview; live SQLite counts and source rows; `.dockerignore`; seed guard |
| Ingestion | Startup and scheduled polling every two hours; Admin manual poll endpoint; bounded backfill; source run/error audit; HTTP retries; bounded 5-minute-to-1-hour exponential cycle retry after failures; versioned upsert. PDF/image fetches now fingerprint source bytes separately from normalized notice text, so same-URL file changes can create versions even if extracted text is unchanged. Each poll also refreshes up to two unknown same-source documents per institution into separately hashed sidecars. Admin Sources shows latest run status/error beside the last successful poll and extraction quality counts. Mumbai backfill uses stable circular-code checkpoints. New ORM-created institutions default to inert `unconfigured`, not a fixture source. | `source_onboarding.py`, `scrape_runtime.py`, `ingestion.py`, `document_extraction_backfill.py`, `adapters/live.py`, `SourcesPage.tsx`, `scrape_progress` and `scrape_run` |
| Duplicate and source-quality control | Zero duplicate current source keys. A partial unique database index enforces one current official row per institution/source key while allowing historical versions. VTU comment links with `#respond` are normalized to their post URL. A malformed Mumbai upload chain was retained for audit but its current row was removed from retrieval; future executable-suffix and filename-like rows are filtered. | Live SQLite index and `source_key` audit; duplicate-legacy migration test; backup at `/private/tmp/finalsay-after-mumbai-curation-20261109.db`; Mumbai adapter regression test |
| Extraction | Text-layer PDF extraction; bounded OCR fallback for poor/blank PDF text; Mumbai image scans use OCR. Separately hashed, redacted sidecars refresh legacy document text without changing notice hashes or versions. External-host attachments remain skipped. | `extraction.py`, `live.py`, `models.py`, `document_extraction_backfill.py`, `comparison.py`, tests |
| Publication dates | All 2,045 current selected-source notices have publication dates. This is metadata completeness; it does not prove the linked document was successfully extracted. | Current SQLite query, 11 Nov 2026 |
| Semantic retrieval | Local embedding retrieval and NLI comparison. Explicitly titled revisions (for example, “Revised …”) are prioritized over an original same-topic candidate, including when the notices use different source URLs. A temporary-database API regression test submitted the old 30 Nov notice, selected the revised 5 Dec URL, and returned `superseded`. The actual local semantic model also returned `superseded` on that controlled text pair. This is not evidence from a real institution publishing those exact dates; no product submission or human review is claimed. | `comparison.py`, `semantic_model.py`; isolated API test and offline model probe, 11 Nov 2026 |
| Reviewer benchmark | Two-account blind annotation and Cohen's Kappa code/API exist. There are 45 unlabeled real source-revision pairs, but no reviewer accounts or human annotations yet. The operator CLI provisions distinct reviewer accounts with hidden password prompts. No human agreement result is claimed | `benchmark_admin.py`, `SourcesPage.tsx`, `seed/create_reviewer.py`, reviewer routes, live SQLite counts |
| Synthetic cleanup safety | Cleanup now removes generated pairs/labels associated with synthetic notices and null-user generated labels, while preserving account-bound human annotations on real pairs. A regression test exercises this cleanup against mixed synthetic and real benchmark data | `clean_synthetic_data.py`, `test_clean_synthetic_data.py` |
| Provenance | Local hash chain and Merkle roots/proofs are available. Foundry compilation and four contract tests passed in the Phase 3 setup. No wallet, deployed contract address, confirmed transaction or on-chain proof is configured | Contract test results in `PHASE3-IMPLEMENTATION-REPORT.md`; current local settings/database |
| Local app | FastAPI `/api/health/ready` returned `{"status":"ok"}`; Vite served the login page with HTTP 200. API PID 77320 and Vite PID 46231 are listening on 127.0.0.1:8000 and :5173. | Local health checks and `lsof` listener check, 11 Nov 2026 |
| Deployment hardening | ECS task definition selects production mode. Startup rejects the built-in/short JWT secret, SQLite, unsupported database drivers, wildcard CORS, and non-HTTPS origins. ECS uses managed PostgreSQL/JWT secret references, explicit HTTPS CORS, DB health checks, and OIDC deploy. The Dockerfile now downloads the configured semantic embedding/NLI artifacts into its cache and enables offline inference at runtime; `.dockerignore` excludes environment files. The local Docker daemon is unavailable and AWS CLI is not installed, so image build and cloud deployment remain unverified. No AWS deployment is claimed | `backend/finalsay/config.py`, `backend/finalsay/tests/test_production_config.py`, `Dockerfile`, `.dockerignore`, `aws/ecs-task-definition.json`, `.github/workflows/verify.yml`, `.github/workflows/build-image.yml`, `.github/workflows/deploy-aws-ecs.yml`, `compose.yaml`, deployment guide |

### Multi-instance source-poll coordination

The poll slot uses a process-local mutex for SQLite development and a PostgreSQL
session advisory lock for production. A partial unique index on current
official source keys also prevents duplicate current rows if a writer bypasses
the poll lock. The database lock is held on a dedicated connection for the
full poll, so multiple API tasks do not concurrently upsert the same source
pages. Manual polling returns `503` if coordination cannot be checked and `409`
when another poll already owns the slot. Unit tests cover lock
acquisition/release, contention cleanup, and coordination failures. This is
verified with a mocked PostgreSQL connection in tests; it has not yet been
exercised against a live managed PostgreSQL deployment.

| Automated checks | Full backend suite: 191 passed in the prior verification; this cleanup/refactor turn: 33 focused ingestion, seed-isolation, and cleanup tests passed; `compileall` passed. Frontend production build passed in prior verification | Backend pytest and compileall; Docker image build remains unavailable because the local Docker daemon is unavailable |

## Live ingestion evidence and limitations

The first live startup poll reached all selected sites in about 138 seconds:

- **VTU:** 20 found, 15 created, 4 revised, 1 unchanged; partial because some PDFs had no extractable text and one detail response exceeded the configured size cap.
- **Delhi:** 38 found, 26 created, 12 unchanged; partial because the official catalog links documents on Google Drive. The app respects the file host's robots policy and stores catalog metadata without fetching those files.
- **Mumbai:** 50 found, 50 created; partial because some PDFs had no text layer.

A second poll skipped the 65 repeated latest-page items and added 45 new
historical items (20 Delhi, 25 Mumbai). These were additional backfill URLs,
not duplicates.

Runs 85–87 failed to resolve all three source hosts. Polls 88–90 later
recovered; Delhi timed out again at run 92 and later recovered. Runs 97–99
recorded DNS errors after a sandbox-denied API restart attempt. The API was
then restarted with localhost bind permission and its startup poll completed
as runs 100–102. VTU found 20 notices (10 created, 10 unchanged); Delhi found
38 (17 created, 1 revised, 20 unchanged; eight Drive-hosted attachments remain
metadata-only); Mumbai found 50 (25 created, 25 unchanged). This cycle added
52 current notices and one historical revision. At that point the DB had 923
official versions: 809 current and 114 historical. The suspicious Mumbai upload chain
remains out of current retrieval, with all eight rows preserved as history.
At that point, selected-source counts were VTU 160, Delhi 244, and Mumbai 366. Latest
cursors are VTU page 16, Delhi offset 280, and Mumbai stable circular code
`363236296185` (approximately row 375 of 5,489). The latest successful cycle
reached all three hosts. Subsequent sandboxed startup probes created failed
scrape runs 103–105 because that execution context could not resolve the source
hosts. These probes added or revised no notices. An existing API listener
remained available and returned HTTP 200 readiness; the frontend base route
returned HTTP 200.

After reviewing the API process and restoring its cached-model offline flags,
the live API startup polls completed as runs 106–108 and 109–111. Each cycle
added 55 current notices (10 VTU, 20 Delhi, 25 Mumbai) with no revisions or
duplicates. Runs 109–111 advanced cursors to VTU page 18, Delhi offset 320, and
Mumbai circular code `463668011626`. Current source totals are VTU 180, Delhi
284, and Mumbai 416. The database now contains 1,033 versions: 919 current
and 114 historical. Both cycles recorded expected partial-source conditions:
Delhi's Google Drive attachments remain metadata-only, and Mumbai backfill is
still in progress. Current selected-source notices have no missing publication
dates, duplicate current source keys, or synthetic markers.

After the extraction-coverage monitor was added, the API restarted from this
checkout and completed a scheduled poll in runs 115–117. It added 53
current records (10 VTU, 19 Delhi, 24 Mumbai), created no revisions, and
advanced cursors to VTU page 19, Delhi offset 340, and Mumbai circular code
`683502916675`. The product DB now has 1,086 official-source versions: 972
current and 114 historical. Selected current counts are VTU 190, Delhi 303,
and Mumbai 440. There are still no duplicate current source keys or selected
source publication-date gaps. The three-source poll completed in about five
minutes; VTU succeeded, while Delhi and Mumbai reported partial-source errors.

Version-history inspection found Mumbai circular code `323772810384` had
alternated between full PDF text and short listing fallbacks across four
versions. Those quality fluctuations were not four confirmed official
revisions. A clone replay confirms a listing-only fetch preserves the current
1,561-character extracted version and creates no extra row. The extraction-
quality migration is live. After runs 115–117, current selected-source rows
include 277 marked `extracted`, 114 `listing_only`, and 595 legacy rows
`unknown`, which will be classified as they are safely refetched. The Admin
Sources table now reports this coverage per institution. Run 101 recorded one revised Delhi
version; no duplicate current source keys were created.

The next startup poll completed as runs 118–120. It added 53 current records
(10 VTU, 18 Delhi, 25 Mumbai) and created no revisions. Cursors advanced to
VTU page 20, Delhi offset 360, and Mumbai circular code `926021369782`. The
database now has 1,139 official-source versions: 1,025 current and 114
historical. Current selected-source totals are VTU 200, Delhi 321, and Mumbai
465. Current selected-source records still have no missing publication dates
or duplicate current source keys. The cycle took about five minutes; VTU
succeeded, while Delhi and Mumbai remained partial for their documented
attachment/backfill limits. Latest current-source extraction quality is 277
`extracted`, 114 `listing_only`, and 595 `unknown`.

Read-only in-memory semantic probes against the refreshed current database
retrieved VTU #1313, Delhi #1331, and Mumbai #1356 as their own institution's
top result with cosine 1.0. These probes created no submissions.

An attempted duplicate startup from the restricted execution sandbox later
recorded error-only runs 121–123 when that process could not resolve the
official source hosts. They fetched or changed no notices and did not move
backfill cursors. Separate bounded checks from the permitted host context
resolved all three names and each official page returned HTTP 200. A subsequent
authorized API restart retained the same database and offline-model flags.

The restarted API completed its scheduled source cycle as runs 124–126 in
about 5 minutes 43 seconds. It added 55 current notices (10 VTU, 20 Delhi,
25 Mumbai), created no revisions, and reported 55 unchanged notices. VTU
completed successfully; Delhi remained partial because Drive attachments are
metadata-only, and Mumbai remained partial because backfill continues. Cursors
advanced to VTU page 21, Delhi offset 380, and Mumbai circular code
`192231838748`. The database then had 1,194 official-source versions: 1,080
current and 114 historical.

The source-isolated transaction change was activated in the next API restart.
During runs 127–129, VTU and Delhi each committed their source batches before
the slower Mumbai poll completed. The cycle finished in about 5 minutes 6
seconds with 54 created (10 VTU, 19 Delhi, 25 Mumbai), 55 unchanged, no
revisions, and two expected partial-source errors. Cursors advanced to VTU
page 22, Delhi offset 400, and Mumbai circular code `567151518948`. The
database now has 1,248 official-source versions: 1,134 current and 114
historical. Selected-source current totals are VTU 220, Delhi 360, and Mumbai
515. There are no current-key duplicates or selected-source publication-date
gaps. Extraction quality is 354 `extracted`, 146 `listing_only`, and 595
`unknown`.

Read-only in-memory retrieval against the refreshed database ranked VTU
#1421, Delhi #1440, and Mumbai #1465 first for their respective institution
queries, each at cosine 1.0. No student submission was persisted.

OCR improved the actual VTU notice at
`https://vtu.ac.in/2026/11/41960/` to current notice #494, version 3, with
1,846 extracted characters. Local OCR is capped at two pages per PDF with a
per-page timeout. Scanned notices beyond those pages can still be incomplete.

Backfill remains incomplete. Current successful cursors are VTU page 22, Delhi
offset 400, and Mumbai circular code `567151518948`. The Mumbai cursor uses
the circular's stable code; its old numeric offset migrated during run 102. A
regression test verifies new front-page records do not shift the checkpoint.
At the current 25-row two-hour batch, the remaining Mumbai backfill is still
expected to take about 17 days if polls succeed consistently.
All current selected-source records now have publication dates. The 40 missing
VTU dates were read from persisted official listing text, and the application
content and notice versions were left unchanged. Twenty-six older inactive
Thapar and IIT Bombay records still have no source-listed date. The parser
reads machine-readable `<time datetime>` values and ISO dates for new polls; it
does not infer dates when a source does not provide them.

## Admin manual-poll integration verification

On 10 November, the actual Admin frontend's **Poll configured sources** action
was run against an isolated clone of the product SQLite database. The first
request to `POST /api/ingest/fetch` returned HTTP 200 and ingested VTU 20 found
(10 new, 10 unchanged), Delhi 38 (17 new, 1 revised, 20 unchanged), and
Mumbai 50 (14 new, 25 unchanged). That first Mumbai result carried a
`UnicodeEncodeError` caused by a malformed surrogate in source text.

Unicode normalization was added at the extraction and persistence boundaries.
A second click from the Admin frontend completed with HTTP 200: VTU 20 found
(10 new, 10 unchanged), Delhi 40 (20 new, 20 unchanged), and Mumbai 50
(11 new, 39 unchanged). The second run had no Unicode encoding error. Mumbai
was partial because backfill continues at row 375 of approximately 5,489;
Delhi was partial because eight Google Drive attachments remain outside the
safe host allowlist. After the poll, the clone contained 953 notice versions
and 839 current rows with no duplicate current source keys. The temporary
database and its Admin user were isolated from the main product database.

## Verification commands

```sh
cd backend
.venv/bin/python -m pytest finalsay/tests -q -o addopts=''
.venv/bin/python -m compileall -q finalsay
.venv/bin/python -m finalsay.services.backfill_vtu_publication_dates
cd ../apps/web
npm run build
```

Latest results on 10 November: **194 backend tests passed** (run from
`backend/`; four dependency deprecation warnings), `python -m compileall -q
finalsay` passed, and `npm run build` completed successfully from `apps/web/`.
One captured OCR check fetched an official VTU timetable PDF and
recognized 1,581 characters / 224 words, including examination text.

## Remaining work before launch

1. Continue backfill until each source's `backfill_complete` is true; VTU and Mumbai historical backfills remain active. Successful scheduler cycles use the configured interval; failed cycles now retry with bounded exponential delays from five minutes to one hour.
2. Fix or explicitly accept source-specific extraction limits: Delhi's external file host, PDFs over the 20 MB fetch bound, remaining scanned or malformed PDFs, and 525 current selected-source rows still marked `unknown` until they are safely refetched. Current selected-source publication dates are complete.
3. Bootstrap a real Admin account, provision institution-scoped issuer accounts, curate actual student submission/candidate pairs, and collect annotations from two actual independent reviewers. Synthetic/fixture kappa is not human validation. The ready-to-run steps are in `REAL-USER-VALIDATION.md`.
4. Complete production deployment setup: provision AWS OIDC/IAM roles, managed PostgreSQL, Secrets Manager entries, frontend origin, HTTPS load balancer, backup/restore, and monitoring. No AWS credentials or production host are configured. A Docker image build could not be checked because the local Docker socket is unavailable.
5. If public-chain anchoring is required, configure a dedicated test wallet securely in `backend/.env`, deploy to Amoy, and verify a real successful receipt before claiming on-chain anchoring. No private key has been requested or exposed.

**Current assessment (10 November 2026):** the product database contains 1,879 official notice versions (1,759 current; 120 historical), 65 document-extraction sidecars, and 45 unlabeled real revision pairs. Selected-source current counts are VTU 400, Delhi 380, and Mumbai 940; inactive real Thapar and IIT Bombay sources retain 24 and 15 current records. All 1,720 selected-source current notices have publication dates, and there are no duplicate current source keys. Extraction quality is 971 `extracted`, 223 `listing_only`, 525 `unknown`, and one `unextractable`. Delhi's checkpoint is complete but some linked files return 404; VTU and Mumbai backfills remain incomplete. Latest scheduled VTU/Delhi attempts failed on DNS resolution. There are no product users, student submissions, comparison edges, or reviewer annotations; the 45 benchmark pairs are unlabeled. A read-only semantic probe against current Delhi notice #2071 retrieved notice #1996 first (cosine 0.918). The backend suite passes (194 tests), Python compilation passes, and the frontend production build succeeds. Existing localhost processes remain listening, and browser tabs point at login. Human review, two actual reviewer accounts/annotations, remaining historical ingestion, transient source connectivity, and production deployment remain outstanding. No blockchain deployment or transaction is claimed.

The API was restarted on 10 November 2026 after SQLite backups, preserving the
existing database and two-hour polling interval. The extraction-quality
migration applied successfully; API readiness and frontend checks returned
HTTP 200. Cached embedding/NLI weights load successfully with
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`; the local API uses these flags to
avoid failed Hugging Face DNS lookups. Production still needs model artifacts
present in its image or reliable model-host access.

Runs 145–147 recorded DNS failures. Later direct HTTPS checks returned HTTP 200
for all three configured source URLs, and the next live cycles resumed. A
separate-process test confirmed the SQLite poll lock rejects a concurrent
poller. The latest completed scheduler cycle added 35 current records and four
sidecars, with zero extraction-refresh errors. DNS validation retries temporary
lookup errors up to three times while retaining the host allowlist and public-IP
checks. The current API process completed a startup poll with the change loaded.

An actual-notice workflow was rerun against a temporary clone of the current
product database: a student registered and logged in, submitted the stored text
of University of Delhi notice #518, and semantic retrieval selected current
notice #517. The model returned `unresolved`; review case 1 appeared in the
reviewer queue. Admin curation then created one benchmark pair in the clone,
and two separately authenticated reviewer accounts received the same pair text
with their own labels blank. This verifies student-to-candidate-to-review and
blind-pair access on real scraped records. It does not prove a correct
`SUPERSEDED` classification or human annotation; no reviewer labeled the pair.
The clone and all temporary accounts/submissions were removed. Product DB
counts remain zero for users, student submissions, and annotations; the product
database contains 45 unlabeled benchmark pairs from real source revisions.

After the document-sidecar integration, a fresh isolated copy of the product
database was used for another actual API run. A temporary student account
submitted notice #518; `POST /api/ingest/submit` returned HTTP 200, selected
notice #517, and produced `unresolved` with review case 1. A separately
authenticated temporary reviewer saw that case through `/api/reviewer/queue`
(HTTP 200, one case). The temporary clone was deleted. This verifies the
student-to-classification-to-review-queue integration against scraped notices;
it does not count as a human adjudication or model-quality annotation.

After the VTU date-field backfill, retrieval was also checked directly against
the live product database: an in-memory probe using actual Delhi notice #518
text ranked current revised notice #517 first (combined score 0.400; semantic
similarity 0.912). The probe was not persisted; the product DB still has zero
student submissions. Candidate retrieval reads current official notices from
the database on each request, so metadata-only date updates did not require a
separate embedding-index rebuild.

On 10 November, another isolated API check seeded only the real current
University of Mumbai notice #1644 (a further-revised examination timetable).
A temporary student registered and logged in, then submitted a proposed
further revision through `POST /api/ingest/submit` (HTTP 200). Semantic
retrieval selected notice #1644 and the local NLI model returned `superseded`
at 0.990 confidence. In a second check, a low-match student submission became
`unresolved` with an open review case visible to a separately authenticated
reviewer through `/api/reviewer/queue` (HTTP 200). The temporary databases and
accounts were deleted; the product DB still has no users or student
submissions. A different test against real VTU notice #1836 returned
`contradictory` for a rescheduling scenario, so the `SUPERSEDED` result is
evidence for this tested pair, not a guarantee for all revisions. Human
annotations are still required to assess classification quality.
