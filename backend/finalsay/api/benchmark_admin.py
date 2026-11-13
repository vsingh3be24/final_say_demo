"""Admin curation of real submissions for blind reviewer benchmarking."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import aliased

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import BenchmarkPair, Institution, Notice, RelationEdge, User
from finalsay.schemas import (
    BenchmarkPairCreateRequest,
    BenchmarkPairCreateResponse,
    BenchmarkCandidateOut,
)

router = APIRouter(prefix="/api/admin/benchmark", tags=["benchmark curation"])


@router.get(
    "/candidates",
    response_model=list[BenchmarkCandidateOut],
    dependencies=[Depends(require_role("admin"))],
)
def list_real_benchmark_candidates(
    db: Session = Depends(get_db),
) -> list[BenchmarkCandidateOut]:
    """List genuine student/live-source comparison pairs not yet curated.

    Model labels, confidence, and rationale are intentionally omitted so
    curation does not pre-label the blind reviewer corpus.
    """
    submission = aliased(Notice, name="submission")
    official = aliased(Notice, name="official")
    already_curated = select(BenchmarkPair.id).where(
        BenchmarkPair.submission_id == submission.id,
        BenchmarkPair.official_id == official.id,
    ).exists()
    rows = db.execute(
        select(
            submission.id,
            official.id,
            Institution.name,
            submission.title,
            official.title,
            submission.created_at,
            official.published_date,
        )
        .distinct()
        .select_from(submission)
        .join(User, User.id == submission.submitted_by)
        .join(RelationEdge, RelationEdge.src_notice_id == submission.id)
        .join(official, official.id == RelationEdge.dst_notice_id)
        .join(Institution, Institution.id == official.institution_id)
        .where(
            submission.kind == "submission",
            User.role == "student",
            or_(submission.source_url.is_(None), ~submission.source_url.like("seed:%")),
            official.kind == "official",
            official.is_current.is_(True),
            official.institution_id == submission.institution_id,
            Institution.active.is_(True),
            Institution.scrape_type != "fixture",
            func.trim(submission.redacted_text) != "",
            func.trim(official.redacted_text) != "",
            ~already_curated,
        )
        .order_by(submission.created_at.desc(), submission.id.desc(), official.id),
    ).all()
    return [
        BenchmarkCandidateOut(
            submission_id=row[0],
            official_id=row[1],
            institution_name=row[2],
            submission_title=row[3],
            official_title=row[4],
            submission_created_at=row[5],
            official_published_date=row[6],
        )
        for row in rows
    ]


@router.post(
    "/pairs",
    response_model=BenchmarkPairCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
)
def create_real_benchmark_pair(
    payload: BenchmarkPairCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> BenchmarkPairCreateResponse:
    """Snapshot a real student/candidate pair without adding a gold label.

    The source records must be a non-demo student submission and its current
    official candidate from an active live institution, with a persisted
    comparison edge linking them. Repeated requests are idempotent.
    """
    submission = db.get(Notice, payload.submission_id)
    official = db.get(Notice, payload.official_id)
    if submission is None or official is None:
        raise HTTPException(status_code=404, detail="submission or official notice not found")
    if submission.kind != "submission" or submission.submitted_by is None:
        raise HTTPException(
            status_code=422,
            detail="benchmark input must be a persisted student submission",
        )
    submitter = db.get(User, submission.submitted_by)
    if submitter is None or submitter.role != "student":
        raise HTTPException(status_code=422, detail="submission must belong to a student")
    if submission.source_url and submission.source_url.startswith("seed:"):
        raise HTTPException(status_code=422, detail="seed/demo submissions cannot be benchmarked")
    if official.kind != "official" or not official.is_current:
        raise HTTPException(
            status_code=422,
            detail="benchmark reference must be a current official notice",
        )
    if submission.institution_id is None or official.institution_id != submission.institution_id:
        raise HTTPException(
            status_code=422,
            detail="submission and official candidate must belong to the same institution",
        )
    institution = db.get(Institution, official.institution_id)
    if institution is None or not institution.active or institution.scrape_type == "fixture":
        raise HTTPException(
            status_code=422,
            detail="benchmark reference must come from an active live institution",
        )
    if not (submission.redacted_text or "").strip() or not (official.redacted_text or "").strip():
        raise HTTPException(status_code=422, detail="both notices need extracted text")

    edge = db.scalar(
        select(RelationEdge).where(
            RelationEdge.src_notice_id == submission.id,
            RelationEdge.dst_notice_id == official.id,
        )
    )
    if edge is None:
        raise HTTPException(
            status_code=422,
            detail="the official notice must be the persisted comparison candidate",
        )

    existing = db.scalar(
        select(BenchmarkPair).where(
            BenchmarkPair.submission_id == submission.id,
            BenchmarkPair.official_id == official.id,
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return BenchmarkPairCreateResponse(
            id=existing.id,
            submission_id=existing.submission_id,
            official_id=existing.official_id,
            created=False,
        )

    pair = BenchmarkPair(
        submission_id=submission.id,
        official_id=official.id,
        # Snapshot actual text for a stable blind corpus. Never copy the model
        # prediction or an inferred label into the reviewer benchmark.
        submission_text=submission.redacted_text,
        official_text=official.redacted_text,
        gold_label=None,
    )
    db.add(pair)
    db.commit()
    db.refresh(pair)
    return BenchmarkPairCreateResponse(
        id=pair.id,
        submission_id=pair.submission_id,
        official_id=pair.official_id,
        created=True,
    )
