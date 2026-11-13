"""Reviewer console API (module 5, design.md section 8).

- ``GET /api/reviewer/queue`` lists open unresolved cases with the edge and both
  notices.
- ``POST /api/reviewer/cases/{id}/resolve {label}`` sets the edge label, marks
  the edge ``confirmed`` (label unchanged) or ``corrected`` (label changed), and
  closes the review case.
- Benchmark: reviewers see the shared corpus plus only their own saved label.
  They annotate with ``POST /api/reviewer/benchmark/annotate {pair_id, label}``
  and lock a complete pass with ``POST /api/reviewer/benchmark/complete``.
  Kappa and per-label agreement remain hidden until two passes are complete.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import (
    RELATIONSHIP_LABELS,
    BenchmarkCompletion,
    BenchmarkAnnotation,
    BenchmarkPair,
    Notice,
    RelationEdge,
    ReviewCase,
    User,
)
from finalsay.schemas import (
    BenchmarkAnnotateRequest,
    BenchmarkCompletionOut,
    BenchmarkPairOut,
    BenchmarkStatusOut,
    KappaResponse,
    NoticeSummary,
    ResolveRequest,
    ResolveResponse,
    ReviewQueueItem,
)
from finalsay.services.kappa import cohen_kappa, per_label_counts

router = APIRouter(prefix="/api/reviewer", tags=["reviewer"])


def _benchmark_pair_output(
    db: Session, pair: BenchmarkPair, *, your_label: str | None
) -> BenchmarkPairOut:
    left = db.get(Notice, pair.submission_id)
    right = db.get(Notice, pair.official_id)
    is_source_revision = bool(
        left is not None and right is not None
        and left.kind == "official" and right.kind == "official"
    )
    institution = left.institution if left is not None else None
    return BenchmarkPairOut(
        id=pair.id,
        submission_id=pair.submission_id,
        official_id=pair.official_id,
        submission_text=pair.submission_text,
        official_text=pair.official_text,
        pair_kind="source_revision" if is_source_revision else "student_comparison",
        institution_name=institution.name if institution is not None else None,
        left_title=left.title if left is not None else None,
        right_title=right.title if right is not None else None,
        your_label=your_label,
    )


@router.get(
    "/queue",
    response_model=list[ReviewQueueItem],
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def queue(db: Session = Depends(get_db)) -> list[ReviewQueueItem]:
    cases = db.scalars(
        select(ReviewCase).where(ReviewCase.status == "open").order_by(ReviewCase.id)
    ).all()

    items: list[ReviewQueueItem] = []
    for case in cases:
        edge = db.get(RelationEdge, case.edge_id)
        if edge is None:
            continue
        submission = db.get(Notice, edge.src_notice_id)
        candidate = db.get(Notice, edge.dst_notice_id)
        # For a no-candidate edge, src == dst; show no candidate in that case.
        candidate_summary = (
            NoticeSummary.model_validate(candidate)
            if candidate is not None and candidate.id != edge.src_notice_id
            else None
        )
        items.append(
            ReviewQueueItem(
                case_id=case.id,
                edge_id=edge.id,
                status=case.status,
                label=edge.label,
                confidence=edge.confidence,
                rationale=edge.rationale,
                submission=NoticeSummary.model_validate(submission),
                candidate=candidate_summary,
            )
        )
    return items


@router.post(
    "/cases/{case_id}/resolve",
    response_model=ResolveResponse,
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def resolve(
    case_id: int,
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer", "admin")),
) -> ResolveResponse:
    if payload.label not in RELATIONSHIP_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"label must be one of {RELATIONSHIP_LABELS}",
        )
    case = db.get(ReviewCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"review case {case_id} not found",
        )
    edge = db.get(RelationEdge, case.edge_id)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="edge for review case not found",
        )

    # "confirmed" when the reviewer keeps the model's label, "corrected" otherwise.
    edge_status = "confirmed" if payload.label == edge.label else "corrected"
    edge.label = payload.label
    edge.status = edge_status

    case.status = "closed"
    case.resolved_by = current_user.id
    case.resolved_label = payload.label
    db.commit()

    return ResolveResponse(
        case_id=case.id,
        edge_id=edge.id,
        label=edge.label,
        edge_status=edge.status,
        case_status=case.status,
    )


@router.get(
    "/benchmark/pairs",
    response_model=list[BenchmarkPairOut],
    dependencies=[Depends(require_role("reviewer"))],
)
def benchmark_pairs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer")),
) -> list[BenchmarkPairOut]:
    """Return the corpus and only the signed-in reviewer's own saved labels."""
    pairs, fingerprint = _benchmark_corpus(db)
    own_annotations = db.scalars(
        select(BenchmarkAnnotation).where(
            BenchmarkAnnotation.user_id == current_user.id,
            BenchmarkAnnotation.pair_id.in_([pair.id for pair in pairs] or [-1]),
        )
    ).all()
    own_labels = {annotation.pair_id: annotation.label for annotation in own_annotations}
    return [
        _benchmark_pair_output(db, pair, your_label=own_labels.get(pair.id))
        for pair in pairs
    ]


