"""Ingestion API (module 1, design.md section 4).

- ``POST /api/ingest/submit``: a student submits a notice as a multipart file
  (image/pdf) OR JSON ``{text}``. Runs extraction -> provenance hash ->
  comparison and returns the classified result. Image input with no OCR engine
  degrades to HTTP 422 asking for pasted text (graceful degradation, R2.1).
- ``POST /api/ingest/fetch`` (admin): runs the three institution adapters
  synchronously and upserts official notices by content hash (idempotent).
- ``GET/POST /api/ingest/sources`` (admin): CRUD over ``institution`` rows.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finalsay.auth import get_current_user, require_role
from finalsay.db import get_db
from finalsay.models import (
    Institution,
    Notice,
    NoticeDocumentExtraction,
    RelationEdge,
    ReviewCase,
    ScrapeProgress,
    ScrapeRun,
    User,
)
from finalsay.schemas import (
    ComparisonResponse,
    FetchResponse,
    InstitutionCreate,
    InstitutionOut,
    InstitutionUpdate,
    ScrapeRunOut,
)
from finalsay.services import comparison
from finalsay.services import ingestion
from finalsay.services.extraction import OcrUnavailable

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
_PDF_TYPES = {"application/pdf"}


# Submitting a notice for verification is a Student action in the scope note.
# We gate it to ``student`` (the primary actor) plus ``admin`` (operational
# override / demo convenience) rather than any authenticated role, keeping the
# per-actor route model consistent. Reviewers and issuers have their own routes.
@router.post("/submit", response_model=ComparisonResponse)
async def submit(
    text: str | None = Form(default=None),
    institution_id: int | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("student", "admin")),
) -> ComparisonResponse:
    """Ingest a student submission (upload or paste) and classify it."""
    if file is None and not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either a file (pdf/image) or pasted text.",
        )

    # Student verification always uses the college saved on the account. The
    # form cannot silently select a different institution; admins retain the
    # previous operational override behavior.
    available_institutions = list(
        db.scalars(
            select(Notice.institution_id)
            .join(Institution, Institution.id == Notice.institution_id)
            .where(
                Notice.kind == "official",
                Notice.is_current.is_(True),
                Institution.active.is_(True),
                Institution.scrape_type != "fixture",
            )
            .distinct()
        ).all()
    )
    if current_user.role == "student":
        if current_user.institution_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Choose your college before submitting a notice.",
            )
        if institution_id is not None and institution_id != current_user.institution_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student submissions must use the college saved on the account.",
            )
        institution_id = current_user.institution_id
        if institution_id not in available_institutions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No current official notices are available for your college yet.",
            )
    elif institution_id is None:
        if len(available_institutions) == 1:
            institution_id = available_institutions[0]
        elif len(available_institutions) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Select your institution so the notice is compared only with its official notices.",
            )
    else:
        institution = db.get(Institution, institution_id)
        if institution is None or not institution.active or institution.scrape_type == "fixture":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Select an active institution with official notice sources.",
            )
        if institution_id not in available_institutions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No current official notices are available for that institution yet.",
            )

    pdf_bytes: bytes | None = None
    image_bytes: bytes | None = None

    if file is not None:
        data = await file.read()
        content_type = (file.content_type or "").lower()
        if content_type in _PDF_TYPES or (file.filename or "").lower().endswith(".pdf"):
            pdf_bytes = data
        elif content_type in _IMAGE_TYPES or (file.filename or "").lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ):
            image_bytes = data
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type; upload a PDF or image, or paste text.",
            )
    try:
        submission = ingestion.create_submission(
            db,
            text=text,
            pdf_bytes=pdf_bytes,
            image_bytes=image_bytes,
            institution_id=institution_id,
            submitted_by=current_user.id,
        )
    except OcrUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    outcome = comparison.classify_submission(db, submission)
    db.commit()

    candidate_extractions = (
        list(
            db.scalars(
                select(NoticeDocumentExtraction)
                .where(NoticeDocumentExtraction.notice_id == outcome.candidate.id)
                .order_by(NoticeDocumentExtraction.extracted_at.desc())
            ).all()
        )
        if outcome.candidate
        else []
    )
    return ComparisonResponse(
        submission_id=submission.id,
        candidate_id=outcome.candidate.id if outcome.candidate else None,
        edge_id=outcome.edge.id,
        label=outcome.label,
        confidence=outcome.confidence,
        rationale=outcome.rationale,
        model=outcome.edge.model or "",
        status=outcome.edge.status,
        gated=outcome.gated,
        review_case_id=outcome.review_case.id if outcome.review_case else None,
        candidate_score=outcome.candidate_score,
        candidate_institution=(outcome.candidate.institution.name if outcome.candidate and outcome.candidate.institution else None),
        candidate_issuer=outcome.candidate.issuer if outcome.candidate else None,
        candidate_notice_date=outcome.candidate.notice_date if outcome.candidate else None,
        candidate_deadline=outcome.candidate.deadline if outcome.candidate else None,
        candidate_source_url=outcome.candidate.source_url if outcome.candidate else None,
        candidate_text=outcome.candidate.redacted_text if outcome.candidate else None,
        candidate_supplemental_extractions=candidate_extractions,
        evidence=outcome.evidence,
    )


@router.get("/submissions/{submission_id}/result", response_model=ComparisonResponse)
def get_submission_result(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ComparisonResponse:
    """Return the persisted comparison so a refreshed result is never stale."""
    submission = db.get(Notice, submission_id)
    if submission is None or submission.kind != "submission":
        raise HTTPException(status_code=404, detail="submission not found")
    if current_user.role == "student" and submission.submitted_by != current_user.id:
        raise HTTPException(status_code=404, detail="submission not found")
    if current_user.role not in {"student", "admin", "reviewer"}:
        raise HTTPException(status_code=403, detail="role cannot view comparison results")

    edge = db.scalar(
        select(RelationEdge)
        .where(RelationEdge.src_notice_id == submission.id)
        .order_by(RelationEdge.created_at.desc(), RelationEdge.id.desc())
        .limit(1)
    )
    if edge is None:
        raise HTTPException(status_code=404, detail="comparison result not found")

    candidate = db.get(Notice, edge.dst_notice_id)
    if candidate is not None and candidate.id == submission.id:
        candidate = None
    review_case = db.scalar(
        select(ReviewCase)
        .where(ReviewCase.edge_id == edge.id)
        .order_by(ReviewCase.id.desc())
        .limit(1)
    )
    extractions = (
        list(
            db.scalars(
                select(NoticeDocumentExtraction)
                .where(NoticeDocumentExtraction.notice_id == candidate.id)
                .order_by(NoticeDocumentExtraction.extracted_at.desc())
            ).all()
        )
        if candidate is not None
        else []
    )
    return ComparisonResponse(
        submission_id=submission.id,
        candidate_id=candidate.id if candidate else None,
        edge_id=edge.id,
        label=edge.label,
        confidence=edge.confidence,
        rationale=edge.rationale or "Persisted comparison result.",
        model=edge.model or "",
        status=edge.status,
        gated=edge.status == "unresolved",
        review_case_id=review_case.id if review_case else None,
        candidate_score=None,
        candidate_institution=(candidate.institution.name if candidate and candidate.institution else None),
        candidate_issuer=candidate.issuer if candidate else None,
        candidate_notice_date=candidate.notice_date if candidate else None,
        candidate_deadline=candidate.deadline if candidate else None,
        candidate_source_url=candidate.source_url if candidate else None,
        candidate_text=candidate.redacted_text if candidate else None,
        candidate_supplemental_extractions=extractions,
        evidence=[],
    )


@router.post(
    "/fetch",
    response_model=FetchResponse,
    dependencies=[Depends(require_role("admin"))],
)
def fetch(db: Session = Depends(get_db)) -> FetchResponse:
    """Run all adapters and upsert official notices by content hash (idempotent)."""
    from finalsay.services.scrape_runtime import acquire_scrape_slot, release_scrape_slot

    try:
        acquired = acquire_scrape_slot()
    except Exception as exc:  # noqa: BLE001 - fail closed if distributed coordination fails
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="source-poll coordination is unavailable",
        ) from exc
    if not acquired:
        raise HTTPException(status_code=409, detail="a source poll is already running")
    try:
        summary = ingestion.fetch_all(db, include_fixtures=False)
        db.commit()
        return FetchResponse(**summary)
    except Exception:
        db.rollback()
        raise
    finally:
        release_scrape_slot()


@router.get("/sources", response_model=list[InstitutionOut])
def list_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    query = select(Institution).where(
        Institution.scrape_type != "fixture"
    ).order_by(Institution.id)
    if current_user.role != "admin":
        query = query.where(Institution.active.is_(True))
    sources = list(db.scalars(query).all())
    quality_rows = db.execute(
        select(Notice.institution_id, Notice.extraction_quality, func.count())
        .where(
            Notice.kind == "official",
            Notice.is_current.is_(True),
            Notice.institution_id.is_not(None),
        )
        .group_by(Notice.institution_id, Notice.extraction_quality)
    ).all()
    quality_counts: dict[int, dict[str, int]] = {}
    for institution_id, quality, count in quality_rows:
        counts = quality_counts.setdefault(institution_id, {})
        counts[quality or "unknown"] = int(count)
    result = []
    for source in sources:
        progress = db.get(ScrapeProgress, source.id)
        latest_success = db.scalar(
            select(ScrapeRun)
            .where(
                ScrapeRun.institution_id == source.id,
                ScrapeRun.status.in_(("ok", "partial")),
                ScrapeRun.completed_at.is_not(None),
            )
            .order_by(ScrapeRun.completed_at.desc(), ScrapeRun.id.desc())
            .limit(1)
        )
        source_quality = quality_counts.get(source.id, {})
        result.append({
            "id": source.id,
            "name": source.name,
            "slug": source.slug,
            "source_url": source.source_url,
            "scrape_type": source.scrape_type,
            "scrape_enabled": source.scrape_enabled,
            "active": source.active,
            "backfill_complete": progress.backfill_complete if progress else False,
            "backfill_cursor": progress.cursor if progress else None,
            "last_successful_fetch": latest_success.completed_at if latest_success else None,
            "last_successful_created": latest_success.created if latest_success else 0,
            "last_successful_modified": latest_success.modified if latest_success else 0,
            "last_successful_unchanged": latest_success.unchanged if latest_success else 0,
            "current_notice_count": sum(source_quality.values()),
            "extracted_count": source_quality.get("extracted", 0),
            "listing_only_count": source_quality.get("listing_only", 0),
            "unextractable_count": source_quality.get("unextractable", 0),
            "unknown_extraction_count": sum(
                count for quality, count in source_quality.items()
                if quality not in {"extracted", "listing_only", "unextractable"}
            ),
        })
    return result


@router.post(
    "/sources",
    response_model=InstitutionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
)
def create_source(
    payload: InstitutionCreate, db: Session = Depends(get_db)
) -> Institution:
    from finalsay.adapters.live import SourceFetchError, validate_scrape_config

    try:
        validate_scrape_config(payload.scrape_type, payload.source_url, resolve_host=False)
    except SourceFetchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = db.scalar(
        select(Institution).where(Institution.slug == payload.slug)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"institution slug '{payload.slug}' already exists",
        )
    institution = Institution(
        name=payload.name,
        slug=payload.slug,
        source_url=payload.source_url,
        scrape_type=payload.scrape_type,
        scrape_enabled=payload.scrape_enabled,
        active=payload.active,
    )
    db.add(institution)
    db.commit()
    db.refresh(institution)
    return institution


@router.put(
    "/sources/{institution_id}",
    response_model=InstitutionOut,
    dependencies=[Depends(require_role("admin"))],
)
def update_source(
    institution_id: int,
    payload: InstitutionUpdate,
    db: Session = Depends(get_db),
) -> Institution:
    from finalsay.adapters.live import SourceFetchError, validate_scrape_config

    institution = db.get(Institution, institution_id)
    if institution is None:
        raise HTTPException(status_code=404, detail="institution source not found")
    updates = payload.model_dump(exclude_unset=True)
    scrape_type = updates.get("scrape_type", institution.scrape_type)
    source_url = updates.get("source_url", institution.source_url)
    try:
        validate_scrape_config(scrape_type, source_url, resolve_host=False)
    except SourceFetchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for key, value in updates.items():
        setattr(institution, key, value)
    db.commit()
    db.refresh(institution)
    return institution


@router.get(
    "/runs",
    response_model=list[ScrapeRunOut],
    dependencies=[Depends(require_role("admin"))],
)
def list_scrape_runs(db: Session = Depends(get_db)) -> list[ScrapeRun]:
    return list(db.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(50)).all())
