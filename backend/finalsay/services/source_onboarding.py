"""Idempotently onboard the three selected official notice portals.

Run from backend/:
    python -m finalsay.services.source_onboarding          # show planned changes
    python -m finalsay.services.source_onboarding --apply # save source config

The command configures sources only; it does not fabricate notices. The normal
scrape service then polls them and writes scrape_run audit rows.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from finalsay.db import Base, SessionLocal, engine
from finalsay.models import Institution
from finalsay.migrations import run_migrations

OFFICIAL_SOURCES = (
    {
        "slug": "vtu",
        "name": "Visvesvaraya Technological University",
        "source_url": "https://vtu.ac.in/category/examination/",
        "scrape_type": "vtu_examination",
    },
    {
        "slug": "university-of-delhi",
        "name": "University of Delhi Examination",
        "source_url": "https://exam.du.ac.in/exam/index.php/notifications",
        "scrape_type": "du_examination",
    },
    {
        "slug": "university-of-mumbai",
        "name": "University of Mumbai",
        "source_url": "https://mu.ac.in/circular.php",
        "scrape_type": "mumbai_circulars",
    },
)


def onboard(*, apply: bool) -> list[str]:
    """Create/update the selected source rows. Safe to run repeatedly."""
    if apply:
        Base.metadata.create_all(bind=engine)
        run_migrations(engine)
    db = SessionLocal()
    outcomes: list[str] = []
    try:
        selected_slugs = {source["slug"] for source in OFFICIAL_SOURCES}
        if apply:
            for legacy in db.scalars(select(Institution).where(Institution.scrape_enabled.is_(True))).all():
                if legacy.slug not in selected_slugs:
                    legacy.scrape_enabled = False
                    legacy.active = False
                    outcomes.append(f"disable unselected live source {legacy.slug}")
        for source in OFFICIAL_SOURCES:
            existing = db.scalar(
                select(Institution).where(
                    (Institution.slug == source["slug"]) | (Institution.scrape_type == source["scrape_type"])
                )
            )
            action = "create" if existing is None else "update"
            outcomes.append(f"{action} {source['slug']} ({source['source_url']})")
            if not apply:
                continue
            if existing is None:
                existing = Institution(**source, scrape_enabled=False, active=True)
                db.add(existing)
            else:
                for field, value in source.items():
                    setattr(existing, field, value)
                existing.active = True
        if apply:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write source configuration to the currently configured database",
    )
    args = parser.parse_args()
    print("Selected official source onboarding:")
    for outcome in onboard(apply=args.apply):
        print(f"- {outcome}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to save these source profiles.")
    else:
        print("Saved. The running service will poll enabled sources on its next cycle.")
        print("Default poll interval: 7200 seconds (2 hours).")


if __name__ == "__main__":
    main()
