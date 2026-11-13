"""Curate unlabeled blind benchmark pairs from real source revisions."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finalsay.db import Base, SessionLocal, engine
from finalsay.models import BenchmarkPair, Institution, Notice


def curate_revision_pairs(db: Session, *, dry_run: bool = True) -> dict[str, int]:
    """Create unlabeled pairs from adjacent versions of real official notices.

    Newer records must explicitly link to their previous version, both records
    must have source text, and their institution must be an active live source.
    No model output or inferred gold label is copied into the benchmark.
    """
    older = Notice.__table__.alias("older")
    newer = Notice.__table__.alias("newer")
    candidates = db.execute(
        select(newer.c.id, older.c.id, older.c.redacted_text, newer.c.redacted_text)
        .select_from(
            newer.join(older, older.c.id == newer.c.previous_version_id).join(
                Institution, Institution.id == newer.c.institution_id
            )
        )
        .where(
            newer.c.kind == "official",
            newer.c.is_current.is_(True),
            older.c.kind == "official",
            older.c.institution_id == newer.c.institution_id,
            Institution.active.is_(True),
            Institution.scrape_type != "fixture",
            func.trim(func.coalesce(older.c.redacted_text, "")) != "",
            func.trim(func.coalesce(newer.c.redacted_text, "")) != "",
        )
        .order_by(newer.c.institution_id, newer.c.id)
    ).all()

    created = skipped = 0
    for newer_id, older_id, older_text, newer_text in candidates:
        existing = db.scalar(
            select(BenchmarkPair.id).where(
                BenchmarkPair.submission_id == older_id,
                BenchmarkPair.official_id == newer_id,
            )
        )
        if existing is not None:
            skipped += 1
            continue
        if dry_run:
            created += 1
            continue
        db.add(
            BenchmarkPair(
                submission_id=older_id,
                official_id=newer_id,
                submission_text=older_text,
                official_text=newer_text,
                gold_label=None,
            )
        )
        created += 1

    if not dry_run:
        db.commit()
    return {
        "eligible_pairs": len(candidates),
        "created_or_would_create": created,
        "already_curated": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create unlabeled benchmark pairs from actual official notice revisions."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the pairs. By default, only report the eligible count.",
    )
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        print(json.dumps(curate_revision_pairs(db, dry_run=not args.apply), indent=2))


if __name__ == "__main__":
    main()
