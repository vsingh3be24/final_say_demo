from sqlalchemy import select

from finalsay.models import (
    BenchmarkAnnotation,
    BenchmarkCompletion,
    BenchmarkPair,
    Institution,
    Notice,
    User,
)
from finalsay.services.clean_synthetic_data import clean, preview


def test_cleanup_removes_generated_benchmark_rows_but_preserves_human_real_pair(db_session):
    synthetic_institution = Institution(
        name="Northgate Institute",
        slug="northgate",
        source_url="https://northgate.example.test",
        scrape_type="fixture",
        active=True,
    )
    real_institution = Institution(
        name="Visvesvaraya Technological University",
        slug="vtu",
        source_url="https://vtu.ac.in/category/examination/",
        scrape_type="vtu_examination",
        active=True,
        scrape_enabled=True,
    )
    demo_student = User(
        email="student@finalsay.demo", hashed_password="hash", role="student"
    )
    demo_reviewer = User(
        email="reviewer@finalsay.demo", hashed_password="hash", role="reviewer"
    )
    real_student = User(
        email="student@university.edu", hashed_password="hash", role="student"
    )
    real_reviewer = User(
        email="reviewer@university.edu", hashed_password="hash", role="reviewer"
    )
    db_session.add_all(
        [
            synthetic_institution,
            real_institution,
            demo_student,
            demo_reviewer,
            real_student,
            real_reviewer,
        ]
    )
    db_session.flush()

    synthetic_official = Notice(
        kind="official",
        institution_id=synthetic_institution.id,
        title="Synthetic official notice",
        redacted_text="Synthetic official notice text",
        source_url="seed://northgate/official/1",
    )
    synthetic_submission = Notice(
        kind="submission",
        institution_id=synthetic_institution.id,
        submitted_by=demo_student.id,
        redacted_text="Synthetic student notice text",
        source_url="seed://northgate/submission/1",
    )
    real_official = Notice(
        kind="official",
        institution_id=real_institution.id,
        title="Real examination notice",
        redacted_text="University examination schedule",
        source_url="https://vtu.ac.in/notice.pdf",
    )
    real_submission = Notice(
        kind="submission",
        institution_id=real_institution.id,
        submitted_by=real_student.id,
        redacted_text="Student examination schedule question",
    )
    db_session.add_all(
        [synthetic_official, synthetic_submission, real_official, real_submission]
    )
    db_session.flush()

    generated_pair = BenchmarkPair(
        submission_id=synthetic_submission.id,
        official_id=synthetic_official.id,
        submission_text=synthetic_submission.redacted_text,
        official_text=synthetic_official.redacted_text,
    )
    real_pair = BenchmarkPair(
        submission_id=real_submission.id,
        official_id=real_official.id,
        submission_text=real_submission.redacted_text,
        official_text=real_official.redacted_text,
    )
    db_session.add_all([generated_pair, real_pair])
    db_session.flush()
    generated_pair_id = generated_pair.id
    real_pair_id = real_pair.id
    synthetic_official_id = synthetic_official.id
    real_official_id = real_official.id
    real_completion = BenchmarkCompletion(
        user_id=real_reviewer.id,
        pair_count=1,
        pair_fingerprint="real-corpus",
    )
    db_session.add_all(
        [
            BenchmarkAnnotation(
                pair_id=generated_pair.id,
                annotator="generated-seed-a",
                user_id=None,
                label="consistent",
            ),
            BenchmarkAnnotation(
                pair_id=real_pair.id,
                annotator=real_reviewer.email,
                user_id=real_reviewer.id,
                label="unresolved",
            ),
            BenchmarkCompletion(
                user_id=demo_reviewer.id,
                pair_count=1,
                pair_fingerprint="generated-corpus",
            ),
            real_completion,
        ]
    )
    db_session.commit()

    counts = preview()
    assert counts["benchmark_pairs_to_delete"] == 1
    assert counts["annotations_to_delete"] == 1
    assert counts["benchmark_completions_to_delete"] == 1

    result = clean()
    db_session.expire_all()

    assert result["benchmark_pairs"] == 1
    assert result["benchmark_annotations"] == 1
    assert result["benchmark_completions"] == 1
    assert db_session.get(BenchmarkPair, generated_pair_id) is None
    assert db_session.get(BenchmarkPair, real_pair_id) is not None
    human = db_session.scalar(
        select(BenchmarkAnnotation).where(
            BenchmarkAnnotation.pair_id == real_pair_id,
            BenchmarkAnnotation.user_id == real_reviewer.id,
        )
    )
    assert human is not None
    assert db_session.get(BenchmarkCompletion, real_completion.id) is not None
    assert db_session.get(Notice, synthetic_official_id) is None
    assert db_session.get(Notice, real_official_id) is not None
