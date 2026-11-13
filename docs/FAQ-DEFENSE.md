# FinalSay — project defense FAQ

Use this FAQ with [`FINAL-PROJECT-REPORT.md`](FINAL-PROJECT-REPORT.md) and
[`phase1-ml-evaluation.md`](phase1-ml-evaluation.md). The report is the source of
truth for the current local build. Do not reuse metrics or claims from the
historical files `RESULTS-SUMMARY.md` and `eval-results.md`.

### 1. Where is the ML?

Candidate retrieval uses a local sentence-embedding model with a lexical tie
signal. The top candidate is compared with student text using a local DeBERTa
NLI cross-encoder. The system exposes the matching claim pair and date evidence,
and sends insufficient evidence to the reviewer queue. Raw model rankings are
not calibrated probabilities.

### 2. How well does it perform?

On this small, generated fixture set, macro-F1 was 0.810 on the 30-pair
validation set, 0.295 on the 21-pair temporal holdout, and 0.686 on the 21-pair
held-out institution. These are prototype diagnostics, not estimates of
real-world student-forward accuracy. Candidate recall@1 on those splits was
0.533, 0.476, and 0.429 respectively. The temporal result is weak and should be
reported as such.

### 3. Were there two human annotators?

No. The 0.625 Cohen's kappa is computed from deterministic seed annotations,
not independent human judgments. The reviewer interface supports account-bound
human annotations, and `python -m finalsay.seed.create_reviewer EMAIL` provisions
additional reviewer-only accounts locally. Human labels from at least two
independent reviewers must still be collected before claiming measured
inter-annotator agreement.

### 4. Are the baselines independent ML systems?

`chronological` and `page_change` are simple algorithmic baselines. The entries
named `nli` and `prompted_llm` in the fixture evaluator are heuristic cue
baselines, not calls to independent NLI or hosted LLM services. The evaluation
report names this limitation.

### 5. Are scraped notices official and complete?

The enabled live adapters use official Thapar and IIT Bombay academic pages;
those pages contain actual notices and PDF links. The latest recorded polls
were partial: Thapar found 23 records (6 modified, 17 unchanged, one stale PDF
404); IIT Bombay found 10 (8 modified, 2 unchanged, one old PDF without
extractable text). NIT Jalandhar is paused after its endpoint reset the
connection. This demonstrates real fetch and persistence paths, not complete
coverage or institutional authentication of every fetched file.

### 6. Is the notice provenance on Polygon?

No. The current local environment uses a local hash chain and Merkle proofs.
The Solidity contract and Polygon Amoy adapter exist, and outage, pending,
reverted, and local-fallback behavior are tested with controlled responses, but
there is no funded test wallet, deployed contract address, transaction hash, or
confirmed receipt in this database. A successful Polygon claim requires an
actual testnet transaction and an independent lookup.

### 7. Is this ready to make institutional decisions?

No. It is a local research prototype. It needs real, independently annotated
evaluation data, better temporal holdout performance, broader source coverage,
production secrets and operations, and real external anchoring before it could
support institutional decisions. A displayed classification is comparison
evidence and should be reviewed against the original issuing source.

### 8. What does the current end-to-end test show?

The local UI retrieved official Thapar test notice #189 for a later-date
submission and classified #245 as `superseded`; exact matching content in #248
was classified `consistent`; and #251 with a conflicting date was classified
`contradictory`. The corrected extractor left issuer missing for body-only text.
Ambiguous submission #246 returned `unresolved`, was reviewed, and its case was
closed with that label. These controlled records show the integrated workflow;
they are not performance metrics. The official record itself is synthetic and
its `example.test` URL is a placeholder.
