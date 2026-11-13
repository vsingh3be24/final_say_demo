"""Remove generated/demo rows from the local product database.

Usage from backend/:
    python -m finalsay.services.clean_synthetic_data
    python -m finalsay.services.clean_synthetic_data --apply --confirm

This command is intentionally restricted to SQLite. It removes the known
fictional institutions, seed-marked notices, notices owned by seeded .demo
accounts, the synthetic test notice hosted on example.test, and the generated
benchmark corpus. Real scraped official notices are retained. Existing real
sources outside the selected three are retained but deactivated.
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import func, or_, select, update

from finalsay.db import SessionLocal, engine
from finalsay.models import (
    AnchorBlock,
    BenchmarkAnnotation,
    BenchmarkCompletion,
    BenchmarkPair,
    Institution,
    IssuerMembership,
    MerkleProof,
    MerkleRoot,
    Notice,
    NoticeField,
    RelationEdge,
    ReviewCase,
    ScrapeRun,
    User,
)
from finalsay.services.provenance import build_all_missing_roots

FICTIONAL_INSTITUTION_SLUGS = {"northgate", "riverside", "summit"}
SELECTED_SOURCE_SLUGS = {"vtu", "university-of-delhi", "university-of-mumbai"}
DEMO_EMAIL_SUFFIX = "@finalsay.demo"


def _targets(db):
    fictional_institutions = list(
        db.scalars(
            select(Institution).where(Institution.slug.in_(FICTIONAL_INSTITUTION_SLUGS))
        )
    )
    demo_users = list(
        db.scalars(select(User).where(User.email.like(f"%{DEMO_EMAIL_SUFFIX}")))
    )
    demo_user_ids = {user.id for user in demo_users}
    notice_query = select(Notice.id)
    conditions = []
    if fictional_institutions:
        conditions.append(
            Notice.institution_id.in_([institution.id for institution in fictional_institutions])
        )
    conditions.extend(
        [
            Notice.source_url.like("seed://%"),
            Notice.source_url.like("https://example.test/%"),
        ]
    )
    if demo_user_ids:
        conditions.append(Notice.submitted_by.in_(demo_user_ids))
    notice_ids = set(db.scalars(notice_query.where(or_(*conditions)))) if conditions else set()
    edges = list(
        db.scalars(
            select(RelationEdge).where(
                or_(
                    RelationEdge.src_notice_id.in_(notice_ids or {-1}),
                    RelationEdge.dst_notice_id.in_(notice_ids or {-1}),
                )
            )
        )
    )
    edge_ids = {edge.id for edge in edges}
    return fictional_institutions, demo_users, notice_ids, edge_ids


def _synthetic_benchmark_pair_ids(db, notice_ids: set[int]) -> set[int]:
    """Find benchmark pairs tied to notices the cleanup will remove."""
    if not notice_ids:
        return set()
    return set(
        db.scalars(
            select(BenchmarkPair.id).where(
                or_(
                    BenchmarkPair.submission_id.in_(notice_ids),
                    BenchmarkPair.official_id.in_(notice_ids),
                )
            )
        )
    )


def preview() -> dict[str, object]:
    with SessionLocal() as db:
        institutions, users, notice_ids, edge_ids = _targets(db)
        benchmark_pair_ids = _synthetic_benchmark_pair_ids(db, notice_ids)
        demo_user_ids = {user.id for user in users}
        case_count = db.scalar(
            select(func.count(ReviewCase.id)).where(
                or_(
                    ReviewCase.edge_id.in_(edge_ids or {-1}),
                    ReviewCase.resolved_by.in_({user.id for user in users} or {-1}),
                )
            )
        ) or 0
        official_keep = db.scalar(
            select(func.count(Notice.id)).where(
                Notice.kind == "official",
                Notice.is_current.is_(True),
                Notice.id.not_in(notice_ids or {-1}),
            )
        ) or 0
        return {
            "fictional_institutions": [item.slug for item in institutions],
            "demo_accounts": [user.email for user in users],
            "notices_to_delete": len(notice_ids),
            "benchmark_pairs_to_delete": len(benchmark_pair_ids),
            "annotations_to_delete": db.scalar(
                select(func.count(BenchmarkAnnotation.id)).where(
                    or_(
                        BenchmarkAnnotation.pair_id.in_(benchmark_pair_ids or {-1}),
                        BenchmarkAnnotation.user_id.is_(None),
                    )
                )
            ) or 0,
            "benchmark_completions_to_delete": db.scalar(
                select(func.count(BenchmarkCompletion.id)).where(
                    BenchmarkCompletion.user_id.in_(demo_user_ids or {-1})
                )
            ) or 0,
            "edges_to_delete": len(edge_ids),
            "review_cases_to_delete": case_count,
            "current_official_notices_to_keep": official_keep,
        }


def clean() -> dict[str, int]:
    """Delete generated rows, deactivate unselected sources, and rebuild roots."""
    db = SessionLocal()
    try:
        fictional, demo_users, notice_ids, edge_ids = _targets(db)
        demo_user_ids = {user.id for user in demo_users}
        benchmark_pair_ids = _synthetic_benchmark_pair_ids(db, notice_ids)
        summary = Counter()

        # Remove generated labels and pairs tied to synthetic notices, while
        # preserving account-bound human annotations on real benchmark pairs.
        summary["benchmark_annotations"] = db.query(BenchmarkAnnotation).filter(
            or_(
                BenchmarkAnnotation.pair_id.in_(benchmark_pair_ids or {-1}),
                BenchmarkAnnotation.user_id.is_(None),
            )
        ).delete(synchronize_session=False)
        summary["benchmark_pairs"] = db.query(BenchmarkPair).filter(
            BenchmarkPair.id.in_(benchmark_pair_ids or {-1})
        ).delete(synchronize_session=False)
        summary["benchmark_completions"] = db.query(BenchmarkCompletion).filter(
            BenchmarkCompletion.user_id.in_(demo_user_ids or {-1})
        ).delete(synchronize_session=False)

        if edge_ids:
            summary["review_cases"] = db.query(ReviewCase).filter(
                or_(
                    ReviewCase.edge_id.in_(edge_ids),
                    ReviewCase.resolved_by.in_(demo_user_ids or {-1}),
                )
            ).delete(synchronize_session=False)
            summary["edges"] = db.query(RelationEdge).filter(
                RelationEdge.id.in_(edge_ids)
            ).delete(synchronize_session=False)
        else:
            summary["review_cases"] = db.query(ReviewCase).filter(
                ReviewCase.resolved_by.in_(demo_user_ids or {-1})
            ).delete(synchronize_session=False)
            summary["edges"] = 0

        # Rebuildable local roots included generated notices. Remove the old
        # local proofs/roots/chain, then create fresh commitments for retained
        # real official notices only. No confirmed external chain transaction
        # is present in this database.
        summary["merkle_proofs"] = db.query(MerkleProof).delete(synchronize_session=False)
        summary["merkle_roots"] = db.query(MerkleRoot).delete(synchronize_session=False)
        summary["anchor_blocks"] = db.query(AnchorBlock).delete(synchronize_session=False)

        if notice_ids:
            db.execute(
                update(Notice)
                .where(Notice.previous_version_id.in_(notice_ids))
                .values(previous_version_id=None)
            )
            summary["notice_fields"] = db.query(NoticeField).filter(
                NoticeField.notice_id.in_(notice_ids)
            ).delete(synchronize_session=False)
            summary["notices"] = db.query(Notice).filter(
                Notice.id.in_(notice_ids)
            ).delete(synchronize_session=False)
        else:
            summary["notice_fields"] = 0
            summary["notices"] = 0

        if fictional:
            institution_ids = [institution.id for institution in fictional]
            summary["scrape_runs"] = db.query(ScrapeRun).filter(
                ScrapeRun.institution_id.in_(institution_ids)
            ).delete(synchronize_session=False)
            summary["institutions"] = db.query(Institution).filter(
                Institution.id.in_(institution_ids)
            ).delete(synchronize_session=False)
        else:
            summary["scrape_runs"] = 0
            summary["institutions"] = 0

        if demo_user_ids:
            summary["issuer_memberships"] = db.query(IssuerMembership).filter(
                IssuerMembership.user_id.in_(demo_user_ids)
            ).delete(synchronize_session=False)
            summary["users"] = db.query(User).filter(
                User.id.in_(demo_user_ids)
            ).delete(synchronize_session=False)
        else:
            summary["issuer_memberships"] = 0
            summary["users"] = 0

        summary["deactivated_sources"] = db.query(Institution).filter(
            Institution.scrape_type != "fixture",
            Institution.slug.not_in(SELECTED_SOURCE_SLUGS),
            Institution.active.is_(True),
        ).update(
            {Institution.active: False, Institution.scrape_enabled: False},
            synchronize_session=False,
        )
        db.flush()
        summary["rebuilt_roots"] = len(build_all_missing_roots(db))
        db.commit()
        return dict(summary)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the data cleanup")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm removal of generated demo data from the configured local database",
    )
    args = parser.parse_args()
    print("Synthetic-data cleanup preview:")
    for key, value in preview().items():
        print(f"- {key}: {value}")
    if not args.apply:
        print("Preview only. Use --apply --confirm to delete these generated rows.")
        return
    if not args.confirm:
        parser.error("--apply requires --confirm")
    if engine.dialect.name != "sqlite":
        parser.error("this cleanup command is restricted to SQLite databases")
    print("Cleanup results:")
    for key, value in clean().items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
