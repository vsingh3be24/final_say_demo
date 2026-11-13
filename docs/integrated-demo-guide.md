# FinalSay integrated demo guide

## Local services

The current development servers use:

- Frontend: <http://127.0.0.1:5173/FinalSay-prototype/>
- API and Swagger: <http://127.0.0.1:8000/docs>
- Readiness probe: <http://127.0.0.1:8000/api/health/ready>

The API defaults to the local SQLite file at `backend/finalsay.db`. Source
configuration, fetched notices, and scrape history are retained in that file.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Student | `student@finalsay.demo` | `student123` |
| Reviewer A | `reviewer@finalsay.demo` | `reviewer123` |
| Reviewer B | `reviewer2@finalsay.demo` | `reviewer2-demo` |
| Admin | `admin@finalsay.demo` | `admin123` |
| Issuer | `issuer@finalsay.demo` | `issuer123` |

These are local synthetic accounts seeded through the normal password-hash and
JWT flow. Public self-registration creates students only; it cannot grant an
issuer or admin role.

Reviewer A and B are separate local demo accounts for exercising blind
annotation. Do not share these demo credentials for an academic study; create
individual accounts for the actual reviewers.

## Grant issuer access

Sign in as the admin and open **Admin → Sources → Issuer publishing grants**.
Grant `issuer@finalsay.demo` permission for Thapar. Issuer publication is
limited to explicitly granted, active institutions; public registration still
creates student accounts only.

## Publish an official notice as issuer

Sign in as `issuer@finalsay.demo`, choose **Issuer → Publish**, select Thapar,
and paste the notice. Equivalent JSON API request:

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=issuer@finalsay.demo' \
  --data-urlencode 'password=issuer123' | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -sS -X POST http://127.0.0.1:8000/api/issuer/publish \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "institution_id": 4,
    "text": "Issued by: Thapar Institute of Engineering and Technology\nSubject: Revised Schedule for End-Semester Examinations\nDate: 01 November 2026\nThe End-Semester Examinations for the odd semester will commence from 15 December 2026.",
    "source_url": "https://example.test/thapar/notices/revised-end-semester-examinations-2026-11-01"
  }'
