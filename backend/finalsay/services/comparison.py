"""Comparison (module 4, design.md section 7).

- Candidate retrieval: filter official notices by institution/audience when
  known, rank by token overlap, take top-K (K=5).
- ``classify_submission``: run the configured ComparisonModel against the best
  candidate, apply confidence gating (below ``FINALSAY_CONFIDENCE_THRESHOLD`` ->
  label forced to 'unresolved' and a ``review_case`` created), then persist a
  ``relation_edge`` with label, confidence, rationale, model name and status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.config import get_settings
from finalsay.models import Notice, NoticeDocumentExtraction, RelationEdge, ReviewCase
from finalsay.models_iface.comparison_model import ComparisonModel, get_comparison_model

TOP_K = 5
_REVISION_TITLE_RE = re.compile(
    r"\b(?:revised|revision|corrigendum|correction|corrected|amended|amendment|updated|update)\b",
    re.IGNORECASE,
)


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _submission_text(notice: Notice) -> str:
    parts = [
        notice.issuer or "",
        notice.action or "",
        notice.redacted_text or "",
        getattr(notice, "supplemental_extracted_text", "") or "",
    ]
    return "\n".join(p for p in parts if p)


def _explicit_revision_title_match(submission: Notice, official: Notice) -> bool:
    """Prefer a portal's clearly marked revision over its original same-topic notice."""
    submission_title = submission.title or ""
    official_title = official.title or ""
    submission_base = _REVISION_TITLE_RE.sub(" ", submission_title)
    official_base = _REVISION_TITLE_RE.sub(" ", official_title)
    def normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    return bool(
        normalize(submission_title)
        and _REVISION_TITLE_RE.search(official_title)
        and not _REVISION_TITLE_RE.search(submission_title)
        and normalize(submission_base)
        and normalize(submission_base) == normalize(official_base)
    )


def _revision_first(submission: Notice, candidates: list[Candidate]) -> list[Candidate]:
    """Keep explicit same-topic revisions ahead of an exact old-copy match."""
    return sorted(
        candidates,
        key=lambda item: (
            _explicit_revision_title_match(submission, item.notice),
            item.score,
        ),
        reverse=True,
    )


@dataclass
class Candidate:
    notice: Notice
    score: float
    semantic_similarity: float | None = None


