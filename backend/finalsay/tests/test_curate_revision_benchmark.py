from finalsay.models import BenchmarkPair, Institution, Notice
from finalsay.services.curate_revision_benchmark import curate_revision_pairs


def test_curates_actual_revision_pair_without_a_label_or_model_prediction(db_session):
    institution = Institution(
        name="Official Source University",
        slug="official-source-university",
        source_url="https://vtu.ac.in/",
        scrape_type="vtu_examination",
        scrape_enabled=True,
        active=True,
    )
    db_session.add(institution)
    db_session.flush()
    older = Notice(
        institution_id=institution.id,
        kind="official",
        title="Original exam schedule",
        source_key="schedule-1",
        redacted_text="The exams start on 10 December.",
        sha256="a" * 64,
        is_current=False,
    )
    db_session.add(older)
    db_session.flush()
    newer = Notice(
        institution_id=institution.id,
        kind="official",
        title="Revised exam schedule",
        source_key="schedule-1",
        redacted_text="The exams start on 15 December.",
        sha256="b" * 64,
        previous_version_id=older.id,
        is_current=True,
    )
    db_session.add(newer)
    db_session.commit()

    dry_run = curate_revision_pairs(db_session)
    assert dry_run == {
        "eligible_pairs": 1,
        "created_or_would_create": 1,
        "already_curated": 0,
    }
    assert db_session.query(BenchmarkPair).count() == 0

    applied = curate_revision_pairs(db_session, dry_run=False)
    pair = db_session.query(BenchmarkPair).one()
    assert applied["created_or_would_create"] == 1
    assert applied["already_curated"] == 0
    assert pair.submission_id == older.id
    assert pair.official_id == newer.id
    assert pair.submission_text == older.redacted_text
    assert pair.official_text == newer.redacted_text
    assert pair.gold_label is None

    repeated = curate_revision_pairs(db_session, dry_run=False)
    assert repeated["created_or_would_create"] == 0
    assert repeated["already_curated"] == 1
    assert db_session.query(BenchmarkPair).count() == 1
