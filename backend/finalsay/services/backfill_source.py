"""Safely replay one configured source's resumable backfill.

Run from ``backend``. Preview the current cursor with:
    python -m finalsay.services.backfill_source --source university-of-delhi

Apply a bounded batch of source polls with:
    python -m finalsay.services.backfill_source --source university-of-delhi --cycles 10 --apply

The command uses the same cross-process poll lock, adapter, versioned upsert,
source run log, and progress cursor as scheduled ingestion. It never deletes
notices; unchanged records remain idempotent.
"""

from __future__ import annotations

import argparse
import json
import time

from sqlalchemy import select

from finalsay.db import SessionLocal
from finalsay.models import Institution, ScrapeProgress
from finalsay.services.ingestion import fetch_all
from finalsay.services.scrape_runtime import acquire_scrape_slot, release_scrape_slot

SOURCE_SLUGS = {"vtu", "university-of-delhi", "university-of-mumbai"}


def run_backfill(source_slug: str, *, cycles: int, reset: bool = False) -> dict:
    """Run a bounded, locked, source-specific cursor replay."""
    if source_slug not in SOURCE_SLUGS:
        raise ValueError(f"source must be one of {sorted(SOURCE_SLUGS)}")
    if not 1 <= cycles <= 30:
        raise ValueError("cycles must be between 1 and 30")
    if not acquire_scrape_slot():
        raise RuntimeError("another scheduled or manual source poll is active")

    results: list[dict] = []
    db = SessionLocal()
    try:
        institution = db.scalar(
            select(Institution).where(
                Institution.slug == source_slug,
                Institution.active.is_(True),
                Institution.scrape_enabled.is_(True),
            )
        )
        if institution is None:
            raise ValueError(f"no active configured source found for {source_slug}")
        progress = db.get(ScrapeProgress, institution.id)
        if progress is None:
            progress = ScrapeProgress(institution_id=institution.id)
            db.add(progress)
            db.flush()
        if reset:
            progress.cursor = None
            progress.backfill_complete = False
            db.commit()

        for cycle in range(cycles):
            before = (progress.cursor, progress.backfill_complete)
            summary = fetch_all(
                db,
                include_live_sources=True,
                include_fixtures=False,
                commit_each_source=True,
                source_slugs={source_slug},
            )
            result = next(
                (item for item in summary["institutions"] if item["slug"] == source_slug),
                None,
            )
            db.expire_all()
            progress = db.get(ScrapeProgress, institution.id)
            after = (progress.cursor, progress.backfill_complete)
            results.append(
                {
                    "cycle": cycle + 1,
                    "source": source_slug,
                    "status": result["status"] if result else "not_polled",
                    "found": result["found"] if result else 0,
                    "created": result["created"] if result else 0,
                    "modified": result["modified"] if result else 0,
                    "unchanged": result["skipped"] if result else 0,
                    "error": (result["error"] or "")[:500] if result else None,
                    "cursor": progress.cursor,
                    "backfill_complete": progress.backfill_complete,
                }
            )
            if not result or result["status"] == "error":
                break
            if progress.backfill_complete or after == before:
                break
            if cycle + 1 < cycles:
                time.sleep(2)

        db.commit()
        return {"source": source_slug, "cycles": results}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        release_scrape_slot()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_SLUGS))
    parser.add_argument("--cycles", type=int, default=1, help="maximum bounded fetches (1–30)")
    parser.add_argument("--reset", action="store_true", help="restart this source cursor from its first page")
    parser.add_argument("--apply", action="store_true", help="poll and persist the selected real source")
    args = parser.parse_args()
    if not 1 <= args.cycles <= 30:
        parser.error("--cycles must be between 1 and 30")
    if args.reset and not args.apply:
        parser.error("--reset requires --apply")
    if not args.apply:
        with SessionLocal() as db:
            institution = db.scalar(select(Institution).where(Institution.slug == args.source))
            progress = db.get(ScrapeProgress, institution.id) if institution else None
            print(json.dumps({
                "source": args.source,
                "active": bool(institution and institution.active and institution.scrape_enabled),
                "cursor": progress.cursor if progress else None,
                "backfill_complete": progress.backfill_complete if progress else False,
                "preview_only": True,
            }, sort_keys=True))
        print("Preview only. Add --apply to perform the source polls.")
        return 0
    try:
        print(json.dumps(run_backfill(args.source, cycles=args.cycles, reset=args.reset), sort_keys=True))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"source": args.source, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
