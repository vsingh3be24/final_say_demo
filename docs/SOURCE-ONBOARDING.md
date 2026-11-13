# Official notice source onboarding

FinalSay supports one-step, repeatable onboarding for the selected portals:

- VTU examination notices
- University of Delhi Examination notifications
- University of Mumbai circulars

## Configure sources

From the repository root:

~~~sh
cd backend
.venv/bin/python -m finalsay.services.source_onboarding
.venv/bin/python -m finalsay.services.source_onboarding --apply
~~~

The first command previews the changes. The second creates or updates those
three institution rows and enables polling. It does not create notice records
or remove old notice history. Re-running it is safe.

## Polling and manual refresh

The FastAPI process polls enabled live sources every two hours by default
(FINALSAY_SCRAPE_INTERVAL_SECONDS, default 7200). A poll writes created or
revised notices through the regular extraction/versioning path and records a
ScrapeRun row for each source. Repeated polls use stable source URLs and
content hashes to avoid duplicate current records; a partial unique database
index now enforces the current official source-key invariant while preserving
historical versions. Scheduled cycles commit each source's records, run audit,
cursor, and provenance independently, so a later slow or failed source does
not roll back completed source batches. The interval can be changed in the
backend environment.

An admin can also open /admin/sources and select **Fetch notices now**. The
same operation is available at POST /api/ingest/fetch with an admin bearer
token. The API schema restricts each adapter to its institution host; the
scraper follows only bounded same-site pagination and does not fetch
third-party-hosted attachments.

## Verified local state (10 November 2026)

The latest completed scheduled cycle is runs 142–144. It added 35 current
notices (10 VTU, 0 Delhi, 25 Mumbai) with no revisions. The database now has
1,404 official-source versions: 1,290 current and 114 historical.
Selected-source current counts are VTU 260, Delhi 376, and Mumbai 615; inactive
Thapar and IIT Bombay account for the remaining 39 current records. There are
zero duplicate current source keys or missing selected-source publication
dates. Current quality counts are VTU 141 `extracted`, 2 `listing_only`, 117
`unknown`; Delhi 11 `extracted`, 159 `listing_only`, 206 `unknown`; and Mumbai
352 `extracted`, 0 `listing_only`, 263 `unknown`.

The current backfill cursors are VTU page 26, Delhi complete, and Mumbai
circular code `977328034612`. A focused adapter test exposed a Delhi pagination
bug that could select a previous-page link and rewind the cursor. The fix
ignores same-kind numeric links at or behind the current page; the restarted
API poll advanced Delhi from offset 380 to 400, and the next bounded live poll
marked its backfill complete. The scheduler's extraction refresh stored six
separately hashed sidecars; with the validated manual batch, nine sidecars now
feed candidate retrieval without changing notice hashes or versions. VTU and
Mumbai backfill continue. Runs 132–134
are error-only records from an isolated sandbox startup that lacked source DNS;
they added or revised no notices. The live product API and frontend both return
HTTP 200.

## Legacy document extraction refresh

Each scheduled cycle now retries up to two current `unknown` documents per
configured source after the source poll. Successful redacted text is stored in
`notice_document_extraction` with a SHA-256 hash, then included in semantic
candidate retrieval and NLI comparison. It does not rewrite the immutable
notice text/hash or create a notice version. The current database has 9 such
sidecars; integration tests confirm matching notice hashes and versions remain
unchanged. External hosts such as Delhi's Google Drive links are skipped.

For an operator-run bounded refresh, default mode is read-only:

```sh
cd backend
.venv/bin/python -m finalsay.services.document_extraction_backfill --limit-per-institution 1
```

Add `--apply` to store the verified redacted sidecars and update extraction
quality metadata. `--limit-per-institution` defaults to 2.

An attempted duplicate startup from the restricted execution sandbox created
error-only runs 121–123: that process could not resolve any source host before
fetching records. These attempts created or revised no notices and did not
advance backfill cursors. Separate bounded connectivity checks from the
permitted host context resolved all three names and each official page returned
HTTP 200. The existing API and frontend also returned HTTP 200. Later
authorized restarts loaded the scraper-default hardening and source-isolated
scheduled commits; the latest poll completed in runs 127–129.

Runs 85–87 recorded DNS failures, followed by successful polling in runs
88–90; Delhi timed out again at run 92 and later recovered. Runs 97–99 and
103–105 recorded sandbox DNS failures and changed no notice rows. After
reviewing the process and restarting the API from this checkout with its
cached-model offline flags, live source polls succeeded in runs 106–108,
109–111, and 115–117. API readiness and frontend base route return HTTP 200.
The API uses the existing database and continues two-hour scheduled polling.
DNS behavior still needs verification in the actual deployment runtime.

