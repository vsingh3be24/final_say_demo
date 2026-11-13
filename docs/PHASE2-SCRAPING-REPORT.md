# Phase 2 — Live institutional notice ingestion

**Status checked:** 3 November 2026, local development database and services.

## Outcome

Two real institutional notice sources are configured and have produced
persisted records. Admins can poll them from **Admin → Sources** or rely on the
backend startup/six-hour scheduler. Repeated runs reuse unchanged notices and
keep previous versions when source content changes. Scraped current official
notices are included in the existing same-institution semantic candidate
retrieval path.

The most recent manual UI poll completed with **0 new, 0 revised, 28 unchanged,
and 2 source errors**. The errors are retained in scrape history and extracted
records remain available. This is a partial run, not a claim that every item
on either site was collected.

## Sources and adapters

| Institution | Official source | Adapter | Current database state |
|---|---|---|---|
| Thapar Institute of Engineering and Technology | [Dean Academics Notice Board](https://www.thapar.edu/students/pages/dean-academics-notice-board) | `thapar_html`: listing HTML, linked PDF downloads, extracted title/text/date | Active and polling enabled; 50 stored official versions, 24 current |
| Indian Institute of Technology Bombay | [Academic Office Circulars](https://acad.iitb.ac.in/circulars) | `iitb_html`: circular listing HTML and linked PDF downloads | Active and polling enabled; 23 stored official versions, 15 current |
| Dr B R Ambedkar National Institute of Technology Jalandhar | [Academic notices feed](https://www.nitj.ac.in/api/academicnotices/get/all) | `nitj_api`: JSON feed and linked PDFs | Adapter is present, but polling is disabled after the live host reset the connection; 0 notices stored |

The Thapar and IIT Bombay pages are official institutional domains and expose
public notice/circular listings with HTML links to PDF notices. The scraper
fetches and caches each site's `robots.txt`, checks requested paths, and does
not bypass authentication or access controls. The checked public listing and
notice paths are allowed by the two sources' published directives. NITJ's
robots endpoint redirected to its homepage rather than returning directives;
its feed is paused after the observed connection reset.

The source-specific parsers and shared HTTP safeguards live in
[`backend/finalsay/adapters/live.py`](../backend/finalsay/adapters/live.py).
Saved listing fixtures are in
[`backend/finalsay/tests/fixtures`](../backend/finalsay/tests/fixtures).

## Persisted scrape evidence

The local SQLite database contains 289 notices overall, including synthetic
fixture data. The two live sources account for **73 official version rows**:
50 Thapar and 23 IIT Bombay. Of those, 39 are current (24 and 15 respectively).
Publication dates were extracted and stored for 23 live rows (20 Thapar and 3
IIT Bombay).

Across recorded runs for the two working sources, database counters show 257
source-item observations: 38 new, 34 revised, and 185 unchanged encounters.
These are cumulative run counters, so unchanged encounters count again on
later polls; they are not unique notice totals. The latest recorded Thapar run
found 23 items, created/revised none, and left 23 unchanged; it was partial
because one linked PDF returned HTTP 404. The latest IIT Bombay run found 5
items, left all 5 unchanged, and was partial because two linked PDFs contained
no extractable text. NITJ's recorded attempt failed with `Connection reset by
peer`; the source remains paused.

Version history is preserved in the notice table using `version_no`,
`previous_version_id`, and `is_current`. The ingestion service identifies a
source notice by its stable source key, compares content hashes, and creates a
new version when the content changes. Repeated unchanged content reuses its
current row. Retrieval timestamps, source URLs, extracted publication dates,
and SHA-256 content hashes are stored with notices.

## ML retrieval integration

The current retrieval service filters to current official notices for the
submission's institution, then ranks them with the configured semantic model.
There is no separate manual indexing step required for a persisted notice.

An end-to-end local smoke submission (#289, institution 4) retrieved scraped
Thapar notice #288 as its top candidate. The API candidate result recorded a
combined score of 1.0 and embedding cosine of 0.689945. The persisted relation
edge points from #289 to #288 and is `unresolved`; this report claims successful
candidate retrieval, not a resolved classification. The official notice has a
source URL and publication date in the database.

## Admin controls, safety, and scheduling

The existing Admin → Sources page uses live API data to list sources, active
and polling state, latest successful poll counts, recent errors, and a
**Browse notices** link. Admins can add/configure a source, enable or disable
it, and trigger a manual poll. Fixture sources are not included in manual or
scheduled polling results.

The scheduler starts with the API and runs every six hours by default. Set
`FINALSAY_SCRAPE_INTERVAL_SECONDS=0` to disable it. Manual and scheduled polls
share a process lock. Requests use HTTPS, official-host allowlists, public-IP
DNS checks, robots checks, same-host redirects, bounded timeouts and response
sizes, per-host spacing, and at most three total attempts for retryable
transport/429/5xx failures. Retry delays honor numeric `Retry-After` values up
to five seconds and otherwise use capped backoff. Run outcomes and errors are
stored in `scrape_run`.

## Verification

- Backend: `(cd backend && .venv/bin/pytest finalsay/tests -q)` — **108 passed**.
  Coverage includes saved listing fixtures, extraction, PDF handling,
  idempotency, version history, failure handling, scheduler locking, manual
  polling, and semantic candidate retrieval.
- Frontend: `(cd apps/web && npm run build)` — TypeScript and Vite build passed.
- Admin UI: localhost Sources page showed the current real-source poll summary,
  23 Thapar items, 5 IIT Bombay items, and their two partial-run errors.
- Runtime: frontend opens from <http://localhost:5173> and routes under
  `/FinalSay-prototype/`; backend readiness returns `{"status":"ok"}` at
  <http://localhost:8000/api/health/ready>; API documentation is at
  <http://localhost:8000/docs>.

## Limitations

- Scrapers are source-specific and may miss changes when institutional page
  structure changes.
- Some linked PDFs are stale or image-only/unextractable; OCR availability is
  not assumed. Such failures are surfaced in the scrape run instead of being
  represented as extracted notices.
- NITJ is configured but not currently a successful source; its feed returned
  a connection reset during validation.
- Publication dates are saved only when a page or extracted PDF text provides a
  recognized date label; they are not inferred from retrieval time.
- Scraping is best-effort public notice discovery, not a completeness guarantee
  or an institutional authenticity endorsement.
