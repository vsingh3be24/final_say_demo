"""Ingestion tests: source-key idempotency, student submit
returns a classified result, sources CRUD, and issuer publishing."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from finalsay.adapters.base import RawNotice
from finalsay.models import Institution, Notice, NoticeField, ScrapeProgress, ScrapeRun
from finalsay.services import comparison
from finalsay.services import ingestion


def _token(client, make_user, email, password, role):
    # Public register only creates students; provision privileged roles the way
    # the seed does (directly), then log in through the normal flow.
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


def test_fetch_all_is_idempotent_for_stable_source_keys(db_session):
    first = ingestion.fetch_all(
        db_session, include_live_sources=False, include_fixtures=True
    )
    db_session.commit()
    officials_1 = db_session.query(Notice).filter(Notice.kind == "official").count()

    second = ingestion.fetch_all(
        db_session, include_live_sources=False, include_fixtures=True
    )
    db_session.commit()
    officials_2 = db_session.query(Notice).filter(Notice.kind == "official").count()

    assert first["created"] > 0
    assert officials_1 == officials_2  # no duplicates on re-run
    assert second["created"] == 0
    assert second["skipped"] == officials_1


def test_distinct_official_source_keys_keep_identical_notice_text(db_session):
    institution = ingestion.get_or_create_institution(
        db_session, "duplicate-text-source", "Duplicate Text University",
        "https://example.edu/notices",
    )
    text = (
        "Issued by: Duplicate Text University\n"
        "Subject: Examination schedule\n"
        "The examination begins on 15 December 2026."
    )
    first = RawNotice(
        text=text,
        source_url="https://example.edu/notices/exam-a.pdf",
        institution_slug=institution.slug,
        external_id="exam-a",
        metadata={"title": "Examination schedule"},
    )
    second = RawNotice(
        text=text,
        source_url="https://example.edu/notices/exam-b.pdf",
        institution_slug=institution.slug,
        external_id="exam-b",
        metadata={"title": "Examination schedule"},
    )

    notice_a, outcome_a = ingestion.upsert_official(db_session, first, institution)
    notice_b, outcome_b = ingestion.upsert_official(db_session, second, institution)
    duplicate_b, duplicate_outcome = ingestion.upsert_official(
        db_session, second, institution
    )

    assert outcome_a == outcome_b == "created"
    assert notice_a.id != notice_b.id
    assert notice_a.sha256 == notice_b.sha256
    assert duplicate_b.id == notice_b.id
    assert duplicate_outcome == "unchanged"


def test_fetch_all_excludes_fictional_fixtures_by_default(db_session):
    summary = ingestion.fetch_all(db_session, include_live_sources=False)

    assert summary["created"] == 0
    assert summary["institutions"] == []
    assert db_session.query(Institution).count() == 0
    assert db_session.query(Notice).count() == 0


def test_fetch_all_can_target_one_configured_source(db_session, monkeypatch):
    import finalsay.adapters.live as live

    sources = [
        Institution(
            name=f"{slug} University", slug=slug,
            source_url=url, scrape_type=scraper,
            active=True, scrape_enabled=True,
        )
        for slug, url, scraper in (
            ("target-source", "https://vtu.ac.in/category/examination/", "vtu_examination"),
            ("untargeted-source", "https://exam.du.ac.in/exam/index.php/notifications", "du_examination"),
        )
    ]
    db_session.add_all(sources)
    db_session.flush()
    fetched = []

    class EmptyAdapter:
        errors = []
        supports_backfill = False

        def __init__(self, institution):
            self.slug = institution.slug
            self.name = institution.name
            self.base_url = institution.source_url

        def fetch(self):
            fetched.append(self.slug)
            return []

    monkeypatch.setattr(live, "create_live_adapter", EmptyAdapter)
    summary = ingestion.fetch_all(db_session, source_slugs={"target-source"})

    assert fetched == ["target-source"]
    assert [item["slug"] for item in summary["institutions"]] == ["target-source"]


def test_ingested_source_date_is_stored_separately_and_notice_is_candidate_retrievable(db_session):
    institution = ingestion.get_or_create_institution(
        db_session, "scraped-test", "Scraped Test University", "https://www.thapar.edu"
    )
    raw = RawNotice(
        text=(
            "Issued by: Scraped Test University\nSubject: End-semester examination timetable\n"
            "The odd-semester examinations will be held in December."
        ),
        source_url="https://www.thapar.edu/notices/exams.pdf",
        institution_slug="scraped-test",
        external_id="https://www.thapar.edu/notices/exams.pdf",
        metadata={"title": "End-semester examination timetable", "source_date": "12 October 2026"},
    )
    official, result = ingestion.upsert_official(db_session, raw, institution)
    assert result == "created"
    assert official.published_date == "12 October 2026"

    submission = ingestion.create_submission(
        db_session,
        text=(
            "Subject: End-semester examination timetable\n"
            "The odd-semester examinations timetable will be held in December."
        ),
        institution_id=institution.id,
    )
    assert submission.title == "End-semester examination timetable"

    class SemanticRanker:
        name = "semantic-test-ranker"

        def rank_candidates(self, _submission, officials):
            return [(notice, 0.92, 0.90) for notice in officials]

    candidates = comparison.retrieve_candidates(db_session, submission, model=SemanticRanker())
    assert candidates
    assert candidates[0].notice.id == official.id
    assert candidates[0].semantic_similarity == 0.90


def test_upsert_repairs_broken_unicode_in_real_source_text_and_title(db_session):
    institution = ingestion.get_or_create_institution(
        db_session, "unicode-test", "Unicode Test University", "https://mu.ac.in/circular.php"
    )
    raw = RawNotice(
        text="Official circular 🎓 with malformed extracted text \ud83c",
        source_url="https://mu.ac.in/admin/upload/circular/unicode-test.pdf",
        institution_slug="unicode-test",
        external_id="mumbai:unicode-test",
        metadata={"title": "Circular \ud83c", "source_date": "10 November 2026"},
    )

    notice, outcome = ingestion.upsert_official(db_session, raw, institution)
    db_session.commit()

    assert outcome == "created"
    assert notice.title == "Circular \ufffd"
    assert "🎓" in notice.redacted_text
    assert "\ufffd" in notice.redacted_text
    assert "\ud83c" not in notice.redacted_text


def test_live_source_backfill_cursor_persists_and_advances_after_success(db_session, monkeypatch):
    import finalsay.adapters.live as live

    institution = Institution(
        name="Cursor University",
        slug="cursor-university",
        source_url="https://www.thapar.edu/notices",
        scrape_type="thapar_html",
        scrape_enabled=True,
        active=True,
    )
    db_session.add(institution)
    db_session.flush()
    step = {"value": 0}

    class PagedAdapter:
        slug = "cursor-university"
        name = "Cursor University"
        base_url = "https://www.thapar.edu"
        errors = []
        supports_backfill = True
        backfill_complete = False
        backfill_next_cursor = None

        def __init__(self, next_cursor, complete):
            self.backfill_next_cursor = next_cursor
            self.complete_after_fetch = complete

        def fetch(self):
            self.backfill_complete = self.complete_after_fetch
            return [RawNotice(
                text="Issued by: Cursor University\nSubject: Official exam timetable\nExam timetable revised for winter.",
                source_url="https://www.thapar.edu/notices/exam.pdf",
                institution_slug="cursor-university",
                external_id="https://www.thapar.edu/notices/exam.pdf",
            )]

    def fake_create(_institution):
        step["value"] += 1
        if step["value"] == 1:
            return PagedAdapter("https://www.thapar.edu/notices/page/3", False)
        return PagedAdapter(None, True)

    monkeypatch.setattr(live, "create_live_adapter", fake_create)
    ingestion.fetch_all(db_session, include_fixtures=False)
    progress = db_session.get(ScrapeProgress, institution.id)
    assert progress.cursor == "https://www.thapar.edu/notices/page/3"
    assert progress.backfill_complete is False

    ingestion.fetch_all(db_session, include_fixtures=False)
    assert progress.cursor is None
    assert progress.backfill_complete is True


def test_scheduled_source_batches_commit_independently(db_session, monkeypatch):
    """A later source failure must not roll back an earlier source's work."""
    from sqlalchemy import select

    from finalsay.db import SessionLocal

    sources = [
        Institution(
            name="First University",
            slug="first-university",
            source_url="https://vtu.ac.in/category/examination/",
            scrape_type="vtu_examination",
            active=True,
            scrape_enabled=True,
        ),
        Institution(
            name="Second University",
            slug="second-university",
            source_url="https://exam.du.ac.in/exam/index.php/notifications",
            scrape_type="du_examination",
            active=True,
            scrape_enabled=True,
        ),
    ]
    db_session.add_all(sources)
    db_session.commit()

    class Adapter:
        errors = []
        supports_backfill = False

        def __init__(self, institution):
            self.slug = institution.slug
            self.name = institution.name
            self.base_url = institution.source_url
            self.fail = institution.slug == "second-university"

        def fetch(self):
            if self.fail:
                raise OSError("second source is unavailable")
            return [RawNotice(
                text=(
                    "Issued by: First University\nSubject: Exam timetable\n"
                    "The examination timetable is now available."
                ),
                source_url="https://vtu.ac.in/notices/current-timetable.pdf",
                institution_slug=self.slug,
                external_id="vtu:current-timetable",
                metadata={"extraction_quality": "extracted"},
            )]

    monkeypatch.setattr(
        "finalsay.adapters.live.create_live_adapter",
        lambda institution: Adapter(institution),
    )
    summary = ingestion.fetch_all(db_session, commit_each_source=True)

    assert summary["created"] == 1
    assert summary["errors"] == 1
    assert [row["status"] for row in summary["institutions"]] == ["ok", "error"]

    # Read through a separate session to prove the first transaction was
    # committed before the second source failed.
    verify = SessionLocal()
    try:
        first = verify.scalar(
            select(Notice).where(
                Notice.kind == "official",
                Notice.source_key == "vtu:current-timetable",
            )
        )
        runs = verify.scalars(select(ScrapeRun).order_by(ScrapeRun.id)).all()
        assert first is not None
        assert len(runs) == 2
        assert [run.status for run in runs] == ["ok", "error"]
        assert "second source is unavailable" in (runs[1].error or "")
    finally:
        verify.close()


