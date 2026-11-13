"""Ingestion service (module 1, design.md section 4).

Shared helpers used by the ingestion, issuer and seed code paths:

- ``upsert_official`` runs a raw notice through extraction (which redacts and
  extracts fields) and versions it by its stable source key. When a source has
  no key, an identical current content hash remains an idempotency fallback.
- ``create_submission`` runs the same extraction pipeline for a student
  submission and stores the resulting ``submission`` notice.

Only redacted text and extracted fields are ever persisted (GC-5, R2.4).
"""

from __future__ import annotations

from datetime import datetime, timezone
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.adapters.base import RawNotice
from finalsay.models import Institution, Notice, NoticeField, ScrapeProgress, ScrapeRun
from finalsay.services import extraction
from finalsay.services.extraction import ExtractionResult
from finalsay.services.provenance import sha256_notice

_TITLE_RE = re.compile(r"(?:^|\n)\s*(?:subject|title)\s*[:\-]\s*(.+)", re.IGNORECASE)
_DEGRADED_QUALITIES = {"listing_only", "unextractable"}
_QUALITY_RANK = {
    "listing_only": 0,
    "unextractable": 1,
    "unknown": 1,
    "extracted": 2,
    "issuer_submitted": 2,
    "student_submitted": 2,
}


def _stored_quality(notice: Notice, incoming_text: str) -> str:
    """Infer older rows' quality until their next successful document fetch."""
    quality = notice.extraction_quality or "unknown"
    if quality != "unknown":
        return quality
    current_text = notice.redacted_text or ""
    if "Official listing:" in current_text or (
        "Circular code:" in current_text and len(current_text) < 600
    ):
        return "listing_only"
    # Before extraction_quality existed, successful OCR/PDF records have no
    # structured marker. A clearly longer body remains the safer current copy
    # when the new poll has only a short fallback payload.
    if len(current_text) >= max(500, len(incoming_text) + 100):
        return "extracted"
    return "unknown"


def _preserve_better_current(
    current: Notice, incoming_quality: str, incoming_text: str
) -> bool:
    """Prevent a failed extraction fallback from replacing richer current text."""
    if incoming_quality not in _DEGRADED_QUALITIES:
        return False
    current_quality = _stored_quality(current, incoming_text)
    current_rank = _QUALITY_RANK.get(current_quality, 1)
    incoming_rank = _QUALITY_RANK.get(incoming_quality, 1)
    if current_rank > incoming_rank:
        return True
    return (
        current_rank == incoming_rank
        and current_rank <= 1
        and len(current.redacted_text or "") > len(incoming_text)
    )


def _store_fields(db: Session, notice: Notice, result: ExtractionResult) -> None:
    """Replace a notice's stored fields with the freshly extracted ones."""
    for stale in list(notice.fields):
        db.delete(stale)
    for name, (value, confidence) in result.fields.items():
        db.add(
            NoticeField(
                notice_id=notice.id,
                field_name=name,
                value=value,
                confidence=confidence,
            )
        )


def _apply_extraction(notice: Notice, result: ExtractionResult) -> None:
    """Copy extracted fields onto the notice columns and compute its hash."""
    notice.redacted_text = result.redacted_text
    notice.issuer = result.field_value("issuer")
    notice.notice_date = result.field_value("date")
    notice.deadline = result.field_value("deadline")
    notice.audience = result.field_value("audience")
    notice.action = result.field_value("action")
    notice.sha256 = sha256_notice(
        notice.redacted_text,
        notice.issuer,
        notice.notice_date,
        notice.deadline,
        notice.audience,
        notice.action,
    )


def get_or_create_institution(
    db: Session, slug: str, name: str, source_url: str | None = None
) -> Institution:
    """Return the institution with ``slug``, creating it if absent (idempotent)."""
    institution = db.scalar(select(Institution).where(Institution.slug == slug))
    if institution is None:
        institution = Institution(slug=slug, name=name, source_url=source_url)
        db.add(institution)
        db.flush()
    return institution


