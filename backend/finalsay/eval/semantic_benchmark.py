"""Evaluate the local semantic pipeline without touching the institution holdout.

Threshold selection uses only early (temporal_bucket=0) Northgate/Riverside
examples. Temporal and institution holdouts are evaluated only after those
thresholds are fixed. This is a small generated fixture set, not a real-world
benchmark, so results must be interpreted as prototype diagnostics.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from finalsay.config import get_settings
from finalsay.eval import baselines
from finalsay.models import RELATIONSHIP_LABELS
from finalsay.models_iface.comparison_model import MockComparisonModel
from finalsay.models_iface.semantic_model import SemanticComparisonModel
from finalsay.seed import dataset
from finalsay.seed.seed import load_gold_submissions


def _fixtures() -> tuple[list[dict], dict[str, dict]]:
    root = Path(__file__).resolve().parents[1] / "seed" / "fixtures"
    officials: dict[str, dict] = {}
    for institution in dataset.INSTITUTIONS:
        path = root / f"{institution['slug']}_official.json"
        if path.exists():
            officials.update(
                {record["external_id"]: record for record in json.loads(path.read_text())}
            )
    return load_gold_submissions(), officials


def _as_notice(record: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=record["external_id"],
        issuer=(record.get("text", "").splitlines() or [""])[0],
        action=record.get("gold_action"),
        redacted_text=record.get("text", ""),
        sha256=record["external_id"],
    )


def _predict(model: SemanticComparisonModel, gold: list[dict], officials: dict[str, dict]):
    rows = []
    for example in gold:
        institution_officials = [
            _as_notice(record)
            for record in officials.values()
            if record["external_id"].startswith(example["institution_slug"] + "-")
        ]
        submission = SimpleNamespace(
            issuer="", action=None, redacted_text=example["text"]
        )
        start = time.perf_counter()
        ranked = model.rank_candidates(submission, institution_officials)
        candidate, rank_score, similarity = ranked[0] if ranked else (None, 0.0, 0.0)
        if candidate is None:
            label, score = "unresolved", 0.0
        else:
            # Measure real NLI execution per example, not a reused memoized score
            # from another fixture with identical sentences.
            model._pair_score_cache.clear()
            label, score, _rationale, _evidence = model.classify_with_evidence(
                model._notice_text(candidate), example["text"]
            )
        latency_ms = (time.perf_counter() - start) * 1000
        rows.append(
            {
                "example": example,
                "label": label,
                "score": score,
                "latency_ms": latency_ms,
                "candidate_id": candidate.id if candidate else None,
                "candidate_rank_score": rank_score,
                "candidate_similarity": similarity,
            }
        )
    return rows


def _accepted(row: dict, candidate_threshold: float, confidence_threshold: float) -> str:
    if row["candidate_similarity"] < candidate_threshold:
        return "unresolved"
    if row["score"] < confidence_threshold:
        return "unresolved"
    return row["label"]


def _select_thresholds(rows: list[dict]) -> tuple[float, float, dict]:
    """Choose retrieval cutoff at >=0.50 precision; maximize recall there.

    Then select the NLI score floor that maximizes validation macro-F1. Both
    choices exclude the held-out institution and temporal holdout bucket.
    """
    retrieval_candidates = []
    for threshold in [i / 100 for i in range(20, 81, 5)]:
        accepted = [r for r in rows if r["candidate_similarity"] >= threshold]
        true_positive = sum(
            r["candidate_id"] == r["example"]["official_external_id"]
            for r in accepted
        )
        precision = true_positive / len(accepted) if accepted else 0.0
        recall = true_positive / len(rows) if rows else 0.0
        if precision >= 0.50:
            retrieval_candidates.append((recall, -threshold, precision, threshold))
    if retrieval_candidates:
        _recall, _tie, retrieval_precision, candidate_threshold = max(retrieval_candidates)
    else:
        candidate_threshold, retrieval_precision = 1.0, 0.0

    labels = [row["example"]["gold_label"] for row in rows]
    score_candidates = []
    for threshold in [i / 100 for i in range(20, 96, 5)]:
        predicted = [_accepted(r, candidate_threshold, threshold) for r in rows]
        macro_f1 = f1_score(
            labels, predicted, labels=RELATIONSHIP_LABELS,
            average="macro", zero_division=0,
        )
        score_candidates.append((float(macro_f1), -threshold, threshold))
    _f1, _tie, confidence_threshold = max(score_candidates)
    return candidate_threshold, confidence_threshold, {
        "validation_pairs": len(rows),
        "retrieval_precision_at_selected_threshold": retrieval_precision,
        "validation_macro_f1": max(score_candidates)[0],
        "validation_institutions": sorted({r["example"]["institution_slug"] for r in rows}),
    }


def _metrics(rows: list[dict], candidate_threshold: float, confidence_threshold: float):
    gold = [row["example"]["gold_label"] for row in rows]
    predicted = [_accepted(row, candidate_threshold, confidence_threshold) for row in rows]
    precision, recall, per_class_f1, _ = precision_recall_fscore_support(
        gold, predicted, labels=RELATIONSHIP_LABELS, zero_division=0
    )
    true_consistent = sum(
        label == "consistent" and expected == "consistent"
        for expected, label in zip(gold, predicted)
    )
    false_confirmation = sum(
        label == "consistent" and expected != "consistent"
        for expected, label in zip(gold, predicted)
    ) / len(gold) if gold else 0.0
    return {
        "count": len(rows),
        "accuracy": float(accuracy_score(gold, predicted)) if gold else 0.0,
        "macro_precision": float(sum(precision) / len(precision)) if gold else 0.0,
        "macro_recall": float(sum(recall) / len(recall)) if gold else 0.0,
        "macro_f1": float(sum(per_class_f1) / len(per_class_f1)) if gold else 0.0,
        "per_class_f1": {label: float(value) for label, value in zip(RELATIONSHIP_LABELS, per_class_f1)},
        "confusion_matrix": confusion_matrix(gold, predicted, labels=RELATIONSHIP_LABELS).tolist(),
        "false_confirmation_rate": false_confirmation,
        "unresolved_rate": sum(label == "unresolved" for label in predicted) / len(predicted) if predicted else 0.0,
        "candidate_recall_at_1": sum(
            row["candidate_id"] == row["example"]["official_external_id"]
            and row["candidate_similarity"] >= candidate_threshold
            for row in rows
        ) / len(rows) if rows else 0.0,
        "candidate_coverage": sum(row["candidate_similarity"] >= candidate_threshold for row in rows) / len(rows) if rows else 0.0,
        "median_latency_ms": statistics.median(row["latency_ms"] for row in rows) if rows else 0.0,
        "labels": {"gold": gold, "predicted": predicted},
    }


def _baseline_metrics(rows: list[dict], officials: dict[str, dict], predictor):
    gold, predicted = [], []
    for row in rows:
        example = row["example"]
        official = officials.get(example["official_external_id"], {})
        gold.append(example["gold_label"])
        predicted.append(
            predictor(baselines.build_sample(example["text"], official.get("text", "")))
        )
    return {
        "accuracy": float(accuracy_score(gold, predicted)) if gold else 0.0,
        "macro_f1": float(f1_score(gold, predicted, labels=RELATIONSHIP_LABELS, average="macro", zero_division=0)) if gold else 0.0,
        "unresolved_rate": sum(label == "unresolved" for label in predicted) / len(predicted) if predicted else 0.0,
    }


def evaluate() -> dict:
    gold, officials = _fixtures()
    model = SemanticComparisonModel()
    rows = _predict(model, gold, officials)
    validation = [
        row for row in rows
        if row["example"].get("temporal_bucket") == 0
        and row["example"]["institution_slug"] != dataset.HELD_OUT_SLUG
    ]
    candidate_threshold, confidence_threshold, selection = _select_thresholds(validation)
    temporal = [row for row in rows if row["example"].get("temporal_bucket") == 1]
    institution = [row for row in rows if row["example"]["institution_slug"] == dataset.HELD_OUT_SLUG]
    results = {
        "model": model.name,
        "candidate_threshold": candidate_threshold,
        "confidence_threshold": confidence_threshold,
        "threshold_selection": selection,
        "validation": _metrics(validation, candidate_threshold, confidence_threshold),
        "temporal": _metrics(temporal, candidate_threshold, confidence_threshold),
        "institution": _metrics(institution, candidate_threshold, confidence_threshold),
        "two_annotator_kappa": __import__("finalsay.eval.harness", fromlist=["benchmark_kappa"]).benchmark_kappa(),
        "baselines": {},
    }
    for split_name, split_rows in (("temporal", temporal), ("institution", institution)):
        results["baselines"][split_name] = {
            "mock": _baseline_metrics(
                split_rows, officials,
                lambda sample: _mock_predict(sample),
            ),
            **{
                name: _baseline_metrics(split_rows, officials, predictor)
                for name, predictor in baselines.BASELINES.items()
            },
        }
    return results


def _mock_predict(sample: dict) -> str:
    label, score, _ = MockComparisonModel().classify(sample["off_text"], sample["sub_text"])
    return label if score >= get_settings().confidence_threshold else "unresolved"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", help="Optional Markdown output path")
    args = parser.parse_args(argv)
    results = evaluate()
    printable = {key: value for key, value in results.items()}
    print(json.dumps(printable, indent=2))
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Semantic model validation and holdout results\n\n```json\n" + json.dumps(printable, indent=2) + "\n```\n")
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