def test_admin_fetch_endpoint_no_duplicates(client: TestClient, make_user, monkeypatch):
    token = _token(client, make_user, "admin1@example.com", "s3cret1", "admin")

    source = client.post(
        "/api/ingest/sources",
        json={
            "name": "Test Live University",
            "slug": "test-live-university",
            "source_url": "https://www.thapar.edu/students/pages/dean-academics-notice-board",
            "scrape_type": "thapar_html",
            "scrape_enabled": True,
        },
        headers=_auth(token),
    )
    assert source.status_code == 201, source.text

    class FakeLiveAdapter:
        slug = "test-live-university"
        name = "Test Live University"
        base_url = "https://www.thapar.edu"
        errors = []

        def fetch(self):
            return [RawNotice(
                text="Issued by: Test Live University\nSubject: Test notice\nA public test notice.",
                source_url="https://www.thapar.edu/test-notice.pdf",
                institution_slug=self.slug,
                external_id="https://www.thapar.edu/test-notice.pdf",
                metadata={"title": "Test notice"},
            )]

    monkeypatch.setattr(
        "finalsay.adapters.live.create_live_adapter", lambda _institution: FakeLiveAdapter()
    )
    r1 = client.post("/api/ingest/fetch", headers=_auth(token))
    assert r1.status_code == 200, r1.text
    created_1 = r1.json()["created"]
    assert created_1 > 0

    r2 = client.post("/api/ingest/fetch", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] == 0

    # Confirm the browse endpoint sees a stable count.
    listing = client.get("/api/notices", headers=_auth(token))
    assert listing.status_code == 200
    assert len(listing.json()) == created_1


