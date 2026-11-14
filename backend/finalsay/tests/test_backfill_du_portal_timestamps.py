from datetime import date

from finalsay.models import Institution, Notice
from finalsay.services.backfill_du_portal_timestamps import backfill_du_portal_timestamps


def test_du_portal_timestamp_backfill_is_dry_run_by_default_and_corrects_deadline_date(db_session):
    institution = Institution(
        name="University of Delhi Examination",
        slug="university-of-delhi",
        active=True,
    )
    db_session.add(institution)
    db_session.flush()
    notice = Notice(
        kind="official",
        institution_id=institution.id,
        title="Exam form deadline extended up to 15.11.2026",
        published_date="15.11.2026",
        published_on=date(2026, 11, 15),
        redacted_text=(
            "Issued by: University of Delhi Examination\n"
            "Official listing: Exam form deadline 15.11.2026. "
            "13 Oct 2026, 07:43 AM STUDENT"
        ),
        extraction_quality="listing_only",
    )
    db_session.add(notice)
    db_session.flush()

    preview = backfill_du_portal_timestamps(db_session)
    assert preview["matched"] == 1
    assert preview["changed"] == 0
    assert notice.published_date == "15.11.2026"

    applied = backfill_du_portal_timestamps(db_session, dry_run=False)
    assert applied["matched"] == 1
    assert applied["changed"] == 1
    assert notice.published_date == "13 Oct 2026, 07:43 AM"
    assert notice.published_on.isoformat() == "2026-10-13"
