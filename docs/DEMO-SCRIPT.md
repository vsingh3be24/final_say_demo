# FinalSay — verified local demo (8 minutes)

This script matches the current local semantic-model configuration and database
snapshot (2 November 2026). It avoids older mock-model predictions and does not
present generated benchmark annotations as human labels.

## Open the running application

- Frontend: <http://127.0.0.1:5173/FinalSay-prototype/>
- API docs: <http://127.0.0.1:8000/docs>
- Backend readiness: <http://127.0.0.1:8000/api/health/ready>

The localhost services are running in this workspace. If starting a clean
checkout instead, follow [`integrated-demo-guide.md`](integrated-demo-guide.md).
The normal local SQLite database currently has 251 notices and must be retained
for the saved IDs below.

## Demo accounts

| Role | Login | Password |
|---|---|---|
| Student | `student@finalsay.demo` | `student123` |
| Issuer | `issuer@finalsay.demo` | `issuer123` |
| Reviewer A | `reviewer@finalsay.demo` | `reviewer123` |
| Reviewer B | `reviewer2@finalsay.demo` | `reviewer2-demo` |
| Admin | `admin@finalsay.demo` | `admin123` |

These are local synthetic accounts. The issuer has a Thapar publishing grant.
Do not use these defaults in a production deployment.

## 1. Show official notice publishing (1 minute)

Sign in as issuer and open **Publish official notice**. The seeded test record is
official notice **#189**, Thapar Institute of Engineering and Technology,
“Revised Schedule for End-Semester Examinations,” dated 01 November 2026. Its
body states that odd-semester end-semester exams commence on 15 December 2026.

The record is synthetic and its `example.test` source URL is a placeholder; it
is not evidence of an actual Thapar announcement. For API publishing, follow the
shell request in [`integrated-demo-guide.md`](integrated-demo-guide.md).
Identical content is deduplicated by the publishing pipeline.

## 2. Show a superseded notice (1.5 minutes)

Sign in as student, open **Submit notice**, select Thapar, and submit:

> Revised Schedule for End-Semester Examinations. The End-Semester
> Examinations for the odd semester have been postponed from 15 December 2026
> and will now commence on 20 December 2026 instead.

The verified run is submission **#245**. It retrieved official notice #189 at
rank 1 and returned `SUPERSEDED` (raw score 0.999, uncalibrated). The matched
claim pair and date evidence are visible in the result. This is a controlled
demo case, not a measurement of model accuracy.

## 3. Show a consistent notice (1 minute)

Submit the official wording unchanged, including the date and exam statement.
The verified repeat is submission **#248**. It retrieved #189 at rank 1 and
returned `CONSISTENT` (raw score 0.974, uncalibrated). The result shows matching
claim text and matching 15 December dates, without replacement-language
evidence.

## 4. Show a contradictory notice and corrected extraction (1 minute)

Submission **#251** retrieved #189 at rank 1 and returned `CONTRADICTORY`
(raw score 0.997, uncalibrated) because it says 20 December while the official
notice says 15 December. The UI correctly shows no issuer extracted from this
body-only submission. This check also covers the issuer-extraction correction;
earlier pre-restart submission #250 still contains the old fallback value.

## 5. Show the unresolved/reviewer flow (1.5 minutes)

As student, submit this low-information text for Thapar:

> There is confusion about a campus circular; timing and venue details are not
> entirely clear. Could someone clarify which schedule applies?

The saved example **#246** returned `UNRESOLVED` with no suitable official
candidate. Reviewer case **#42** was opened, then a reviewer confirmed the
unresolved label and closed it through the reviewer UI. To demonstrate the flow
live again, submit a fresh ambiguous variation and resolve its new case from
**Queue → Open → Resolve case**. Choosing `unresolved` confirms the model label;
no candidate should be invented when evidence is absent.

## 6. Show blind reviewer benchmarking (1 minute)

Sign in as Reviewer A and Reviewer B in separate browser profiles. Both see the
same benchmark texts, each sees only their own saved labels, and labels are not
preselected. Kappa and pair-level agreement remain hidden until both reviewers
label every pair and submit their pass. Submission locks that reviewer's labels.
The local corpus uses generated example texts, so this walk-through demonstrates
the blind workflow only; it is not a human agreement result until two people
independently annotate approved study examples.

## 7. Show source management (1 minute)

Sign in as admin and open **Sources**. Thapar and IIT Bombay are enabled and
NIT Jalandhar is paused after a connection reset. Recent actual runs found 23
Thapar notices (6 modified, 17 unchanged, partial due to one stale PDF 404) and
10 IIT Bombay notices (8 modified, 2 unchanged, partial because an old PDF had
no extractable text). These are recorded scrape results; they do not prove full
site coverage. Source pages publish actual notices and their links are listed in
the integrated demo guide.

## 8. Show integrity and the current boundary (1 minute)

On result #251, use **Verify integrity**. It returned a matching content hash and
Merkle proof against local root #8. The UI's **Simulate tamper** control on
result #248 returned an integrity failure; it simulates a changed hash and does
not mutate the saved notice. Root #8 covers 62 notices created on 2 November
2026.

The configured anchor is `local`. The optional Polygon Amoy contract adapter
and Solidity contract exist, but this environment has no funded test wallet or
deployed contract address, so **no on-chain transaction or receipt exists**.
Do not describe the local hash chain as a blockchain anchor.

## Evaluation caveat

The current semantic evaluation is a small generated-fixture diagnostic. Its
validation / temporal / institution-holdout macro-F1 scores are 0.810 / 0.295 /
0.686. The seeded 0.625 kappa comes from deterministic generated annotations,
not independent human annotators. `chronological` and `page_change` are simple
baselines; the `nli` and `prompted_llm` entries are heuristic baselines, not
independent services. Use [`FINAL-PROJECT-REPORT.md`](FINAL-PROJECT-REPORT.md)
and [`phase1-ml-evaluation.md`](phase1-ml-evaluation.md) for the full caveats,
metrics, and remaining limitations.