The Admin frontend's **Poll configured sources** action was also exercised on
10 November against an isolated copy of the product database. The first UI
poll completed through `POST /api/ingest/fetch` (HTTP 200): VTU found 20
(10 new, 10 unchanged), Delhi found 38 (17 new, 1 revised, 20 unchanged), and
Mumbai found 50 (14 new, 25 unchanged) before a malformed Unicode surrogate
caused the Mumbai run to end partial. After normalizing malformed Unicode in
the extraction and persistence paths, a second poll from the same Admin UI
completed (HTTP 200): VTU found 20 (10 new, 10 unchanged), Delhi found 40
(20 new, 20 unchanged), and Mumbai found 50 (11 new, 39 unchanged). The
second Mumbai run was partial only because backfill remains in progress; the
Unicode error did not recur. The Delhi run remained partial because eight
Google Drive attachments are outside the approved fetch-host allowlist. The
clone reached 953 notice versions / 839 current rows with zero duplicate
current source keys. This UI verification used a temporary database and Admin
account; it did not change the product database.

Backfill is **in progress**, not complete: latest successful cursors are VTU
page 22, Delhi offset 400, and Mumbai circular code `567151518948`. Each poll checks
the current feed and advances one bounded
historical batch. Mumbai now stores the last processed circular code rather
than a row offset, so new items inserted at the front cannot shift its
checkpoint. The old numeric cursor migrated during run 102. At the 25-row
two-hour batch, the remaining Mumbai backfill is still expected to take about
17 days if polls succeed consistently. A full
three-source cycle takes about five minutes when source hosts respond.

All current rows from the three selected sources now have publication dates.
The 40 previously blank dates on current VTU rows were recovered from the date
at the start of each persisted `Official listing:` field. The source text was
already stored, so no date was inferred from an exam event or fetched from a
different source. The one-time, repeatable dry-run/apply command is
`python -m finalsay.services.backfill_vtu_publication_dates`; the script only
updates current official VTU notices with blank dates. The parser continues to
read machine-readable `<time datetime>` values and ISO dates on future polls.
Older inactive Thapar/IIT Bombay records still have 26 missing dates in total.

## Current limitations

The University of Delhi page links some attachments through Google Drive. For
those entries, FinalSay indexes the official listing title, date, and link, but
does not download the third-party file. A broken PDF also falls back to listing
metadata and is recorded as a partial scrape. Mumbai PDF circulars are parsed
as before; JPG/JPEG/PNG scans now use bounded OCR. Executable suffixes and
filename-like suspicious titles are skipped instead of indexed as notice
metadata. Persisted extraction quality distinguishes extracted documents,
listing-only fallbacks, and unknown legacy rows. A direct-download probe on
two publicly linked Delhi files redirected to `drive.usercontent.google.com`;
both advertised files over the scraper's 20-MB response cap. Google's published
robots policy disallows `/uc` downloads on `drive.google.com` and all paths on
`drive.usercontent.google.com`, so FinalSay preserves listing metadata and
does not fetch those files. Among current selected-source notices, 695 are
classified as extracted, 207 as listing-only, 558 as unknown and one as
unextractable. The Admin Sources table reports extraction counts per
institution as polling continues.

The 20-MB PDF cap still excludes at least one VTU attachment. OCR supports at
most two pages per PDF with a per-page timeout, so some longer scans remain
incomplete. Delhi's Drive-hosted documents remain metadata-only. The actual
VTU schedule at #41960 is current record #494, version 3, with 1,846 OCR
characters. Duplicate `#respond` comment links are normalized and there are
no duplicate current source keys.

An authenticated student API test used historic #292 and current #494
versions of the same VTU notice from a temporary clone of the real database.
Before the title integration fix, #494 ranked 17th behind unrelated exam
timetables. Student submissions now store their `Subject:`/`Title:` heading;
exact title agreement raised #494 to rank 1 with candidate score 0.924 and
cosine 0.862. `POST /api/ingest/submit` returned HTTP 200 and classified the
sparse historic text as `consistent` at 0.971 confidence. The clone was
removed; the product database still has zero student submissions and accounts.
This verifies API-to-retrieval integration, but does not prove that a genuine
revision pair will be classified `superseded`.

A second API integration check used actual University of Delhi records #518
(original) and #517 (revised) from an isolated copy of the live DB. The student
submission retrieved #517; the semantic model conservatively returned
`unresolved`, opened a review case, and the reviewer queue returned that case.
The API model weights are available in the local Hugging Face cache; the local
server uses offline mode flags to avoid DNS retry loops. This validates the
handoff path but still requires a reviewer to adjudicate the real pair.

## Live source state on 10 November 2026

The product database currently contains 1,500 current and 114 historical
official notice versions, plus 37 hashed document-extraction sidecars. The
latest completed live source cycle added 10 VTU and 25 Mumbai notices, and the
refresh stored four more sidecars. Delhi's backfill is complete; VTU is at page
32 and Mumbai is at circular code `882132412997`.
The database also has 45 unlabeled blind-review pairs generated from actual
adjacent official source versions; there are still no reviewer accounts or
human annotations.
Runs 145–147 recorded transient source-host DNS failures; direct HTTPS checks
later returned HTTP 200 for each configured source and polling resumed. A
separate-process test verifies SQLite poll serialization. DNS validation retries
temporary lookup errors up to three times without relaxing host allowlists or
public-IP checks. The focused live-adapter test passes, and the latest startup
poll completed without DNS resolution errors.
