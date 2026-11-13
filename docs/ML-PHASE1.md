# FinalSay Phase 1: semantic comparison

## Model and workflow

The configured application default is now `semantic`. It composes two local,
open model checkpoints:

- `sentence-transformers/all-MiniLM-L6-v2` embeds official notices and the
  submission. Official embeddings are cached in process memory by content hash.
  The existing same-institution filter remains; semantic and lexical ranks are
  fused to select candidate notices without a vector database.
- `cross-encoder/nli-deberta-v3-small` scores the most relevant substantive
  sentence pair as entailment, contradiction, or neutral. The neutral outcome,
  a weak sentence match, a missing candidate, or an insufficient score yields
  `unresolved` and creates the existing reviewer case.

Sentence-level comparison removes generic headers and footers before NLI so
that boilerplate does not overwhelm the instruction being checked. Explicit
date replacement language plus conflicting dates maps a contradiction to
`superseded`. A date conflict without replacement language stays
`contradictory`. The existing `corrected`, `extended`, and `cancelled` labels
remain accepted by the database and UI; the semantic model may emit them when
its NLI result is contradictory and the notice text supports the subtype.

The NLI scores are model ranking evidence, not calibrated probabilities. The
API returns the score and the rationale says so. `FINALSAY_CONFIDENCE_THRESHOLD`
and `FINALSAY_SEMANTIC_CANDIDATE_THRESHOLD` are configurable.

## Threshold selection and evaluation

Reproduce with:

```bash
cd backend
HF_HUB_OFFLINE=1 .venv/bin/python -m finalsay.eval.semantic_benchmark \
  --report ../docs/phase1-ml-evaluation.md
```

Threshold selection uses 30 early generated examples from Northgate and
Riverside. Summit is excluded. The candidate cosine floor was selected for
maximum retrieval recall subject to at least 0.50 precision on the designated
gold candidate. The NLI score floor was chosen by macro-F1 on the same
non-held-out validation examples. Resulting defaults: candidate cosine `0.55`,
NLI score floor `0.20`.

The temporal evaluation contains 21 later generated examples. The institution
evaluation contains 21 Summit examples and was not used for either threshold.
It is not a trained-model split: no fine-tuning is done. The 65 gold examples
and 308 seeded benchmark pairs are generated fixtures, not independently
collected institutional notices. A fixture audit corrected mismatched event
dates, registration deadlines, and venue text on 2 November 2026; the current
metrics are regenerated in [`phase1-ml-evaluation.md`](phase1-ml-evaluation.md).
The seeded Cohen's kappa `0.625` describes generated demo labels, not an
independent human annotation study.

Measured semantic pipeline results (seven stored labels, macro metrics):

| Split | N | Accuracy | Macro precision | Macro recall | Macro F1 | Unresolved | Candidate recall@1 | Median warm latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Validation | 30 | 0.867 | 0.786 | 0.857 | 0.810 | 0.133 | 0.533 | 48.1 ms |
| Temporal | 21 | 0.429 | 0.250 | 0.429 | 0.295 | 0.286 | 0.476 | 46.5 ms |
| Summit holdout | 21 | 0.714 | 0.732 | 0.714 | 0.686 | 0.190 | 0.429 | 44.8 ms |

False-confirmation rate was `0.000` on both test splits in this run. Temporal
macro F1 remains much lower than validation, and extended/corrected/cancelled
naturalistic examples remain difficult. The synthetic samples are small and do
not show generalization to real institutions. See
[`phase1-ml-evaluation.md`](phase1-ml-evaluation.md) for class-wise F1 and
confusion matrices.

## Local setup

`make demo` and `make install` install `backend/requirements-ml.txt` in
addition to the ordinary backend dependencies. The first run downloads model
weights from Hugging Face (about 650 MB combined) and caches them locally.
Subsequent runs can use `HF_HUB_OFFLINE=1`. Set
`FINALSAY_COMPARISON_MODEL=mock` to choose the deterministic rule model.

No database migration is required. Classification remains stored in the
existing `relation_edge` table; the API response now includes matched notice
details and comparison evidence.