```

The test notice is stored as current official notice **189** and is retrievable
for Thapar student comparisons. Its `example.test` source URL is intentionally a
placeholder, so it is not evidence that this notice was published by Thapar.
Publishing through the API extracts fields and calculates its content hash. An
identical notice reuses its current row instead of adding a duplicate.

## Scrape sources

Sign in as the admin and open **Admin → Sources**. Select a scraper, enter its
official listing URL, and choose **Poll configured sources**. Active, enabled
sources are also polled once at backend startup and every six hours by default;
set `FINALSAY_SCRAPE_INTERVAL_SECONDS` to change that interval or `0` to turn
automatic polling off. Manual and scheduled polls cannot overlap. Transient
HTTP failures receive at most two retries, honoring a numeric `Retry-After`
header up to five seconds. The source page shows the latest successful poll,
new/revised/unchanged counts, recent errors, an active/polling toggle, and a link
to browse notices for that institution.

Official sources configured in this local DB:

- Thapar Dean Academics notice board:
  <https://www.thapar.edu/students/pages/dean-academics-notice-board>
- IIT Bombay Academic Office circulars:
  <https://acad.iitb.ac.in/circulars>
- NIT Jalandhar academic notices feed:
  <https://www.nitj.ac.in/api/academicnotices/get/all> (paused after its host
  reset the live connection during the validation run)

Observed live extraction and persistence: the latest recorded Thapar poll
found 23 notices, left 23 unchanged, and recorded one stale PDF 404 as a
partial run. The latest IIT Bombay poll found 5 notices, left all 5 unchanged,
and recorded two PDFs with no extractable text. The latest combined manual UI
poll reported 28 unchanged and 2 source errors. Earlier source revisions remain
linked as separate notice versions. NIT Jalandhar's last poll failed with a
connection reset and its source is paused. These are actual local scrape-run
records, not claims that every item on each website was captured. See the
[Phase 2 scraping report](PHASE2-SCRAPING-REPORT.md) for cumulative database
counts and verification details.

## Student comparison flow

Sign in as the student and open **Submit notice**. Select Thapar and submit:

> The End-Semester Examinations for the odd semester have been postponed from
> 15 December 2026 and will now commence on 20 December 2026 instead.

The local UI run for the 20 December statement retrieved official notice 189
at rank 1 and returned `SUPERSEDED` with raw NLI score 0.9992. That score is
model evidence, not a calibrated probability. The result includes the matched
official/student claim pair, parsed dates, source link, and candidate rank
evidence. The run is stored as #245; an earlier equivalent run is #244. A
separate ambiguous submission (#246) returned `UNRESOLVED`; reviewer case #42
was confirmed as unresolved and closed through the reviewer UI. A repeat of
the exact official wording, submission #248, returned `CONSISTENT`, retrieved
#189 at rank 1, and displayed raw score 0.974 without replacement-language
evidence.

Submission #251 says the exams commence on 20 December 2026. It retrieved #189
at rank 1 and returned `CONTRADICTORY` (raw score 0.997, uncalibrated). Since
the submitted body does not identify an issuer, the corrected extraction path
shows issuer `—` at confidence 0.00. Earlier submission #250 was made before the
backend restart and retains the previous fallback value.

For an ambiguous case, the confidence gate creates a reviewer case. Sign in as
the reviewer to review and resolve it; case #42 is now closed with label
`unresolved`. A reviewer does not publish official notices.

## Blind reviewer annotation and Cohen's kappa

The benchmark page shows the same pair texts to both reviewers but returns
only the signed-in reviewer's own saved label. Labels are not preselected.
Reviewers can revise their own labels until they submit a complete pass; then
those labels are locked. The API does not reveal another reviewer's labels,
progress, or aggregate agreement during collection. Cohen's kappa remains
unavailable until two distinct reviewer accounts have labeled and submitted
the entire same benchmark corpus. The calculation uses account-bound human
annotations only; generated fixture labels are excluded.

The local seed provides Reviewer A and Reviewer B for functional testing. For
real annotators, provision two individual reviewer accounts in the local
database (run from `backend`; the command prompts for the password twice and
stores only its password hash):

```bash
.venv/bin/python -m finalsay.seed.create_reviewer reviewer-one@example.edu --display-name "Reviewer One"
.venv/bin/python -m finalsay.seed.create_reviewer reviewer-two@example.edu --display-name "Reviewer Two"
```

Give each person their own credentials through a private channel. Use two
separate browser profiles, sign into **Reviewer → Benchmark**, label every pair
independently, and select **Submit completed blind pass**. The second submitted
pass unlocks the measured kappa. The current 308 pair corpus uses generated
example texts, so real approved notice examples should be added before making
claims about agreement on actual student forwards or institutional notices.

## Provenance / Polygon Amoy

Local mode is active and records an append-only hash chain. The Polygon Amoy
integration is implemented but has **not** submitted a transaction: there is
no funded test wallet or deployed contract address in this workspace. No
transaction evidence is claimed.

To create or refresh local integrity proofs, sign in as admin and open
**Admin → Provenance**. Choose the notice creation date in UTC and click **Build
selected date’s root**. Rebuilding an unchanged tree reuses its anchor; if new
notices were added for that date, their Merkle proofs are refreshed. The local
proof verifies stored content consistency and is not an external blockchain
receipt. The current local database has 251 Merkle proofs; refreshed root #8
for 2026-11-02 covers 62 notices, including submissions #244–#251. Student UI
verification of #251 matched its content hash and Merkle proof; the earlier
tamper simulation on #248 returned a failed integrity result.

To enable it, deploy [`../contracts/FinalSayAnchor.sol`](../contracts/FinalSayAnchor.sol)
to Polygon Amoy and set the following in a private local `backend/.env` file:

```dotenv
FINALSAY_ANCHOR=polygon
FINALSAY_POLYGON_RPC_URL=https://polygon-amoy.drpc.org
FINALSAY_POLYGON_PRIVATE_KEY=<test-only funded wallet key>
FINALSAY_POLYGON_CONTRACT=<deployed contract address>
FINALSAY_POLYGON_CHAIN_ID=80002
FINALSAY_POLYGON_RECEIPT_TIMEOUT=45
```

Deployment checklist:

1. Use a dedicated test-only wallet on Polygon Amoy (chain ID `80002`), not a
   production wallet. The contract owner is the deploying address, and the
   configured private key must belong to that same address because
   `anchorRoot` is owner-only.
2. Obtain Amoy test POL for deployment and anchor gas. Polygon's support faucet
   may require a request that is reviewed; no wallet funding is present in this
   checkout.
3. In [Remix](https://remix.ethereum.org), create a Solidity file from
   `FinalSayAnchor.sol`, compile with a Solidity `0.8.24` compatible compiler,
   select the injected wallet provider on Amoy, and deploy the contract. Approve
   the deployment in the wallet and copy the resulting contract address.
4. Put the RPC URL, test-only private key, deployed address, `FINALSAY_ANCHOR`,
   and chain ID in `backend/.env`. `.env` is ignored by Git. Never paste the
   private key into chat or commit it.
5. Restart the backend and use **Admin → Provenance** to build a date root. A
   successful row must say `confirmed` and include chain ID `80002`, a block
   number, and a transaction hash. Then use **Verify integrity**; the verifier
   reads the root mapping from the configured contract.

The contract stores only the Merkle root, opaque batch and issuer-set hashes,
publisher address, and timestamp.
FinalSay records transaction
hash, chain, block, and confirmation status in SQLite. A transaction without a
receipt is reported pending; a reverted transaction is failed; an error before
broadcast is clearly recorded as local fallback. On-chain verification queries
the configured contract mapping.

Polygon's current RPC reference still lists Amoy (chain ID 80002, gas token
POL) and currently points to dRPC. Polygon announced the retirement of its
old `rpc-amoy.polygon.technology` endpoint in July 2026, so do not use that
legacy URL. The dRPC public endpoint can be rate-limited; a managed provider is
also supported by the configuration. See the [current Polygon RPC reference](https://docs.polygon.technology/pos/reference/rpc-endpoints)
and [Amoy endpoint deprecation notice](https://forum.polygon.technology/t/deprecation-of-polygons-public-rpc-endpoints-mainnet-amoy/22014). Test POL availability is described in [Polygon's faucet instructions](https://support.polygon.technology/support/solutions/articles/82000906072-how-can-i-get-test-tokens-).

## Local start commands

From the repository root, if the persistent dev processes are stopped:

```bash
cd backend
FINALSAY_COMPARISON_MODEL=semantic .venv/bin/uvicorn finalsay.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd apps/web
npm run dev -- --host 127.0.0.1 --port 5173
```

For a new checkout, install `backend/requirements.txt` and
`backend/requirements-ml.txt`, run `python -m finalsay.seed.seed`, and run
`npm install` in `apps/web` before starting the two servers.