@router.get(
    "/benchmark/status",
    response_model=BenchmarkStatusOut,
    dependencies=[Depends(require_role("reviewer"))],
)
def benchmark_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer")),
) -> BenchmarkStatusOut:
    pairs, fingerprint = _benchmark_corpus(db)
    completed = _current_completion(db, current_user.id, len(pairs), fingerprint)
    annotated_count = db.scalar(
        select(func.count(BenchmarkAnnotation.id)).where(
            BenchmarkAnnotation.user_id == current_user.id,
            BenchmarkAnnotation.pair_id.in_([pair.id for pair in pairs] or [-1]),
        )
    ) or 0
    return BenchmarkStatusOut(
        completed=completed is not None,
        pair_count=len(pairs),
        annotated_count=int(annotated_count),
    )


@router.post(
    "/benchmark/annotate",
    response_model=BenchmarkPairOut,
    dependencies=[Depends(require_role("reviewer"))],
)
def benchmark_annotate(
    payload: BenchmarkAnnotateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer")),
) -> BenchmarkPairOut:
    if payload.label not in RELATIONSHIP_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"label must be one of {RELATIONSHIP_LABELS}",
        )
    pair = db.get(BenchmarkPair, payload.pair_id)
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"benchmark pair {payload.pair_id} not found",
        )
    pairs, fingerprint = _benchmark_corpus(db)
    completion = _current_completion(db, current_user.id, len(pairs), fingerprint)
    if completion is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="your blind annotation pass is complete and locked",
        )
    # The account identity is server-derived, so one reviewer cannot pose as
    # two independent annotators by changing a request field.
    existing = db.scalar(
        select(BenchmarkAnnotation).where(
            BenchmarkAnnotation.pair_id == payload.pair_id,
            BenchmarkAnnotation.user_id == current_user.id,
        )
    )
    if existing is not None:
        existing.label = payload.label
    else:
        db.add(
            BenchmarkAnnotation(
                pair_id=payload.pair_id,
                annotator=current_user.email,
                user_id=current_user.id,
                label=payload.label,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        # Concurrent saves may race between the read-before-insert and commit.
        # The database index keeps one row; recover as an existing-label update.
        db.rollback()
        concurrent = db.scalar(
            select(BenchmarkAnnotation).where(
                BenchmarkAnnotation.pair_id == payload.pair_id,
                BenchmarkAnnotation.user_id == current_user.id,
            )
        )
        if concurrent is None:
            raise
        completion = _current_completion(db, current_user.id, len(pairs), fingerprint)
        if completion is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="your blind annotation pass is complete and locked",
            )
        concurrent.label = payload.label
        db.commit()
    db.refresh(pair)
    return _benchmark_pair_output(db, pair, your_label=payload.label)


@router.post(
    "/benchmark/complete",
    response_model=BenchmarkCompletionOut,
    dependencies=[Depends(require_role("reviewer"))],
)
def benchmark_complete(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer")),
) -> BenchmarkCompletionOut:
    pairs, fingerprint = _benchmark_corpus(db)
    if not pairs:
        raise HTTPException(status_code=409, detail="there are no benchmark pairs")

    completion = _current_completion(db, current_user.id, len(pairs), fingerprint)
    if completion is not None:
        return BenchmarkCompletionOut(
            completed=True, pair_count=len(pairs), annotated_count=len(pairs)
        )

    pair_ids = {pair.id for pair in pairs}
    labeled_ids = set(
        db.scalars(
            select(BenchmarkAnnotation.pair_id).where(
                BenchmarkAnnotation.user_id == current_user.id,
                BenchmarkAnnotation.pair_id.in_(pair_ids),
            )
        ).all()
    )
    if labeled_ids != pair_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"label every pair before completing ({len(pair_ids - labeled_ids)} remain)",
        )

    prior_completion = db.scalar(
        select(BenchmarkCompletion).where(BenchmarkCompletion.user_id == current_user.id)
    )
    if prior_completion is not None:
        db.delete(prior_completion)

    db.add(
        BenchmarkCompletion(
            user_id=current_user.id,
            pair_count=len(pairs),
            pair_fingerprint=fingerprint,
        )
    )
    db.commit()
    return BenchmarkCompletionOut(
        completed=True, pair_count=len(pairs), annotated_count=len(pairs)
    )


