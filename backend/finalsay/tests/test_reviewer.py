"""Reviewer tests: resolve updates edge + closes case; queue lists unresolved
cases; Cohen's kappa matches a hand-computed value; benchmark annotate flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from finalsay.models import BenchmarkAnnotation, BenchmarkPair, Notice, RelationEdge, ReviewCase
from finalsay.services import comparison
from finalsay.services.kappa import cohen_kappa


def _token(client, make_user, email, password, role):
    # Public register only creates students; privileged roles are provisioned
    # directly (as the seed does), then authenticated via the normal flow.
    if role == "student":
        client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
    else:
        make_user(email, password, role)
    resp = client.post(
        "/api/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- Cohen's kappa math -------------------------------------------------------

def test_kappa_hand_computed_value():
    """Hand-computed example.

    A = [yes, yes, no, no, yes], B = [yes, no, no, no, yes].
    observed agreement p_o = 4/5 = 0.8.
    marginals: A(yes)=3/5, A(no)=2/5; B(yes)=2/5, B(no)=3/5.
    p_e = (0.6*0.4) + (0.4*0.6) = 0.24 + 0.24 = 0.48.
    kappa = (0.8 - 0.48) / (1 - 0.48) = 0.32 / 0.52 = 0.6153846...
    """
    a = ["yes", "yes", "no", "no", "yes"]
    b = ["yes", "no", "no", "no", "yes"]
    assert abs(cohen_kappa(a, b) - 0.6153846153846154) < 0.001


def test_kappa_perfect_agreement():
    a = ["consistent", "superseded", "cancelled"]
    assert abs(cohen_kappa(a, a) - 1.0) < 1e-9


# --- Reviewer resolve ---------------------------------------------------------

def _make_unresolved_case(db):
    """Create a submission that gates to unresolved (no candidate -> unresolved)."""
    submission = Notice(
        kind="submission",
        institution_id=999,
        redacted_text="An ambiguous circular with unclear details.",
    )
    db.add(submission)
    db.flush()
    outcome = comparison.classify_submission(db, submission)
    db.commit()
    assert outcome.review_case is not None
    return outcome.review_case, outcome.edge


def test_resolve_updates_edge_and_closes_case(client: TestClient, db_session, make_user):
    case, edge = _make_unresolved_case(db_session)

    reviewer = _token(client, make_user, "rev1@example.com", "s3cret1", "reviewer")
    resp = client.post(
        f"/api/reviewer/cases/{case.id}/resolve",
        json={"label": "superseded"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "superseded"
    assert body["edge_status"] == "corrected"  # changed from unresolved
    assert body["case_status"] == "closed"

    db_session.expire_all()
    refreshed_edge = db_session.get(RelationEdge, edge.id)
    refreshed_case = db_session.get(ReviewCase, case.id)
    assert refreshed_edge.label == "superseded"
    assert refreshed_edge.status == "corrected"
    assert refreshed_case.status == "closed"
    assert refreshed_case.resolved_label == "superseded"


def test_resolve_confirmed_when_label_unchanged(client: TestClient, db_session, make_user):
    case, edge = _make_unresolved_case(db_session)
    reviewer = _token(client, make_user, "rev2@example.com", "s3cret1", "reviewer")
    resp = client.post(
        f"/api/reviewer/cases/{case.id}/resolve",
        json={"label": "unresolved"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200
    assert resp.json()["edge_status"] == "confirmed"


def test_queue_lists_open_cases(client: TestClient, db_session, make_user):
    _make_unresolved_case(db_session)
    reviewer = _token(client, make_user, "rev3@example.com", "s3cret1", "reviewer")
    resp = client.get("/api/reviewer/queue", headers=_auth(reviewer))
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 1
    assert items[0]["status"] == "open"
    assert "submission" in items[0]


def test_queue_requires_reviewer_role(client: TestClient, make_user):
    student = _token(client, make_user, "stud7@example.com", "s3cret1", "student")
    resp = client.get("/api/reviewer/queue", headers=_auth(student))
    assert resp.status_code == 403


# --- Benchmark + kappa endpoint ----------------------------------------------

def test_benchmark_annotate_and_kappa(client: TestClient, db_session, make_user):
    # Both reviewer accounts receive the same corpus; seed labels are not exposed.
    officials, subs = [], []
    for i in range(5):
        off = Notice(kind="official", institution_id=1, redacted_text=f"official {i}")
        sub = Notice(kind="submission", institution_id=1, redacted_text=f"submission {i}")
        db_session.add_all([off, sub])
        db_session.flush()
        officials.append(off)
        subs.append(sub)
    pairs = []
    for off, sub in zip(officials, subs):
        pair = BenchmarkPair(
            submission_id=sub.id,
            official_id=off.id,
            submission_text=f"Submission text {sub.id}",
            official_text=f"Official text {off.id}",
        )
        db_session.add(pair)
        db_session.flush()
        pairs.append(pair)
        db_session.add(
            BenchmarkAnnotation(
                pair_id=pair.id,
                annotator="generated-seed-a",
                user_id=None,
                label="cancelled",
            )
        )
    db_session.commit()

    reviewer_a = _token(client, make_user, "ann-a@example.com", "s3cret1", "reviewer")
    reviewer_b = _token(client, make_user, "ann-b@example.com", "s3cret1", "reviewer")
    admin = _token(client, make_user, "bench-admin@example.com", "s3cret1", "admin")

    listing = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_a))
    assert listing.status_code == 200
    assert len(listing.json()) == 5
    assert all(pair["your_label"] is None for pair in listing.json())
    assert "annotations" not in listing.json()[0]

    # Admins can manage sources and review cases but cannot count as annotators.
    assert client.get("/api/reviewer/benchmark/pairs", headers=_auth(admin)).status_code == 403
    assert client.get("/api/reviewer/benchmark/kappa", headers=_auth(admin)).status_code == 403

    hidden = client.get("/api/reviewer/benchmark/kappa", headers=_auth(reviewer_a))
    assert hidden.status_code == 200
    assert hidden.json()["ready"] is False
    assert hidden.json()["kappa"] is None
    assert hidden.json()["annotators"] == []

    # A client cannot submit an annotator name to impersonate another reviewer.
    forged = client.post(
        "/api/reviewer/benchmark/annotate",
        json={"pair_id": pairs[0].id, "label": "consistent", "annotator": "ann-b@example.com"},
        headers=_auth(reviewer_a),
    )
    assert forged.status_code == 422

    labels_a = ["consistent", "consistent", "contradictory", "contradictory", "consistent"]
    labels_b = ["consistent", "contradictory", "contradictory", "contradictory", "consistent"]
    for pair, label_a in zip(pairs, labels_a):
        saved = client.post(
            "/api/reviewer/benchmark/annotate",
            json={"pair_id": pair.id, "label": label_a},
            headers=_auth(reviewer_a),
        )
        assert saved.status_code == 200, saved.text
        # B can see the pair text but neither A's label nor generated seed labels.
        b_view = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_b))
        assert b_view.status_code == 200
        assert all(item["your_label"] is None for item in b_view.json())

    incomplete = client.post("/api/reviewer/benchmark/complete", headers=_auth(reviewer_b))
    assert incomplete.status_code == 409
    assert "5 remain" in incomplete.json()["detail"]

    complete_a = client.post("/api/reviewer/benchmark/complete", headers=_auth(reviewer_a))
    assert complete_a.status_code == 200, complete_a.text
    still_hidden = client.get("/api/reviewer/benchmark/kappa", headers=_auth(reviewer_a))
    assert still_hidden.json()["ready"] is False
    assert still_hidden.json()["kappa"] is None

    locked = client.post(
        "/api/reviewer/benchmark/annotate",
        json={"pair_id": pairs[0].id, "label": "unresolved"},
        headers=_auth(reviewer_a),
    )
    assert locked.status_code == 409

    for pair, label_b in zip(pairs, labels_b):
        saved = client.post(
            "/api/reviewer/benchmark/annotate",
            json={"pair_id": pair.id, "label": label_b},
            headers=_auth(reviewer_b),
        )
        assert saved.status_code == 200, saved.text
    complete_b = client.post("/api/reviewer/benchmark/complete", headers=_auth(reviewer_b))
    assert complete_b.status_code == 200, complete_b.text

    kappa_resp = client.get("/api/reviewer/benchmark/kappa", headers=_auth(reviewer_a))
    assert kappa_resp.status_code == 200, kappa_resp.text
    body = kappa_resp.json()
    assert body["ready"] is True
    assert body["pairs_compared"] == 5
    assert body["kappa"] == 0.615385
    assert body["is_seed_demo"] is False
    assert set(body["annotators"]) == {"ann-a@example.com", "ann-b@example.com"}

    own_a = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_a)).json()
    own_b = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_b)).json()
    assert [pair["your_label"] for pair in own_a] == labels_a
    assert [pair["your_label"] for pair in own_b] == labels_b


def test_admin_curates_only_real_student_candidate_pair_for_blind_review(
    client: TestClient, db_session, make_user
):
    from finalsay.models import Institution

    institution = Institution(
        name="Visvesvaraya Technological University",
        slug="vtu",
        source_url="https://vtu.ac.in/category/examination/",
        scrape_type="vtu_examination",
        scrape_enabled=True,
        active=True,
    )
    db_session.add(institution)
    db_session.commit()
    student = make_user("benchmark-student@example.com", "s3cret1", "student")
    official = Notice(
        kind="official",
        institution_id=institution.id,
        is_current=True,
        redacted_text="Official exam schedule: odd semester exams begin 15 December.",
        source_url="https://vtu.ac.in/2026/11/notice/",
    )
    submission = Notice(
        kind="submission",
        institution_id=institution.id,
        submitted_by=student.id,
        redacted_text="Forwarded exam schedule says exams begin 20 December.",
    )
    db_session.add_all([official, submission])
    db_session.flush()
    db_session.add(
        RelationEdge(
            src_notice_id=submission.id,
            dst_notice_id=official.id,
            label="unresolved",
            confidence=0.51,
            rationale="held for review",
            model="semantic-test",
            status="unresolved",
        )
    )
    db_session.commit()

    admin_token = _token(client, make_user, "benchmark-admin@example.com", "s3cret1", "admin")
    reviewer_a = _token(client, make_user, "blind-a@example.com", "s3cret1", "reviewer")
    reviewer_b = _token(client, make_user, "blind-b@example.com", "s3cret1", "reviewer")
    body = {"submission_id": submission.id, "official_id": official.id}

    forbidden = client.post("/api/admin/benchmark/pairs", json=body, headers=_auth(reviewer_a))
    assert forbidden.status_code == 403

    created = client.post("/api/admin/benchmark/pairs", json=body, headers=_auth(admin_token))
    assert created.status_code == 201, created.text
    assert created.json()["created"] is True
    pair_id = created.json()["id"]
    pair = db_session.get(BenchmarkPair, pair_id)
    assert pair is not None
    assert pair.gold_label is None
    assert pair.submission_text == submission.redacted_text
    assert pair.official_text == official.redacted_text

    repeated = client.post("/api/admin/benchmark/pairs", json=body, headers=_auth(admin_token))
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {"id": pair_id, **body, "created": False}

    view_a = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_a))
    view_b = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_b))
    assert view_a.status_code == view_b.status_code == 200
    assert view_a.json()[0]["your_label"] is None
    assert view_b.json()[0]["your_label"] is None
    assert view_a.json()[0]["submission_text"] == view_b.json()[0]["submission_text"]


def test_admin_benchmark_curation_rejects_seeded_demo_submission(
    client: TestClient, db_session, make_user
):
    from finalsay.models import Institution

    institution = Institution(
        name="University of Delhi Examination",
        slug="university-of-delhi",
        source_url="https://exam.du.ac.in/exam/notifications",
        scrape_type="du_examination",
        active=True,
    )
    db_session.add(institution)
    db_session.commit()
    student = make_user("demo-benchmark-student@example.com", "s3cret1", "student")
    official = Notice(
        kind="official", institution_id=institution.id, is_current=True,
        redacted_text="A real current examination notice.",
    )
    submission = Notice(
        kind="submission", institution_id=institution.id, submitted_by=student.id,
        source_url="seed://submission/demo",
        redacted_text="A generated synthetic test submission.",
    )
    db_session.add_all([official, submission])
    db_session.flush()
    db_session.add(
        RelationEdge(
            src_notice_id=submission.id,
            dst_notice_id=official.id,
            label="consistent",
            confidence=0.9,
            model="test",
            status="auto",
        )
    )
    db_session.commit()
    admin_token = _token(client, make_user, "curation-admin@example.com", "s3cret1", "admin")

    response = client.post(
        "/api/admin/benchmark/pairs",
        json={"submission_id": submission.id, "official_id": official.id},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422
    assert "seed/demo" in response.json()["detail"]
    assert db_session.query(BenchmarkPair).count() == 0


def test_two_reviewers_see_and_label_the_same_real_source_revision_pair(
    client: TestClient, db_session, make_user
):
    from finalsay.models import Institution

    institution = Institution(
        name="University of Delhi Examination",
        slug="university-of-delhi",
        source_url="https://exam.du.ac.in/exam/index.php/notifications",
        scrape_type="du_examination",
        active=True,
        scrape_enabled=True,
    )
    db_session.add(institution)
    db_session.flush()
    older = Notice(
        kind="official",
        institution_id=institution.id,
        title="Original examination schedule",
        source_key="real-source-revision-1",
        redacted_text="The examination begins on 10 December.",
        sha256="a" * 64,
        is_current=False,
    )
    db_session.add(older)
    db_session.flush()
    newer = Notice(
        kind="official",
        institution_id=institution.id,
        title="Revised examination schedule",
        source_key=older.source_key,
        redacted_text="The examination begins on 15 December.",
        sha256="b" * 64,
        previous_version_id=older.id,
        is_current=True,
    )
    db_session.add(newer)
    db_session.flush()
    pair = BenchmarkPair(
        submission_id=older.id,
        official_id=newer.id,
        submission_text=older.redacted_text,
        official_text=newer.redacted_text,
        gold_label=None,
    )
    db_session.add(pair)
    db_session.commit()

    reviewer_a = _token(client, make_user, "revision-a@example.com", "s3cret1", "reviewer")
    reviewer_b = _token(client, make_user, "revision-b@example.com", "s3cret1", "reviewer")
    pair_a = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_a)).json()[0]
    pair_b = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer_b)).json()[0]
    assert pair_a["pair_kind"] == pair_b["pair_kind"] == "source_revision"
    assert pair_a["left_title"] == "Original examination schedule"
    assert pair_a["right_title"] == "Revised examination schedule"
    assert pair_a["your_label"] is pair_b["your_label"] is None

    saved_a = client.post(
        "/api/reviewer/benchmark/annotate",
        json={"pair_id": pair.id, "label": "superseded"},
        headers=_auth(reviewer_a),
    )
    saved_b = client.post(
        "/api/reviewer/benchmark/annotate",
        json={"pair_id": pair.id, "label": "corrected"},
        headers=_auth(reviewer_b),
    )
    assert saved_a.status_code == saved_b.status_code == 200
    labels = {
        annotation.user_id: annotation.label
        for annotation in db_session.query(BenchmarkAnnotation)
        .filter(BenchmarkAnnotation.pair_id == pair.id)
        .all()
    }
    assert labels == {
        make_user("revision-a@example.com", "s3cret1", "reviewer").id: "superseded",
        make_user("revision-b@example.com", "s3cret1", "reviewer").id: "corrected",
    }
def test_admin_benchmark_candidate_list_is_real_blind_and_idempotent(
    client: TestClient, db_session, make_user
):
    from finalsay.models import Institution

    institution = Institution(
        name="University of Delhi Examination",
        slug="university-of-delhi",
        source_url="https://exam.du.ac.in/exam/notifications",
        scrape_type="du_examination",
        active=True,
    )
    fixture_institution = Institution(
        name="Test Fixture University",
        slug="fixture-university",
        source_url="https://fixture.example/notices",
        scrape_type="fixture",
        active=True,
    )
    db_session.add_all([institution, fixture_institution])
    db_session.commit()
    student = make_user("curation-student@example.com", "s3cret1", "student")
    official = Notice(
        kind="official",
        institution_id=institution.id,
        is_current=True,
        title="Real official schedule",
        published_date="2026-11-01",
        redacted_text="The official odd semester examination schedule.",
        source_url="https://exam.du.ac.in/exam/notice-1.pdf",
    )
    submission = Notice(
        kind="submission",
        institution_id=institution.id,
        submitted_by=student.id,
        title="Student schedule copy",
        redacted_text="A student's copy of the examination schedule.",
    )
    seeded_submission = Notice(
        kind="submission",
        institution_id=institution.id,
        submitted_by=student.id,
        source_url="seed://submission/demo",
        redacted_text="A generated seed submission.",
    )
    fixture_official = Notice(
        kind="official",
        institution_id=fixture_institution.id,
        is_current=True,
        title="Fixture official",
        redacted_text="Synthetic fixture body.",
    )
    fixture_submission = Notice(
        kind="submission",
        institution_id=fixture_institution.id,
        submitted_by=student.id,
        redacted_text="Synthetic fixture student copy.",
    )
    db_session.add_all(
        [official, submission, seeded_submission, fixture_official, fixture_submission]
    )
    db_session.flush()
    db_session.add_all(
        [
            RelationEdge(
                src_notice_id=submission.id,
                dst_notice_id=official.id,
                label="superseded",
                confidence=0.95,
                rationale="model label must stay hidden",
                model="test-model",
                status="auto",
            ),
            RelationEdge(
                src_notice_id=seeded_submission.id,
                dst_notice_id=official.id,
                label="consistent",
                confidence=0.9,
                model="test-model",
                status="auto",
            ),
            RelationEdge(
                src_notice_id=fixture_submission.id,
                dst_notice_id=fixture_official.id,
                label="consistent",
                confidence=0.9,
                model="test-model",
                status="auto",
            ),
        ]
    )
    db_session.commit()
    admin = _token(client, make_user, "candidate-list-admin@example.com", "s3cret1", "admin")
    reviewer = _token(
        client, make_user, "candidate-list-reviewer@example.com", "s3cret1", "reviewer"
    )

    forbidden = client.get("/api/admin/benchmark/candidates", headers=_auth(reviewer))
    assert forbidden.status_code == 403

    response = client.get("/api/admin/benchmark/candidates", headers=_auth(admin))
    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "submission_id": submission.id,
            "official_id": official.id,
            "institution_name": institution.name,
            "submission_title": submission.title,
            "official_title": official.title,
            "submission_created_at": submission.created_at.isoformat(),
            "official_published_date": official.published_date,
        }
    ]
    assert "label" not in response.text
    assert "confidence" not in response.text

    created = client.post(
        "/api/admin/benchmark/pairs",
        json={"submission_id": submission.id, "official_id": official.id},
        headers=_auth(admin),
    )
    assert created.status_code == 201, created.text
    assert client.get(
        "/api/admin/benchmark/candidates", headers=_auth(admin)
    ).json() == []