def test_fetch_requires_admin(client: TestClient, make_user):
    student = _token(client, make_user, "stud2@example.com", "s3cret1", "student")
    resp = client.post("/api/ingest/fetch", headers=_auth(student))
    assert resp.status_code == 403


def test_submit_paste_returns_classified_result(client: TestClient, make_user):
    admin = _token(client, make_user, "admin2@example.com", "s3cret1", "admin")
    client.post("/api/ingest/fetch", headers=_auth(admin))

    student = _token(client, make_user, "stud3@example.com", "s3cret1", "student")
    resp = client.post(
        "/api/ingest/submit",
        data={
            "text": "The mid-term examination has been cancelled until further notice.",
        },
        headers=_auth(student),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_id"] > 0
    assert body["edge_id"] > 0
    assert body["label"] in (
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
    )
    assert "cancel" in body["rationale"].lower() or body["label"] == "unresolved"


def test_submit_without_input_is_422(client: TestClient, make_user):
    student = _token(client, make_user, "stud4@example.com", "s3cret1", "student")
    resp = client.post("/api/ingest/submit", data={}, headers=_auth(student))
    assert resp.status_code == 422


def test_submit_image_without_ocr_engine_is_422(client: TestClient, make_user, monkeypatch):
    """With no Tesseract engine, image upload degrades to 422 asking for text."""
    from finalsay.services import extraction

    monkeypatch.setattr(extraction, "_tesseract_available", lambda: None)
    student = _token(client, make_user, "stud5@example.com", "s3cret1", "student")
    # A tiny fake PNG payload; extraction should raise OcrUnavailable -> 422.
    files = {"file": ("scan.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}
    resp = client.post("/api/ingest/submit", files=files, headers=_auth(student))
    assert resp.status_code == 422, resp.text


def test_sources_crud(client: TestClient, make_user):
    admin = _token(client, make_user, "admin3@example.com", "s3cret1", "admin")

    created = client.post(
        "/api/ingest/sources",
        json={
            "name": "Test Uni",
            "slug": "test-uni",
            "source_url": "https://vtu.ac.in/category/examination/",
            "scrape_type": "vtu_examination",
        },
        headers=_auth(admin),
    )
    assert created.status_code == 201, created.text
    assert created.json()["slug"] == "test-uni"

    # Duplicate slug -> 409.
    dup = client.post(
        "/api/ingest/sources",
        json={
            "name": "Test Uni",
            "slug": "test-uni",
            "source_url": "https://vtu.ac.in/category/examination/",
            "scrape_type": "vtu_examination",
        },
        headers=_auth(admin),
    )
    assert dup.status_code == 409

    fixture = client.post(
        "/api/ingest/sources",
        json={
            "name": "Fictional Test Source",
            "slug": "fictional-test-source",
            "scrape_type": "fixture",
        },
        headers=_auth(admin),
    )
    assert fixture.status_code == 422

    listing = client.get("/api/ingest/sources", headers=_auth(admin))
    assert listing.status_code == 200
    assert any(i["slug"] == "test-uni" for i in listing.json())


def test_admin_can_onboard_selected_official_portals(client: TestClient, make_user):
    admin = _token(client, make_user, "official-portals-admin@example.com", "s3cret1", "admin")
    sources = [
        ("vtu", "vtu_examination", "https://vtu.ac.in/category/examination/"),
        ("university-of-delhi", "du_examination", "https://exam.du.ac.in/exam/index.php/notifications"),
        ("university-of-mumbai", "mumbai_circulars", "https://mu.ac.in/circular.php"),
    ]
    for slug, scrape_type, source_url in sources:
        response = client.post(
            "/api/ingest/sources",
            json={
                "name": slug,
                "slug": slug,
                "source_url": source_url,
                "scrape_type": scrape_type,
                "scrape_enabled": True,
            },
            headers=_auth(admin),
        )
        assert response.status_code == 201, response.text
        assert response.json()["scrape_enabled"] is True

    rejected = client.post(
        "/api/ingest/sources",
        json={
            "name": "Unapproved",
            "slug": "unapproved",
            "source_url": "https://example.com/notices",
            "scrape_type": "vtu_examination",
        },
        headers=_auth(admin),
    )
    assert rejected.status_code == 422


def test_source_listing_reports_latest_success_and_admin_can_disable_source(
    client: TestClient, make_user, db_session
):
    admin = _token(client, make_user, "source-status-admin@example.com", "s3cret1", "admin")
    institution = Institution(
        name="Status University", slug="status-university",
        source_url="https://vtu.ac.in/category/examination/",
        scrape_type="vtu_examination", active=True, scrape_enabled=True,
    )
    db_session.add(institution)
    db_session.flush()
    db_session.add_all([
        ScrapeRun(
            institution_id=institution.id, status="ok", found=7, created=2,
            modified=1, unchanged=4, completed_at=datetime(2026, 11, 1),
        ),
        ScrapeRun(
            institution_id=institution.id, status="error", found=0, created=0,
            modified=0, unchanged=0, error="site unavailable",
            completed_at=datetime(2026, 11, 2),
        ),
    ])
    db_session.add_all([
        Notice(
            institution_id=institution.id, kind="official", extraction_quality="extracted",
            is_current=True,
        ),
        Notice(
            institution_id=institution.id, kind="official", extraction_quality="listing_only",
            is_current=True,
        ),
        Notice(
            institution_id=institution.id, kind="official", extraction_quality="unknown",
            is_current=True,
        ),
        Notice(
            institution_id=institution.id, kind="official", extraction_quality="extracted",
            is_current=False,
        ),
    ])
    db_session.commit()

    legacy_fixture = Institution(
        name="Fictional Legacy Source", slug="fictional-legacy-source",
        scrape_type="fixture", active=True, scrape_enabled=True,
    )
    db_session.add(legacy_fixture)
    db_session.commit()

    listed = client.get("/api/ingest/sources", headers=_auth(admin))
    source = next(row for row in listed.json() if row["slug"] == "status-university")
    assert not any(row["slug"] == "fictional-legacy-source" for row in listed.json())
    assert source["last_successful_fetch"].startswith("2026-11-01")
    assert source["last_successful_created"] == 2
    assert source["last_successful_unchanged"] == 4
    assert source["current_notice_count"] == 3
    assert source["extracted_count"] == 1
    assert source["listing_only_count"] == 1
    assert source["unextractable_count"] == 0
    assert source["unknown_extraction_count"] == 1

    disabled = client.put(
        f"/api/ingest/sources/{institution.id}",
        json={"active": False, "scrape_enabled": False},
        headers=_auth(admin),
    )
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False
    assert disabled.json()["scrape_enabled"] is False


def test_manual_poll_returns_conflict_if_a_poll_is_already_running(client: TestClient, make_user):
    from finalsay.services.scrape_runtime import acquire_scrape_slot, release_scrape_slot

    token = _token(client, make_user, "busy-poll-admin@example.com", "s3cret1", "admin")
    assert acquire_scrape_slot()
    try:
        response = client.post("/api/ingest/fetch", headers=_auth(token))
    finally:
        release_scrape_slot()
    assert response.status_code == 409


def test_issuer_publish_creates_official(client: TestClient, make_user):
    admin = _token(client, make_user, "admin4@example.com", "s3cret1", "admin")
    source = client.post(
        "/api/ingest/sources",
        json={
            "name": "Issuer Uni",
            "slug": "issuer-uni",
            "source_url": "https://vtu.ac.in/category/examination/",
            "scrape_type": "vtu_examination",
        },
        headers=_auth(admin),
    )
    assert source.status_code == 201, source.text

    issuer = _token(client, make_user, "issuer1@example.com", "s3cret1", "issuer")
    grant = client.post(
        "/api/issuer-memberships",
        json={"issuer_email": "issuer1@example.com", "institution_id": source.json()["id"]},
        headers=_auth(admin),
    )
    assert grant.status_code == 201, grant.text
    resp = client.post(
        "/api/issuer/publish",
        json={
            "institution_slug": "issuer-uni",
            "text": "Issued by: Issuer Uni\nSubject: Holiday\nDate: 5 May\nCampus closed on 5 May.",
        },
        headers=_auth(issuer),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "official"
    assert body["title"] == "Holiday"
    assert body["redacted_text"]
    assert body["sha256"]
    assert body["source_url"] is None

    # A student cannot publish.
    student = _token(client, make_user, "stud6@example.com", "s3cret1", "student")
    forbidden = client.post(
        "/api/issuer/publish",
        json={"institution_slug": "issuer-uni", "text": "x"},
        headers=_auth(student),
    )
    assert forbidden.status_code == 403


def test_issuer_grant_scopes_publishing_and_admin_can_revoke(client: TestClient, make_user):
    admin = _token(client, make_user, "grant-admin@example.com", "s3cret1", "admin")
    source = client.post(
        "/api/ingest/sources",
        json={
            "name": "Scoped Uni",
            "slug": "scoped-uni",
            "source_url": "https://vtu.ac.in/category/examination/",
            "scrape_type": "vtu_examination",
        },
        headers=_auth(admin),
    )
    issuer = _token(client, make_user, "scoped-issuer@example.com", "s3cret1", "issuer")
    student = _token(client, make_user, "grant-student@example.com", "s3cret1", "student")
    institution_id = source.json()["id"]

    forbidden_grant = client.post(
        "/api/issuer-memberships",
        json={"issuer_email": "scoped-issuer@example.com", "institution_id": institution_id},
        headers=_auth(student),
    )
    assert forbidden_grant.status_code == 403

    denied = client.post(
        "/api/issuer/publish",
        json={"institution_id": institution_id, "text": "Subject: Restricted\nTest notice."},
        headers=_auth(issuer),
    )
    assert denied.status_code == 403

    grant = client.post(
        "/api/issuer-memberships",
        json={"issuer_email": "scoped-issuer@example.com", "institution_id": institution_id},
        headers=_auth(admin),
    )
    assert grant.status_code == 201
    assert client.get("/api/issuer/institutions", headers=_auth(issuer)).json()[0]["id"] == institution_id
    assert client.post(
        "/api/issuer/publish",
        json={"institution_id": institution_id, "text": "Subject: Allowed\nTest notice."},
        headers=_auth(issuer),
    ).status_code == 201

    revoked = client.delete(
        f"/api/issuer-memberships/{grant.json()['user_id']}/{institution_id}",
        headers=_auth(admin),
    )
    assert revoked.status_code == 204
    denied_again = client.post(
        "/api/issuer/publish",
        json={"institution_id": institution_id, "text": "Subject: Revoked\nTest notice."},
        headers=_auth(issuer),
    )
    assert denied_again.status_code == 403


# --- Retention / redaction-before-storage (scope note §1, §6; GC-5, R2.4-R2.8) ---

# Original PII strings that MUST never survive into persisted storage.
_PII_ORIGINALS = (
    "jane.smith@northgate.edu",  # email
    "555 2671",  # phone fragment
    "21CS0456",  # roll / registration number
    "Jane Smith",  # honorific name
    "Robert Brown",  # labelled name
)
_REDACTION_MASKS = (
    "[REDACTED_EMAIL]",
    "[REDACTED_PHONE]",
    "[REDACTED_ID]",
    "[REDACTED_NAME]",
)
_PII_TEXT = (
    "Office of the Registrar\n"
    "Attention: all first-year students\n"
    "The mid-term exam is postponed to 22 Sept 2024.\n"
    "Contact Dr. Jane Smith at jane.smith@northgate.edu or +1 415 555 2671.\n"
    "Roll number 21CS0456 must re-register.\n"
    "Name: Robert Brown\n"
)


def test_persisted_submission_holds_only_redacted_text_no_unredacted_original(db_session):
    """Behavioral proof of the retention policy: after actually persisting a notice
    ingested from PII-containing text and re-reading it from the DB, the stored
    redacted_text and every stored NoticeField value must contain the redaction
    masks and NOT the original PII, and no persisted attribute may hold the
    unredacted original. This test would FAIL if an unredacted original were ever
    stored.
    """
    created = ingestion.create_submission(db_session, text=_PII_TEXT)
    db_session.commit()
    notice_id = created.id

    # Expunge everything so the assertions run against a fresh DB read, not the
    # in-memory object we just built.
    db_session.expunge_all()

    notice = db_session.get(Notice, notice_id)
    assert notice is not None

    # redacted_text is the persisted text and carries masks, not the PII.
    assert notice.redacted_text
    for original in _PII_ORIGINALS:
        assert original not in notice.redacted_text
    assert any(mask in notice.redacted_text for mask in _REDACTION_MASKS)

    # No persisted column/attribute on the Notice holds the unredacted original.
    # (Structural guarantee: there is no unredacted-original column.) Scan every
    # persisted string attribute and the raw DB columns to be certain.
    persisted_strings = [
        value for value in vars(notice).values() if isinstance(value, str)
    ]
    for value in persisted_strings:
        for original in _PII_ORIGINALS:
            assert original not in value, (
                f"unredacted PII {original!r} leaked into a persisted Notice attribute"
            )
    column_names = {c.name for c in Notice.__table__.columns}
    assert not any(
        "unredact" in name or name in {"raw_text", "original_text", "original"}
        for name in column_names
    ), "Notice table must not have an unredacted-original column"

    # Every stored NoticeField value is redacted too (fields parsed from redacted
    # text), so no identifier leaks through the structured extraction.
    fields = db_session.query(NoticeField).filter(NoticeField.notice_id == notice_id).all()
    assert fields, "expected extracted fields to be persisted"
    for row in fields:
        if row.value:
            for original in _PII_ORIGINALS:
                assert original not in row.value, (
                    f"unredacted PII {original!r} leaked into stored field {row.field_name!r}"
                )


def test_persisted_official_holds_only_redacted_text(db_session):
    """Same retention guarantee via the official upsert path (upsert_official ->
    _apply_extraction / _store_fields), re-read from the DB."""
    institution = ingestion.get_or_create_institution(
        db_session, "northgate", "Northgate University", "https://northgate.edu"
    )
    from finalsay.adapters.base import RawNotice

    raw = RawNotice(
        text=_PII_TEXT,
        source_url="https://northgate.edu/notices/1",
        institution_slug="northgate",
    )
    notice, outcome = ingestion.upsert_official(db_session, raw, institution)
    db_session.commit()
    assert outcome == "created"
    notice_id = notice.id
    db_session.expunge_all()

    reread = db_session.get(Notice, notice_id)
    assert reread is not None and reread.redacted_text
    for original in _PII_ORIGINALS:
        assert original not in reread.redacted_text
        assert original not in (reread.action or "")
        assert original not in (reread.issuer or "")
    assert any(mask in reread.redacted_text for mask in _REDACTION_MASKS)


def test_modified_source_creates_immutable_current_version_chain(db_session):
    from finalsay.adapters.base import RawNotice

    institution = ingestion.get_or_create_institution(
        db_session, "versioned", "Versioned Institute", "https://www.thapar.edu"
    )
    first = RawNotice(
        text="Subject: Examination timetable\nDate: 01 November 2026\nThe exam starts on 15 December 2026.",
        source_url="https://www.thapar.edu/notices/exam.pdf",
        institution_slug="versioned",
        external_id="exam-schedule-1",
        metadata={"title": "Examination timetable"},
    )
    old, outcome = ingestion.upsert_official(db_session, first, institution)
    assert outcome == "created"
    db_session.flush()
    old_id = old.id

    changed = RawNotice(
        text="Subject: Examination timetable\nDate: 01 November 2026\nThe exam starts on 20 December 2026.",
        source_url=first.source_url,
        institution_slug="versioned",
        external_id=first.external_id,
        metadata=first.metadata,
    )
    current, outcome = ingestion.upsert_official(db_session, changed, institution)
    db_session.flush()

    assert outcome == "modified"
    assert current.id != old_id
    assert current.version_no == 2
    assert current.previous_version_id == old_id
    assert current.is_current is True
    assert db_session.get(Notice, old_id).is_current is False
    duplicate, duplicate_outcome = ingestion.upsert_official(db_session, changed, institution)
    assert duplicate.id == current.id
    assert duplicate_outcome == "unchanged"


def test_changed_source_file_hash_versions_even_if_extracted_text_is_identical(db_session):
    institution = ingestion.get_or_create_institution(
        db_session, "binary-version-source", "Binary Version University",
        "https://example.edu/notices",
    )
    raw = RawNotice(
        text="Subject: Examination schedule\nThe exam is on 30 November 2026.",
        source_url="https://example.edu/notices/exam.pdf",
        institution_slug=institution.slug,
        metadata={"title": "Examination schedule", "source_content_sha256": "a" * 64},
    )
    first, outcome = ingestion.upsert_official(db_session, raw, institution)
    assert outcome == "created"
    db_session.flush()

    revised_file = RawNotice(
        text=raw.text,
        source_url=raw.source_url,
        institution_slug=institution.slug,
        metadata={"title": raw.metadata["title"], "source_content_sha256": "b" * 64},
    )
    second, outcome = ingestion.upsert_official(db_session, revised_file, institution)
    assert outcome == "modified"
    assert second.id != first.id
    assert second.version_no == 2
    assert second.previous_version_id == first.id
    assert first.is_current is False
    assert second.is_current is True

    duplicate, outcome = ingestion.upsert_official(db_session, revised_file, institution)
    assert outcome == "unchanged"
    assert duplicate.id == second.id


def test_student_old_notice_finds_revised_notice_published_at_new_url(
    client: TestClient, make_user, db_session
):
    institution = Institution(
        name="Test University",
        slug="new-url-revision-test",
        source_url="https://example.edu/notices",
        scrape_type="vtu_examination",
        active=True,
        scrape_enabled=True,
    )
    db_session.add(institution)
    db_session.flush()

    original = RawNotice(
        text=(
            "Subject: End-Semester Examination Schedule\n"
            "The end-semester examination is scheduled on 30 November 2026."
        ),
        source_url="https://example.edu/notices/exam-schedule.pdf",
        institution_slug=institution.slug,
        external_id="exam-schedule-original",
        metadata={"title": "End-Semester Examination Schedule", "source_date": "01 November 2026"},
    )
    old_official, old_outcome = ingestion.upsert_official(db_session, original, institution)
    assert old_outcome == "created"

    revised = RawNotice(
        text=(
            "Subject: Revised End-Semester Examination Schedule\n"
            "The end-semester examination has been postponed and will now be held on "
            "5 December 2026."
        ),
        source_url="https://example.edu/notices/revised-exam-schedule.pdf",
        institution_slug=institution.slug,
        external_id="exam-schedule-revised",
        metadata={
            "title": "Revised End-Semester Examination Schedule",
            "source_date": "05 November 2026",
        },
    )
    revised_official, revised_outcome = ingestion.upsert_official(db_session, revised, institution)
    assert revised_outcome == "created"
    db_session.commit()

    student_token = _token(
        client, make_user, "revision-student@example.com", "s3cret1", "student"
    )
    submitted = client.post(
        "/api/ingest/submit",
        data={
            "text": (
                "Subject: End-Semester Examination Schedule\n"
                "The end-semester examination is scheduled on 30 November 2026."
            ),
        },
        headers=_auth(student_token),
    )

    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["candidate_id"] == revised_official.id
    assert result["candidate_source_url"] == revised.source_url
    assert result["label"] == "superseded"
    assert result["edge_id"] > 0
    assert "postpon" in result["rationale"].lower()
    db_session.expire_all()
    stored_submission = db_session.get(Notice, result["submission_id"])
    assert stored_submission is not None
    assert stored_submission.institution_id == institution.id


def test_listing_fallback_cannot_downgrade_extracted_current_notice(db_session):
    institution = ingestion.get_or_create_institution(
        db_session, "quality-source", "Quality Source University", "https://example.edu"
    )
    source_url = "https://example.edu/notices/exam.pdf"
    source_key = "exam-schedule-2026"
    rich = RawNotice(
        text=(
            "Issued by: Quality Source University\n"
            "Subject: Revised examination timetable\n"
            "The odd-semester examinations start on 15 December 2026."
        ),
        source_url=source_url,
        institution_slug="quality-source",
        external_id=source_key,
        metadata={"title": "Revised examination timetable", "extraction_quality": "extracted"},
    )
    original, outcome = ingestion.upsert_official(db_session, rich, institution)
    assert outcome == "created"
    assert original.extraction_quality == "extracted"
    db_session.flush()
    original_id = original.id
    original_text = original.redacted_text

    fallback = RawNotice(
        text=(
            "Issued by: Quality Source University\n"
            "Subject: Revised examination timetable\n"
            "Official listing: Revised examination timetable"
        ),
        source_url=source_url,
        institution_slug="quality-source",
        external_id=source_key,
        metadata={"title": "Revised examination timetable", "extraction_quality": "listing_only"},
    )
    retained, outcome = ingestion.upsert_official(db_session, fallback, institution)
    assert outcome == "unchanged"
    assert retained.id == original_id
    assert retained.redacted_text == original_text
    assert retained.extraction_quality == "extracted"
    assert db_session.query(Notice).filter(Notice.source_key == source_key).count() == 1

    revised = RawNotice(
        text=(
            "Issued by: Quality Source University\n"
            "Subject: Revised examination timetable\n"
            "The odd-semester examinations now start on 20 December 2026."
        ),
        source_url=source_url,
        institution_slug="quality-source",
        external_id=source_key,
        metadata={"title": "Revised examination timetable", "extraction_quality": "extracted"},
    )
    new_current, outcome = ingestion.upsert_official(db_session, revised, institution)
    assert outcome == "modified"
    assert new_current.version_no == 2
    assert new_current.previous_version_id == original_id
    assert new_current.extraction_quality == "extracted"
