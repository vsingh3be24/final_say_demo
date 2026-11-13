"""Notices API (design.md sections 4/7).

- ``GET /api/notices`` lists official notices (optionally filtered by institution).
- ``GET /api/notices/{id}`` returns a notice with its extracted fields (evidence).
- ``GET /api/notices/{submission_id}/candidates`` returns ranked official
  candidates for a submission (the same retrieval used by comparison).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import ensure_notice_access, get_current_user
from finalsay.db import get_db
from finalsay.models import Notice, NoticeDocumentExtraction, User
from finalsay.schemas import CandidateOut, NoticeDetail, NoticeSummary
from finalsay.services import comparison

router = APIRouter(prefix="/api/notices", tags=["notices"])


@router.get("", response_model=list[NoticeSummary])
def list_notices(
    institution_id: int | None = Query(default=None),
    kind: str = Query(default="official"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Notice]:
    if kind not in {"official", "submission"}:
        raise HTTPException(status_code=422, detail="kind must be official or submission")
    query = select(Notice).where(Notice.kind == kind).order_by(Notice.id.desc())
    query = query.where(Notice.is_current.is_(True))
    if kind == "submission" and current_user.role not in {"admin", "reviewer"}:
        if current_user.role != "student":
            raise HTTPException(status_code=403, detail="role cannot list submissions")
        query = query.where(Notice.submitted_by == current_user.id)
    if institution_id is not None:
        query = query.where(Notice.institution_id == institution_id)
    return list(db.scalars(query).all())


@router.get("/{notice_id}", response_model=NoticeDetail)
def notice_detail(
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NoticeDetail:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notice {notice_id} not found",
        )
    ensure_notice_access(notice, current_user)
    detail = NoticeDetail.model_validate(notice)
    detail.supplemental_extractions = list(
        db.scalars(
            select(NoticeDocumentExtraction)
            .where(NoticeDocumentExtraction.notice_id == notice.id)
            .order_by(NoticeDocumentExtraction.extracted_at.desc())
        ).all()
    )
    return detail


@router.get("/{notice_id}/versions", response_model=list[NoticeSummary])
def notice_versions(
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Notice]:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail=f"notice {notice_id} not found")
    ensure_notice_access(notice, current_user)
    if not notice.source_key:
        return [notice]
    versions = db.scalars(
        select(Notice)
        .where(
            Notice.kind == notice.kind,
            Notice.institution_id == notice.institution_id,
            Notice.source_key == notice.source_key,
        )
        .order_by(Notice.version_no.asc(), Notice.id.asc())
    ).all()
    return list(versions)


@router.get("/{submission_id}/candidates", response_model=list[CandidateOut])
def candidates(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CandidateOut]:
    submission = db.get(Notice, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notice {submission_id} not found",
        )
    if submission.kind != "submission":
        raise HTTPException(status_code=422, detail="candidate lookup requires a submission")
    ensure_notice_access(submission, current_user)
    ranked = comparison.retrieve_candidates(db, submission)
    return [
        CandidateOut(
            notice=NoticeSummary.model_validate(c.notice),
            score=c.score,
            semantic_similarity=c.semantic_similarity,
        )
        for c in ranked
    ]
