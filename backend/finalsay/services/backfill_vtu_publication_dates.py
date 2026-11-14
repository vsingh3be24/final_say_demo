"""Recover missing VTU publication dates from persisted official listing text.

Run from ``backend/`` to preview, then pass ``--apply`` to write the dates:

    .venv/bin/python -m finalsay.services.backfill_vtu_publication_dates
    .venv/bin/python -m finalsay.services.backfill_vtu_publication_dates --apply

Only current official VTU notices with an empty ``published_date`` are
considered. A date is accepted only when it appears immediately after the
persisted ``Official listing:`` marker; event dates elsewhere in the body are
not treated as publication dates.
"""

from __future__ import annotations

import argparse
import re

from sqlalchemy import func, or_, select

from finalsay.adapters.live import _LISTING_DATE_RE
from finalsay.db import SessionLocal
from finalsay.models import Institution, Notice
from finalsay.services.notice_dates import parse_publication_date


_OFFICIAL_LISTING_RE = re.compile(r"(?im)^\s*Official listing:\s*([^\r\n]*)")


def date_from_official_listing(text: str | None) -> str | None:
    """Return the date at the start of the stored official listing, if any."""
    if not text:
        return None
    listing = _OFFICIAL_LISTING_RE.search(text)
    if not listing:
        return None
    date = _LISTING_DATE_RE.match(listing.group(1))
    return " ".join(date.group(1).split()) if date else None


def backfill(*, apply: bool = False) -> list[tuple[int, str, str]]:
    """Preview or set dates recoverable from official listing metadata."""
    db = SessionLocal()
    try:
        notices = db.scalars(
            select(Notice)
            .join(Institution, Institution.id == Notice.institution_id)
            .where(
                Institution.slug == "vtu",
                Notice.kind == "official",
                Notice.is_current.is_(True),
                or_(Notice.published_date.is_(None), func.trim(Notice.published_date) == ""),
            )
            .order_by(Notice.id)
        ).all()
        recovered: list[tuple[int, str, str]] = []
        for notice in notices:
            date = date_from_official_listing(notice.redacted_text)
            if not date:
                continue
            recovered.append((notice.id, notice.title or "(untitled)", date))
            if apply:
                notice.published_date = date[:80]
                notice.published_on = parse_publication_date(date)
        if apply:
            db.commit()
        return recovered
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the recoverable VTU dates")
    args = parser.parse_args()

    recovered = backfill(apply=args.apply)
    for notice_id, title, date in recovered:
        print(f"notice #{notice_id}: {date} — {title}")
    action = "Updated" if args.apply else "Would update"
    print(f"{action} {len(recovered)} current official VTU publication dates.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write these source-listed dates.")


if __name__ == "__main__":
    main()
