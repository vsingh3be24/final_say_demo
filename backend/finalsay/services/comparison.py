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
_UPDATE_TITLE_RE = re.compile(
    r"\b(?:revised|revision|corrigendum|correction|corrected|amended|amendment|"
    r"updated|update|extended|extension|postponed|postponement|rescheduled|"
    r"cancelled|canceled|superseded)\b",
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
        notice.title or "",
        notice.issuer or "",
        notice.action or "",
        notice.redacted_text or "",
        getattr(notice, "supplemental_extracted_text", "") or "",
    ]
    return "\n".join(p for p in parts if p)


_TITLE_TOPIC_STOPWORDS = {
    "a", "an", "and", "as", "by", "date", "dated", "examination", "exam",
    "extended", "extension", "filling", "for", "form", "from", "in", "is",
    "last", "notice", "notification", "of", "on", "or", "reg", "regarding",
    "subject", "student", "students", "the", "to", "up", "upto", "with",
}


def _title_topic_similarity(left: str | None, right: str | None) -> float:
    """Measure shared, discriminative title terms without generic notice words."""
    left_tokens = {
        token for token in re.findall(r"[a-z0-9]+", (left or "").casefold())
        if len(token) > 1 and token not in _TITLE_TOPIC_STOPWORDS
    }
    right_tokens = {
        token for token in re.findall(r"[a-z0-9]+", (right or "").casefold())
        if len(token) > 1 and token not in _TITLE_TOPIC_STOPWORDS
    }
    if not left_tokens or not right_tokens:
        return 0.0
    # Overlap coefficient tolerates a concise portal title matching a longer
    # subject heading while still penalizing unrelated audiences or semesters.
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _has_listing_only_evidence(notice: Notice) -> bool:
    """Return true when a match has no underlying source document text."""
    if getattr(notice, "supplemental_extracted_text", ""):
        return False
    if notice.extraction_quality in {"listing_only", "unextractable"}:
        return True
    return bool(
        notice.extraction_quality == "unknown"
        and re.search(r"^\s*official listing\s*:", notice.redacted_text or "", re.IGNORECASE | re.MULTILINE)
    )