def upsert_official(
    db: Session, raw: RawNotice, institution: Institution
) -> tuple[Notice, str]:
    """Upsert an official notice by stable source key, with versioned content.

    Returns ``(notice, outcome)`` where outcome is ``created``, ``modified`` or
    ``unchanged``. Changed source documents are appended as a new Notice row so
    old hashes and Merkle proofs remain verifiable.
    """
    result = extraction.extract(text=raw.text)
    digest = sha256_notice(
        result.redacted_text,
        result.field_value("issuer"),
        result.field_value("date"),
        result.field_value("deadline"),
        result.field_value("audience"),
        result.field_value("action"),
    )
    source_url = (
        extraction.normalize_unicode_text(raw.source_url) if raw.source_url else None
    )
    source_key_value = raw.external_id or source_url
    source_key = (
        extraction.normalize_unicode_text(source_key_value)
        if source_key_value else None
    )
    incoming_quality = str(raw.metadata.get("extraction_quality", "unknown"))
    incoming_source_hash = raw.metadata.get("source_content_sha256")
    if incoming_source_hash:
        incoming_source_hash = str(incoming_source_hash).strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", incoming_source_hash):
            incoming_source_hash = None
    current = None
    if source_key:
        current = db.scalar(
            select(Notice).where(
                Notice.kind == "official",
                Notice.institution_id == institution.id,
                Notice.source_key == source_key,
                Notice.is_current.is_(True),
            ).order_by(Notice.version_no.desc())
        )
    if current is not None:
        current_source_hash = current.source_content_sha256
        same_source_file = bool(
            incoming_source_hash
            and current_source_hash
            and incoming_source_hash == current_source_hash
        )
        changed_source_file = bool(
            incoming_source_hash
            and current_source_hash
            and incoming_source_hash != current_source_hash
        )
        if same_source_file:
            # The downloaded bytes are authoritative for same-URL file changes.
            # OCR/PDF text can vary across extraction versions even when the
            # official file did not change; do not create a false notice version.
            current.retrieved_at = datetime.now(timezone.utc)
            published_date = raw.metadata.get("source_date")
            if published_date:
                current.published_date = extraction.normalize_unicode_text(str(published_date))[:80]
            return current, "unchanged"
        if current.sha256 == digest and not changed_source_file:
            # Existing rows predate the raw-file fingerprint. Establish a
            # baseline without manufacturing a version on the first poll.
            if incoming_source_hash and not current_source_hash:
                current.source_content_sha256 = incoming_source_hash
            current.retrieved_at = datetime.now(timezone.utc)
            if _QUALITY_RANK.get(incoming_quality, 1) > _QUALITY_RANK.get(
                current.extraction_quality or "unknown", 1
            ):
                current.extraction_quality = incoming_quality
            published_date = raw.metadata.get("source_date")
            if published_date:
                current.published_date = extraction.normalize_unicode_text(str(published_date))[:80]
            return current, "unchanged"
    if current is not None and _preserve_better_current(
        current, incoming_quality, result.redacted_text
    ):
        if current.extraction_quality == "unknown":
            current.extraction_quality = _stored_quality(current, result.redacted_text)
        current.retrieved_at = datetime.now(timezone.utc)
        return current, "unchanged"
    # A distinct official source key is a distinct published notice even if
    # its body happens to match another notice. Collapsing by hash here loses
    # source provenance and can make catalog rows disappear from retrieval.
    # Content-hash dedupe remains useful only for sources without stable keys.
    if current is None and not source_key:
        existing = db.scalar(
            select(Notice).where(
                Notice.kind == "official",
                Notice.institution_id == institution.id,
                Notice.sha256 == digest,
                Notice.is_current.is_(True),
            )
        )
        if existing is not None:
            existing.retrieved_at = datetime.now(timezone.utc)
            if _QUALITY_RANK.get(incoming_quality, 1) > _QUALITY_RANK.get(
                existing.extraction_quality or "unknown", 1
            ):
                existing.extraction_quality = incoming_quality
            published_date = raw.metadata.get("source_date")
            if published_date:
                existing.published_date = extraction.normalize_unicode_text(str(published_date))[:80]
            return existing, "unchanged"

    previous_id = None
    version_no = 1
    outcome = "created"
    if current is not None:
        current.is_current = False
        previous_id = current.id
        version_no = current.version_no + 1
        outcome = "modified"

    title = raw.metadata.get("title")
    if not title:
        title_match = _TITLE_RE.search(raw.text)
        title = title_match.group(1).strip()[:500] if title_match else None
    if title:
        title = extraction.normalize_unicode_text(str(title))[:500]

    notice = Notice(
        kind="official",
        institution_id=institution.id,
        title=title,
        published_date=(
            extraction.normalize_unicode_text(str(raw.metadata["source_date"]))[:80]
            if raw.metadata.get("source_date") else None
        ),
        source_url=source_url,
        source_key=source_key,
        source_content_sha256=incoming_source_hash,
        extraction_quality=incoming_quality,
        version_no=version_no,
        is_current=True,
        previous_version_id=previous_id,
        retrieved_at=datetime.now(timezone.utc),
    )
    db.add(notice)
    db.flush()
    _apply_extraction(notice, result)
    _store_fields(db, notice, result)
    db.flush()
    return notice, outcome


