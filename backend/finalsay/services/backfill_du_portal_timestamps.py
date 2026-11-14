"""Correct DU listing-only publication dates from explicit portal timestamps.

Run a read-only preview by default. Use ``--apply`` to update current official
listing-only records when the catalog's posted timestamp was mistaken for a
deadline embedded in the notice title.
"""

from __future__ import annotations

import argparse
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.db import Base, SessionLocal, engine
from finalsay.models import Institution, Notice
from finalsay.services.notice_dates import parse_publication_date


_PORTAL_TIMESTAMP_RE = re.compile(
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4},\s*\d{1,2}:\d{2}\s*[AP]M\b",
    re.IGNORECASE,
)


def backfill_du_portal_timestamps(db: Session, *, dry_run: bool = True) -> dict:
    institution = db.scalar(
        select(Institution).where(Institution.slug == "university-of-delhi")
    )
    if institution is None:
        return {"matched": 0, "changed": 0, "records": []}

    notices = db.scalars(
        select(Notice)
        .where(
            Notice.institution_id == institution.id,
            Notice.kind == "official",
            Notice.is_current.is_(True),
            Notice.extraction_quality.in_(("listing_only", "unknown", "unextractable")),
        )
        .order_by(Notice.id)
    ).all()
    records = []
    changed = 0
    for notice in notices:
        text = notice.redacted_text or ""
        if not re.search(r"^\s*official listing\s*:", text, re.IGNORECASE | re.MULTILINE):
            continue
        timestamps = list(_PORTAL_TIMESTAMP_RE.finditer(text))
        if not timestamps:
            continue
        timestamp = " ".join(timestamps[-1].group(0).split())
        normalized = parse_publication_date(timestamp)
        if normalized is None or normalized == notice.published_on:
            continue
        records.append(
            {
                "notice_id": notice.id,
                "previous": notice.published_date,
                "portal_timestamp": timestamp,
                "normalized": normalized.isoformat(),
            }
        )
        if not dry_run:
            notice.published_date = timestamp
            notice.published_on = normalized
            changed += 1

    if not dry_run:
        db.flush()
    return {"matched": len(records), "changed": changed, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="persist corrected dates; omit for a read-only preview",
    )
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        result = backfill_du_portal_timestamps(db, dry_run=not args.apply)
        if args.apply:
            db.commit()
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