@router.get(
    "/benchmark/kappa",
    response_model=KappaResponse,
    dependencies=[Depends(require_role("reviewer"))],
)
def benchmark_kappa(db: Session = Depends(get_db)) -> KappaResponse:
    return compute_benchmark_kappa(db)


def _benchmark_corpus(db: Session) -> tuple[list[BenchmarkPair], str]:
    pairs = list(db.scalars(select(BenchmarkPair).order_by(BenchmarkPair.id)).all())
    corpus = [
        [p.id, p.submission_id, p.official_id, p.submission_text, p.official_text]
        for p in pairs
    ]
    fingerprint = hashlib.sha256(
        json.dumps(corpus, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return pairs, fingerprint


def _current_completion(
    db: Session, user_id: int, pair_count: int, fingerprint: str
) -> BenchmarkCompletion | None:
    completion = db.scalar(
        select(BenchmarkCompletion).where(BenchmarkCompletion.user_id == user_id)
    )
    if (
        completion is not None
        and completion.pair_count == pair_count
        and completion.pair_fingerprint == fingerprint
    ):
        return completion
    return None


def compute_benchmark_kappa(db: Session) -> KappaResponse:
    """Reveal agreement only after two reviewers finish the same corpus.

    Generated seed annotations have no authenticated ``user_id`` and are never
    included. Until both blind passes are complete, the response intentionally
    contains no annotator names, progress, labels, or partial agreement.
    """
    pairs, fingerprint = _benchmark_corpus(db)
    if not pairs:
        return KappaResponse(kappa=None, ready=False, annotators=[], pairs_compared=0, per_label={})

    completions = db.scalars(
        select(BenchmarkCompletion)
        .join(User, User.id == BenchmarkCompletion.user_id)
        .where(
            User.role == "reviewer",
            BenchmarkCompletion.pair_count == len(pairs),
            BenchmarkCompletion.pair_fingerprint == fingerprint,
        )
        .order_by(BenchmarkCompletion.completed_at, BenchmarkCompletion.user_id)
    ).all()
    if len(completions) < 2:
        return KappaResponse(kappa=None, ready=False, annotators=[], pairs_compared=0, per_label={})

    selected = completions[:2]
    user_ids = [completion.user_id for completion in selected]
    labels_by_user: dict[int, dict[int, str]] = {user_id: {} for user_id in user_ids}
    annotations = db.scalars(
        select(BenchmarkAnnotation).where(
            BenchmarkAnnotation.user_id.in_(user_ids),
            BenchmarkAnnotation.pair_id.in_([pair.id for pair in pairs]),
        )
    ).all()
    for annotation in annotations:
        if annotation.user_id in labels_by_user:
            labels_by_user[annotation.user_id][annotation.pair_id] = annotation.label

    pair_ids = [pair.id for pair in pairs]
    if any(set(labels_by_user[user_id]) != set(pair_ids) for user_id in user_ids):
        return KappaResponse(kappa=None, ready=False, annotators=[], pairs_compared=0, per_label={})

    labels_a = [labels_by_user[user_ids[0]][pair_id] for pair_id in pair_ids]
    labels_b = [labels_by_user[user_ids[1]][pair_id] for pair_id in pair_ids]
    names = [completion.user.email for completion in selected]
    return KappaResponse(
        kappa=round(cohen_kappa(labels_a, labels_b), 6),
        ready=True,
        annotators=names,
        pairs_compared=len(pair_ids),
        per_label=per_label_counts(labels_a, labels_b),
        is_seed_demo=False,
    )