def retrieve_candidates(
    db: Session, submission: Notice, top_k: int = TOP_K,
    model: ComparisonModel | None = None,
) -> list[Candidate]:
    """Return top-K relevant official notices using semantic or lexical ranking."""
    query = select(Notice).where(
        Notice.kind == "official",
        Notice.is_current.is_(True),
        Notice.id != submission.id,
    )
    if submission.institution_id is not None:
        query = query.where(Notice.institution_id == submission.institution_id)

    officials = db.scalars(query).all()

    if officials:
        supplement_query = (
            select(
                NoticeDocumentExtraction.notice_id,
                NoticeDocumentExtraction.extracted_text,
            )
            .join(Notice, Notice.id == NoticeDocumentExtraction.notice_id)
            .where(Notice.kind == "official", Notice.is_current.is_(True))
        )
        if submission.institution_id is not None:
            supplement_query = supplement_query.where(
                Notice.institution_id == submission.institution_id
            )
        supplements: dict[int, list[str]] = {}
        for notice_id, text in db.execute(supplement_query):
            supplements.setdefault(notice_id, []).append(text)
        for official in officials:
            official.supplemental_extracted_text = "\n".join(
                supplements.get(official.id, [])
            )

    model = model or get_comparison_model()
    semantic_ranker = getattr(model, "rank_candidates", None)
    if semantic_ranker is not None:
        ranked = semantic_ranker(submission, officials)
        minimum = get_settings().semantic_candidate_threshold
        candidates = [
            Candidate(notice=notice, score=rank_score, semantic_similarity=similarity)
            for notice, rank_score, similarity in ranked
            if similarity >= minimum
        ]
        return _revision_first(submission, candidates)[:top_k]

    sub_tokens = _tokens(_submission_text(submission))
    aud_tokens = _tokens(submission.audience)

    scored: list[Candidate] = []
    for official in officials:
        score = _overlap(sub_tokens, _tokens(_submission_text(official)))
        if aud_tokens and _tokens(official.audience) & aud_tokens:
            score += 0.1  # small boost for matching audience
        scored.append(Candidate(notice=official, score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    return _revision_first(submission, scored)[:top_k]


@dataclass
class ComparisonOutcome:
    edge: RelationEdge
    candidate: Notice | None
    label: str
    confidence: float
    rationale: str
    gated: bool
    review_case: ReviewCase | None
    evidence: list[str]
    candidate_score: float | None


def classify_submission(
    db: Session,
    submission: Notice,
    model: ComparisonModel | None = None,
    threshold: float | None = None,
) -> ComparisonOutcome:
    """Classify a submission against its best candidate and persist the edge.

    Applies confidence gating (GC-4): when confidence is below the threshold the
    label is forced to 'unresolved' and a review_case is created. The relation
    edge is always persisted with label, confidence, rationale, model and status.
    """
    settings = get_settings()
    model = model or get_comparison_model()
    threshold = settings.confidence_threshold if threshold is None else threshold

    evidence: list[str] = []
    try:
        candidates = retrieve_candidates(db, submission, model=model)
    except Exception as exc:  # model unavailable: preserve API flow as unresolved
        from finalsay.models_iface.semantic_model import SemanticModelUnavailable

        if not isinstance(exc, SemanticModelUnavailable):
            raise
        candidates = []
        evidence.append(str(exc))
    best = candidates[0].notice if candidates else None
    best_score = candidates[0].score if candidates else None
    if candidates and candidates[0].semantic_similarity is not None:
        evidence.append(
            "Candidate retrieval: combined embedding/lexical rank "
            f"{candidates[0].score:.3f}; embedding cosine "
            f"{candidates[0].semantic_similarity:.3f}."
        )

    if best is None:
        # No sufficiently relevant official notice -> route to reviewer.
        label, confidence, rationale = (
            "unresolved",
            0.0,
            "No sufficiently relevant official notice was available for comparison.",
        )
        if evidence:
            rationale = f"Semantic comparison unavailable: {evidence[0]}"
        gated = True
    else:
        premise = _submission_text(best)
        hypothesis = _submission_text(submission)
        detailed = getattr(model, "classify_with_evidence", None)
        if detailed is not None:
            label, confidence, rationale, model_evidence = detailed(premise, hypothesis)
            evidence.extend(model_evidence)
        else:
            label, confidence, rationale = model.classify(premise, hypothesis)
            evidence.append(rationale)
        # Confidence gating (GC-4): never force a guess below the threshold.
        gated = confidence < threshold or label == "unresolved"
        if label == "unresolved":
            rationale = (
                f"{rationale} The model did not support a resolved relationship; "
                "routed to reviewer."
            )
            label = "unresolved"
        elif confidence < threshold:
            rationale = (
                f"{rationale} Confidence {confidence:.2f} is below the "
                f"threshold {threshold:.2f}; routed to reviewer."
            )
            label = "unresolved"

    status = "unresolved" if label == "unresolved" else "auto"
    edge = RelationEdge(
        src_notice_id=submission.id,
        dst_notice_id=best.id if best is not None else submission.id,
        label=label,
        confidence=confidence,
        rationale=rationale,
        model=model.name,
        status=status,
    )
    db.add(edge)
    db.flush()

    review_case: ReviewCase | None = None
    if label == "unresolved":
        review_case = ReviewCase(
            edge_id=edge.id,
            status="open",
            assigned_role="reviewer",
        )
        db.add(review_case)
        db.flush()

    return ComparisonOutcome(
        edge=edge,
        candidate=best,
        label=label,
        confidence=confidence,
        rationale=rationale,
        gated=gated,
        review_case=review_case,
        evidence=evidence,
        candidate_score=best_score,
    )
