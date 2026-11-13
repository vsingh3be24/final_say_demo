"""Refresh legacy official-document text without rewriting notice versions."""

from __future__ import annotations

import hashlib
import argparse
import json
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.adapters.live import create_live_adapter
from finalsay.db import Base, SessionLocal, engine
from finalsay.models import (
    Institution,
    Notice,
    NoticeDocumentExtraction,
)
from finalsay.services import extraction


def refresh_unknown_document_extractions(
    db: Session,
    *,
    per_institution: int = 2,
    dry_run: bool = False,
) -> dict:
    """Re-fetch a bounded number of current unknown documents per live source.

    Re-extracted text is stored as a separately hashed sidecar. It never
    mutates ``Notice.redacted_text``, ``Notice.sha256`` or version history.
    External-host links (including Delhi's Google Drive files) are skipped
    before any request is made.
    """
    if per_institution < 1:
        raise ValueError("per_institution must be at least 1")

    summary = {
        "stored": 0,
        "would_store": 0,
        "skipped_external": 0,
        "skipped_unextractable": 0,
        "errors": [],
        "institutions": [],
    }
    institutions = db.scalars(
        select(Institution)
        .where(
            Institution.active.is_(True),
            Institution.scrape_enabled.is_(True),
            Institution.scrape_type != "fixture",
        )
        .order_by(Institution.id)
    ).all()

    for institution in institutions:
        try:
            adapter = create_live_adapter(institution)
        except Exception as exc:  # noqa: BLE001 - report and continue other sources
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
            summary["errors"].append(f"{institution.slug}: {error}")
            summary["institutions"].append(
                {
                    "institution_id": institution.id,
                    "slug": institution.slug,
                    "stored": 0,
                    "would_store": 0,
                    "attempted": 0,
                    "skipped_external": 0,
                    "skipped_unextractable": 0,
                    "errors": [error],
                }
            )
            continue

        notices = db.scalars(
            select(Notice)
            .where(
                Notice.institution_id == institution.id,
                Notice.kind == "official",
                Notice.is_current.is_(True),
                Notice.extraction_quality == "unknown",
            )
            .order_by(Notice.id)
        ).all()
        existing_ids = set(
            db.scalars(
                select(NoticeDocumentExtraction.notice_id).where(
                    NoticeDocumentExtraction.notice_id.in_(
                        [notice.id for notice in notices]
                    )
                )
            ).all()
        ) if notices else set()

        stored = would_store = skipped_external = skipped_unextractable = 0
        institution_errors: list[str] = []
        attempted = 0
        for notice in notices:
            if notice.id in existing_ids:
                continue
            source_url = notice.source_url or ""
            if urlsplit(source_url).hostname not in adapter.allowed_hosts:
                skipped_external += 1
                continue
            if attempted >= per_institution:
                break
            attempted += 1

            try:
                if institution.scrape_type == "vtu_examination":
                    raw = adapter.fetch_post(
                        source_url, notice.title or "", listing_text=""
                    )
                    if notice.published_date:
                        raw.metadata["source_date"] = notice.published_date
                else:
                    raw = adapter._document(
                        source_url,
                        notice.title or "Official notice",
                        date=notice.published_date,
                        external_id=notice.source_key,
                    )
                if (
                    raw is None
                    or raw.metadata.get("extraction_quality") != "extracted"
                    or not raw.text.strip()
                ):
                    skipped_unextractable += 1
                    continue

                redacted_text = extraction.extract(text=raw.text).redacted_text
                if not redacted_text.strip():
                    skipped_unextractable += 1
                    continue

                if dry_run:
                    would_store += 1
                    continue

                text_hash = hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
                existing = db.scalar(
                    select(NoticeDocumentExtraction).where(
                        NoticeDocumentExtraction.notice_id == notice.id,
                        NoticeDocumentExtraction.source_url == source_url,
                    )
                )
                if existing is None:
                    db.add(
                        NoticeDocumentExtraction(
                            notice_id=notice.id,
                            source_url=source_url,
                            extracted_text=redacted_text,
                            extracted_text_sha256=text_hash,
                            extraction_quality="extracted",
                            extraction_method="official_source_adapter",
                        )
                    )
                else:
                    existing.extracted_text = redacted_text
                    existing.extracted_text_sha256 = text_hash
                    existing.extraction_quality = "extracted"
                notice.extraction_quality = "extracted"
                stored += 1
            except Exception as exc:  # noqa: BLE001 - one source document must not stop the batch
                error = f"notice {notice.id}: {type(exc).__name__}: {str(exc)[:160]}"
                institution_errors.append(error)
                summary["errors"].append(f"{institution.slug}: {error}")

        summary["stored"] += stored
        summary["would_store"] += would_store
        summary["skipped_external"] += skipped_external
        summary["skipped_unextractable"] += skipped_unextractable
        summary["institutions"].append(
            {
                "institution_id": institution.id,
                "slug": institution.slug,
                "stored": stored,
                "would_store": would_store,
                "attempted": attempted,
                "skipped_external": skipped_external,
                "skipped_unextractable": skipped_unextractable,
                "errors": institution_errors,
            }
        )
        if not dry_run:
            db.flush()

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh a bounded batch of legacy official document extractions."
    )
    parser.add_argument(
        "--limit-per-institution", type=int, default=2,
        help="maximum documents to fetch per configured source (default: 2)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="store redacted extracted text in sidecar rows; omit for a read-only dry run",
    )
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        result = refresh_unknown_document_extractions(
            db,
            per_institution=args.limit_per_institution,
            dry_run=not args.apply,
        )
        if args.apply:
            db.commit()
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
