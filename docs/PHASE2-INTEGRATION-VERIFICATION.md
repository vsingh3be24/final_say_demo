# Phase 2 Integration Verification

**Date:** 3 November 2026  
**Scope:** Read-only integration checks plus live scrape polls. Phase 3 was not started.

## Results

1. **Official records and semantic retrieval — partial.** The database contains 289 notices overall. There are 39 current official notices for Thapar and IIT Bombay, but one is synthetic notice #189 (`example.test`). That leaves **38 current records from the configured official sources**: 23 Thapar and 15 IIT Bombay. All 38 are present in the database. A fresh semantic sweep could not be completed: initializing the embedding model tried to contact Hugging Face and failed DNS resolution. An earlier retrieval check included all 39 rows, including #189, so it does not prove a complete sweep of the 38 real scraped rows.

2. **Student submission against a scraped notice — verified.** Existing student submission #289 belongs to `student@finalsay.demo`. The saved comparison edge points to current scraped Thapar notice #288 (source PDF `Minor in CSE (2025).pdf`), using `semantic-nli-deberta-v3-small`; it is `unresolved` at 0.826 model confidence and routed for review. The live result page for `/result/289` displays that official match. The unresolved label is the model result; it is not a superseded classification.

3. **Modified version and retrieval refresh — verified on a disposable database copy.** Using an actual scraped source record and submission #289, the real upsert path created version 4 linked to its prior version and ranked it first for the submission. The copy was discarded. Production data was not revised; notice #288 remains current and no #290 exists in the application database.

4. **Dates and PDF extraction — gaps found.** Of 38 real current scraped rows, 13 have a publication date and 25 do not (Thapar 10/23; IIT Bombay 3/15). Listing sources often provide no explicit issue date; the parser deliberately avoids treating examination/event dates as publication dates. IIT Bombay's two current Autumn 2026 PDFs were stored with title/header text only because no body text could be extracted: `Autumn_Sem_2026_27_Registration_Circular.pdf` and `APS-Circular-2026-Autumn.pdf`. An older room-booking PDF is also title-only. Thapar's stale `Auxiliary Examinations August 2025.pdf` URL returned HTTP 404.

5. **Manual Admin scraping — verified in the actual UI.** Clicking **Poll configured sources** produced runs #19 and #20. The UI reported Thapar: 23 found, 23 unchanged, with one HTTP 404; IIT Bombay: 5 found, 5 unchanged, with the two PDF extraction errors above.

6. **Scheduled scraping and error logs — verified with a limitation.** One actual invocation of the scheduled scrape loop produced runs #21 and #22: 23 and 5 notices found, all unchanged, with the same per-source errors persisted. A later app-start poll attempt recorded runs #23 and #24 as errors because this verification process could not resolve the public source hosts. The configured scheduler interval is six hours. The direct scheduled-loop invocation verifies the loop and logging path; it does not independently prove that a future timer tick ran in the already-open server process.

7. **Repeated polling / duplicates — verified.** Across the manual and direct scheduled polls, the successful source runs reported zero new and zero revised notices. The application notice count stayed at 289. No duplicate current `(institution, source_key)` pairs were found. Runs #23/#24 added error audit entries only.

8. **Tests and app — verified.** Full backend pytest suite passed. `npm run build` passed (TypeScript plus Vite production build). The frontend at `http://localhost:5173/FinalSay-prototype/` and API health endpoint at `http://127.0.0.1:8000/api/health/ready` responded successfully.

## Remaining limitations

- The requested **39 actual scraped** current notices do not exist in the database: #189 is synthetic, leaving 38 real current scraped records.
- The complete semantic retrieval sweep over those 38 was not independently confirmed in this pass because model initialization requires unavailable Hugging Face access. The existing #289 comparison and the disposable version-refresh check are positive integration evidence, but do not substitute for that full sweep.
- Publication-date coverage and the listed source/PDF failures require source-side metadata/content fixes. No ML model changes were made.

## Test commands

- `backend/.venv/bin/pytest -q` — passed.
- `cd apps/web && npm run build` — passed.
