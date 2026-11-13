# Real-user and reviewer validation

This runbook uses the product SQLite database and real notices from VTU,
University of Delhi Examination, or University of Mumbai. Do not use the demo
seed command or generated labels; they are not human validation data.

## 1. Provision privileged accounts

The current product database has no users. From `backend/`, bootstrap the
first Admin with an email address owned by the operator:

```sh
.venv/bin/python -m finalsay.services.provision_admin ADMIN_EMAIL
```

The command asks for the password twice using hidden terminal input. Use a
unique password of at least 16 characters. Do not put it in shell history or
send it in chat.

After the Admin account exists, create one account for each of two different
people using distinct email addresses:

```sh
.venv/bin/python -m finalsay.seed.create_reviewer REVIEWER_A_EMAIL
.venv/bin/python -m finalsay.seed.create_reviewer REVIEWER_B_EMAIL
```

Each reviewer password is also entered through hidden terminal prompts. Do not
share accounts or discuss labels while the review is open.

## 2. Create a real student comparison

Open `http://127.0.0.1:5173/FinalSay-prototype/register`, register a student,
then sign in. From **Submit**, choose the correct institution and submit the
real forwarded or revised notice. Save the returned submission ID and result.
The comparison is persisted against the current official notice candidates;
low-confidence or unresolved results create a reviewer case.

## 3. Curate the blind benchmark

The current product database already contains 45 unlabeled pairs built from
actual adjacent official notice versions. They are marked **Official revision**
in the reviewer queue; no synthetic student submission or model prediction is
used. To preview new source-version pairs after backfill continues, run from
`backend/`:

```sh
.venv/bin/python -m finalsay.services.curate_revision_benchmark
```

After reviewing the eligible count and before reviewers begin, apply idempotently
with:

```sh
.venv/bin/python -m finalsay.services.curate_revision_benchmark --apply
```

The command snapshots only real linked source versions with text and does not
assign labels. Adding pairs after reviewers start changes the shared corpus, so
freeze the corpus before either reviewer completes their pass.

Sign in as Admin and open
`http://127.0.0.1:5173/FinalSay-prototype/admin/sources`. In **Blind reviewer
benchmark**, add eligible real submission/current-notice pairs. The candidate
list omits model labels, confidence, and rationale. Curate the corpus before
reviewers begin because adding pairs changes the shared corpus fingerprint.

## 4. Collect independent annotations

Each reviewer signs in separately and opens
`http://127.0.0.1:5173/FinalSay-prototype/reviewer/benchmark`. Each labels every
pair independently, then selects **Complete review**. Reviewers see only their
own labels and progress. Cohen's Kappa remains hidden until two accounts have
completed the same corpus; it is then computed from those authenticated
annotations.

For a student result routed to review, a reviewer can also use the queue at
`http://127.0.0.1:5173/FinalSay-prototype/reviewer/queue` and resolve the open
case. Record the submission, edge, and review-case IDs with the test evidence.

## Current prerequisite

The application and real source data are running locally. The product DB has
45 official revision benchmark pairs but no users, student submissions, human
annotations, or review cases. Admin/reviewer email identities are still needed;
a real student submission is needed to validate the student workflow. Passwords
must be typed into the local hidden prompts, not supplied here.