def fetch_all(
    db: Session,
    *,
    include_live_sources: bool = True,
    include_fixtures: bool = False,
    commit_each_source: bool = False,
    source_slugs: set[str] | None = None,
) -> dict:
    """Run configured sources and upsert notices by stable source identity.

    Fixture-backed fictional institutions are excluded by default and may only
    be included explicitly by isolated tests or the synthetic seed command.
    Idempotent for unchanged inputs. Returns per-institution outcomes.
    Scheduled callers may commit each institution separately so a later source
    failure or process restart does not discard earlier successful source work.
    """
    summary: dict = {"created": 0, "modified": 0, "skipped": 0, "errors": 0, "institutions": []}
    provenance_days: set[str] = set()
    from finalsay.adapters.live import create_live_adapter

    adapters = []
    if include_fixtures:
        # This module is excluded from production images with the synthetic
        # sources and seed data. Live ingestion leaves this branch disabled.
        from finalsay.adapters.fixture_sources import get_fixture_adapters

        adapters.extend((adapter, None) for adapter in get_fixture_adapters())
    configured_sources = []
    if include_live_sources:
        source_query = select(Institution).where(
            Institution.active.is_(True),
            Institution.scrape_enabled.is_(True),
            Institution.scrape_type != "fixture",
        )
        if source_slugs is not None:
            source_query = source_query.where(Institution.slug.in_(source_slugs))
        configured_sources = list(
            db.scalars(source_query.order_by(Institution.id)).all()
        )
    adapters.extend((None, source) for source in configured_sources)

    def commit_source_batch() -> None:
        if provenance_days:
            from finalsay.services.provenance import build_daily_merkle

            for day in sorted(provenance_days):
                build_daily_merkle(db, day)
            provenance_days.clear()
        db.commit()

    for adapter, configured_source in adapters:
        if configured_source is not None and adapter is None:
            try:
                adapter = create_live_adapter(configured_source)
                if getattr(adapter, "supports_backfill", False):
                    progress = db.get(ScrapeProgress, configured_source.id)
                    if progress is None:
                        progress = ScrapeProgress(institution_id=configured_source.id)
                        db.add(progress)
                        db.flush()
                    adapter.backfill_cursor = progress.cursor
                    adapter.backfill_complete = progress.backfill_complete
            except Exception as exc:  # noqa: BLE001 - report source config failures
                error = f"{type(exc).__name__}: {str(exc)[:500]}"
                summary["errors"] += 1
                summary["institutions"].append({
                    "slug": configured_source.slug,
                    "name": configured_source.name,
                    "found": 0,
                    "created": 0,
                    "modified": 0,
                    "skipped": 0,
                    "status": "error",
                    "error": error,
                })
                db.add(ScrapeRun(
                    institution_id=configured_source.id,
                    status="error",
                    found=0,
                    created=0,
                    modified=0,
                    unchanged=0,
                    error=error,
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                ))
                if commit_each_source:
                    commit_source_batch()
                continue
        assert adapter is not None
        institution = configured_source or get_or_create_institution(
            db, adapter.slug, adapter.name, adapter.base_url
        )
        found = created = modified = skipped = 0
        error = None
        started_at = datetime.now(timezone.utc)
        try:
            notices = adapter.fetch()
            found = len(notices)
            adapter_errors = getattr(adapter, "errors", [])
            if adapter_errors:
                error = " | ".join(str(item)[:250] for item in adapter_errors[:8])
            for raw in notices:
                _notice, outcome = upsert_official(db, raw, institution)
                if outcome == "created":
                    created += 1
                    provenance_days.add(_notice.created_at.strftime("%Y-%m-%d"))
                elif outcome == "modified":
                    modified += 1
                    provenance_days.add(_notice.created_at.strftime("%Y-%m-%d"))
                else:
                    skipped += 1
            if configured_source is not None and getattr(adapter, "supports_backfill", False):
                progress = db.get(ScrapeProgress, configured_source.id)
                if progress is None:
                    progress = ScrapeProgress(institution_id=configured_source.id)
                    db.add(progress)
                progress.cursor = adapter.backfill_next_cursor
                progress.backfill_complete = bool(adapter.backfill_complete)
                progress.updated_at = datetime.now(timezone.utc)
        except Exception as exc:  # keep other institution sources running
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
            if commit_each_source:
                # Keep this source atomic while retaining prior source commits.
                db.rollback()
                created = modified = skipped = 0
        status = ("partial" if found else "error") if error else "ok"
        summary["created"] += created
        summary["modified"] += modified
        summary["skipped"] += skipped
        summary["errors"] += int(status == "error")
        institution_result = {
            "slug": adapter.slug,
            "name": adapter.name,
            "found": found,
            "created": created,
            "modified": modified,
            "skipped": skipped,
            "status": status,
            "error": error,
        }
        summary["institutions"].append(institution_result)
        if configured_source is not None:
            db.add(ScrapeRun(
                institution_id=institution.id,
                status=status,
                found=found,
                created=created,
                modified=modified,
                unchanged=skipped,
                error=error,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            ))
        if commit_each_source:
            commit_source_batch()
    if provenance_days:
        from finalsay.services.provenance import build_daily_merkle

        for day in sorted(provenance_days):
            build_daily_merkle(db, day)
    return summary


def create_submission(
    db: Session,
    *,
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    image_bytes: bytes | None = None,
    institution_id: int | None = None,
    submitted_by: int | None = None,
) -> Notice:
    """Extract a student submission and persist it as a ``submission`` notice."""
    result = extraction.extract(text=text, pdf_bytes=pdf_bytes, image_bytes=image_bytes)
    title_match = _TITLE_RE.search(result.redacted_text)
    notice = Notice(
        kind="submission",
        institution_id=institution_id,
        submitted_by=submitted_by,
        title=title_match.group(1).strip()[:500] if title_match else None,
        extraction_quality="student_submitted",
        retrieved_at=datetime.now(timezone.utc),
    )
    db.add(notice)
    db.flush()
    _apply_extraction(notice, result)
    _store_fields(db, notice, result)
    db.flush()
    return notice


def publish_official(
    db: Session,
    *,
    text: str,
    institution: Institution,
    source_url: str | None = None,
) -> Notice:
    """Publish an issuer-provided official notice (extraction + content hash)."""
    raw = RawNotice(
        text=text,
        source_url=source_url,
        institution_slug=institution.slug,
        metadata={"extraction_quality": "issuer_submitted"},
    )
    notice, _created = upsert_official(db, raw, institution)
    return notice
