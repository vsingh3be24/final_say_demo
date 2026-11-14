"""Notices API (design.md sections 4/7).

- ``GET /api/notices`` lists official notices (optionally filtered by institution).
- ``GET /api/notices/{id}`` returns a notice with its extracted fields (evidence).
- ``GET /api/notices/{submission_id}/candidates`` returns ranked official
  candidates for a submission (the same retrieval used by comparison).
"""

from __future__ import annotations

import math
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finalsay.auth import ensure_notice_access, get_current_user
from finalsay.db import get_db
from finalsay.models import Institution, Notice, NoticeDocumentExtraction, User
from finalsay.schemas import (
    CandidateOut,
    NoticeDetail,
    NoticeMonthCount,
    NoticeSummary,
    StudentNoticeFeed,
    StudentNoticeItem,
)
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
    if kind == "official" and current_user.role == "student":
        if current_user.institution_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Choose your college before browsing official notices.",
            )
        if institution_id is not None and institution_id != current_user.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Students can browse official notices for their selected college.",
            )
        institution_id = current_user.institution_id
    if kind == "submission" and current_user.role not in {"admin", "reviewer"}:
        if current_user.role != "student":
            raise HTTPException(status_code=403, detail="role cannot list submissions")
        query = query.where(Notice.submitted_by == current_user.id)
    if institution_id is not None:
        query = query.where(Notice.institution_id == institution_id)
    if kind == "official" and current_user.role == "student":
        # The paginated student feed is canonical. Keep this compatibility
        # endpoint bounded so old clients cannot pull the entire archive.
        query = query.limit(50)
    return list(db.scalars(query).all())


@router.get("/student/feed", response_model=StudentNoticeFeed)
def student_notice_feed(
    month: str | None = Query(default=None, max_length=7),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StudentNoticeFeed:
    """Return a paginated, college-scoped official notice feed for a student."""
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="student account required")
    if current_user.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Choose your college before browsing official notices.",
        )
    institution = db.get(Institution, current_user.institution_id)
    if institution is None or not institution.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your selected college is not currently available. Choose another college.",
        )

    if month is not None and month != "undated":
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise HTTPException(status_code=422, detail="month must be YYYY-MM or undated")
        year, month_number = (int(part) for part in month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= month_number <= 12:
            raise HTTPException(status_code=422, detail="month must be YYYY-MM or undated")
        month_start = date(year, month_number, 1)
        month_end = date(year + (month_number == 12), month_number % 12 + 1, 1)
    else:
        month_start = month_end = None

    base = select(Notice).where(
        Notice.kind == "official",
        Notice.is_current.is_(True),
        Notice.institution_id == institution.id,
    )
    date_rows = db.execute(
        select(Notice.published_on, func.count(Notice.id))
        .where(
            Notice.kind == "official",
            Notice.is_current.is_(True),
            Notice.institution_id == institution.id,
        )
        .group_by(Notice.published_on)
    ).all()
    month_counts: dict[str, int] = {}
    undated_count = 0
    for published_on, count in date_rows:
        if published_on is None:
            undated_count = count
        else:
            month_key = published_on.strftime("%Y-%m")
            month_counts[month_key] = month_counts.get(month_key, 0) + count

    query = base
    if month == "undated":
        query = query.where(Notice.published_on.is_(None))
    elif month_start is not None and month_end is not None:
        query = query.where(
            Notice.published_on >= month_start,
            Notice.published_on < month_end,
        )

    if q and q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        query = query.where(
            or_(
                Notice.title.ilike(pattern, escape="\\"),
                Notice.issuer.ilike(pattern, escape="\\"),
                Notice.redacted_text.ilike(pattern, escape="\\"),
            )
        )

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    page_count = math.ceil(total / page_size) if total else 0
    items = list(
        db.scalars(
            query.order_by(Notice.published_on.desc().nullslast(), Notice.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    feed_items = []
    for notice in items:
        summary = NoticeSummary.model_validate(notice).model_dump()
        preview_text = " ".join((notice.redacted_text or "").split())
        feed_items.append(
            StudentNoticeItem(
                **summary,
                preview=preview_text[:240] + ("…" if len(preview_text) > 240 else "") or None,
            )
        )

    return StudentNoticeFeed(
        institution_id=institution.id,
        institution_name=institution.name,
        items=feed_items,
        total=total,
        page=page,
        page_size=page_size,
        page_count=page_count,
        months=[
            NoticeMonthCount(month=key, count=count)
            for key, count in sorted(month_counts.items(), reverse=True)
        ],
        undated_count=undated_count,
    )


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