def _dated_schedule_facts(notice: Notice) -> dict[str, set[tuple[int, int, int | None]]]:
    """Extract dates attached to comparable schedule/deadline statements.

    Publication and reference dates are intentionally ignored. This is a
    conservative integration guard for the dangerous case where the semantic
    model selects a shared scope sentence and misses conflicting dates in the
    actual schedule rows.
    """
    from finalsay.models_iface.semantic_model import _date_values

    facts: dict[str, set[tuple[int, int, int | None]]] = {}
    text = "\n".join(
        part
        for part in (
            notice.title,
            notice.action,
            notice.redacted_text or "",
            # A source PDF may be attached to a sparse portal listing. Include
            # those separately extracted pages in the safety check as well as
            # in semantic classification.
            getattr(notice, "supplemental_extracted_text", "") or "",
        )
        if part
    )
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    metadata_line = re.compile(
        r"^(?:published(?:\s+date)?|publication\s+date|ref(?:erence)?\s*(?:no|number)\b|dated\b|date\s*:)",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if not line:
            continue
        if metadata_line.match(line):
            continue
        # PDF table extraction and OCR commonly put the row label on one line
        # and its value on the next. Inspect a narrow adjacent-line window,
        # while retaining line boundaries so dotted dates remain parseable.
        context = " ".join(
            adjacent
            for adjacent in lines[max(0, index - 1): min(len(lines), index + 2)]
            if adjacent and not metadata_line.match(adjacent)
        )
        lowered = context.casefold()
        if re.search(r"\b(?:last date|deadline|due date|extended|extension|late fee)\b", lowered):
            key = "deadline"
        elif re.search(r"\b(?:commence|commencing|begins?|starts?|scheduled|will be held|take place)\b", lowered):
            key = "event"
        else:
            continue
        dates = _date_values(context)
        if dates:
            facts.setdefault(key, set()).update(dates)
    return facts


def _schedule_date_conflicts(
    left: Notice, right: Notice
) -> dict[str, tuple[set[tuple[int, int, int | None]], set[tuple[int, int, int | None]]]]:
    """Return category-specific schedule dates when both notices disagree."""
    left_facts = _dated_schedule_facts(left)
    right_facts = _dated_schedule_facts(right)
    return {
        key: (left_facts[key], right_facts[key])
        for key in left_facts.keys() & right_facts.keys()
        if left_facts[key] != right_facts[key]
    }


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
    """Prefer an explicit same-topic update to an older original notice.

    Portal titles often say "extended" or "postponed" instead of "revised".
    Such a notice should be considered before the original when its subject is
    demonstrably the same. A revision cue alone is not enough: the title-topic
    overlap prevents unrelated updates from jumping ahead of a stronger match.
    """

    def update_match(item: Candidate) -> bool:
        title_similarity = item.title_similarity or _title_topic_similarity(
            submission.title, item.notice.title
        )
        return bool(
            title_similarity >= 0.45
            and _UPDATE_TITLE_RE.search(item.notice.title or "")
        )

    def publication_order(item: Candidate) -> int:
        published_on = item.notice.published_on
        return published_on.toordinal() if published_on is not None else 0

    return sorted(
        candidates,
        key=lambda item: (
            _explicit_revision_title_match(submission, item.notice),
            update_match(item),
            publication_order(item),
            item.score,
        ),
        reverse=True,
    )


@dataclass
class Candidate:
    notice: Notice
    score: float
    semantic_similarity: float | None = None
    title_similarity: float = 0.0


def retrieve_candidates(
    db: Session, submission: Notice, top_k: int = TOP_K,
    model: ComparisonModel | None = None,
) -> list[Candidate]:
    """Return top-K relevant official notices using semantic or lexical ranking."""
    if not submission.title and submission.redacted_text:
        # Older student submissions may predate the OCR-safe wrapped-subject
        # parser; recover the title from their already-redacted stored text.
        from finalsay.services.ingestion import _extract_title

        submission.title = _extract_title(submission.redacted_text)

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
        try:
            ranked = semantic_ranker(submission, officials)
        except Exception as exc:  # offline model weights: preserve retrieval via lexical fallback
            from finalsay.models_iface.semantic_model import SemanticModelUnavailable

            if not isinstance(exc, SemanticModelUnavailable):
                raise
            ranked = None
        if ranked is not None:
            minimum = get_settings().semantic_candidate_threshold
            title_scores = {
                notice.id: _title_topic_similarity(submission.title, notice.title)
                for notice, _rank_score, _similarity in ranked
            }
            strong_title_matches = any(score >= 0.45 for score in title_scores.values())
            candidates = []
            for notice, rank_score, similarity in ranked:
                title_similarity = title_scores[notice.id]
                if similarity < minimum and title_similarity < 0.45:
                    continue
                if strong_title_matches and title_similarity < 0.25:
                    continue
                # Let an informative subject/title rescue a listing-only official
                # record whose sparse text gives it a weak embedding score.
                score = (
                    0.45 * rank_score + 0.55 * title_similarity
                    if title_similarity > 0
                    else rank_score
                )
                candidates.append(
                    Candidate(
                        notice=notice,
                        score=score,
                        semantic_similarity=similarity,
                        title_similarity=title_similarity,
                    )
                )
            return _revision_first(submission, candidates)[:top_k]

    sub_tokens = _tokens(_submission_text(submission))
    aud_tokens = _tokens(submission.audience)

    scored: list[Candidate] = []
    for official in officials:
        score = _overlap(sub_tokens, _tokens(_submission_text(official)))
        title_similarity = _title_topic_similarity(submission.title, official.title)
        score = 0.45 * score + 0.55 * title_similarity if title_similarity > 0 else score
        if aud_tokens and _tokens(official.audience) & aud_tokens:
            score += 0.1  # small boost for matching audience
        scored.append(
            Candidate(notice=official, score=score, title_similarity=title_similarity)
        )

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
    elif candidates:
        evidence.append(
            "Candidate retrieval: lexical/title fallback; semantic model ranking was unavailable."
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
        try:
            if detailed is not None:
                label, confidence, rationale, model_evidence = detailed(premise, hypothesis)
                evidence.extend(model_evidence)
            else:
                label, confidence, rationale = model.classify(premise, hypothesis)
                evidence.append(rationale)
        except Exception as exc:  # model weights unavailable: return reviewable result, not 500
            from finalsay.models_iface.semantic_model import SemanticModelUnavailable

            if not isinstance(exc, SemanticModelUnavailable):
                raise
            label, confidence, rationale = (
                "unresolved",
                0.0,
                "A likely official notice was found, but the local comparison model "
                "could not be loaded. Routed to reviewer without asserting a label.",
            )
            evidence.append(str(exc))
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

        schedule_conflicts = _schedule_date_conflicts(best, submission)
        if label == "consistent" and schedule_conflicts:
            rationale = (
                "The model found the notices semantically similar, but their "
                "schedule or deadline dates conflict. Routed to reviewer instead "
                "of asserting that both notices are consistent."
            )
            for category, (official_dates, submitted_dates) in sorted(schedule_conflicts.items()):
                evidence.append(
                    f"Date safety check ({category}): official notice contains "
                    f"{sorted(official_dates)}; submitted notice contains "
                    f"{sorted(submitted_dates)}."
                )
            label = "unresolved"
            gated = True

        if _has_listing_only_evidence(best):
            evidence.append(
                "The likely official match is available only as a portal listing; its source document text was not retrieved."
            )
            if label != "unresolved":
                rationale = (
                    "The closest same-topic official notice is only a portal listing, so "
                    "the relationship cannot be verified from the original document. "
                    "Routed to reviewer instead of applying the model's provisional label."
                )
                label = "unresolved"
            else:
                rationale = (
                    f"{rationale} The matching official record is only a portal listing, "
                    "so the source document could not be checked."
                )
            gated = True

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
