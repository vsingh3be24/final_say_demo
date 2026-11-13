"""Submission ownership checks across notice, candidate, compare and integrity APIs."""

from fastapi.testclient import TestClient


def _token(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    login = client.post("/api/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200
    return login.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_student_cannot_read_or_recompare_another_students_submission(client: TestClient):
    alice = _token(client, "alice@example.com", "s3cret1")
    bob = _token(client, "bob@example.com", "s3cret1")
    alice_submit = client.post(
        "/api/ingest/submit",
        data={"text": "A notice about an upcoming examination."},
        headers=_auth(alice),
    )
    bob_submit = client.post(
        "/api/ingest/submit",
        data={"text": "A different notice about campus services."},
        headers=_auth(bob),
    )
    assert alice_submit.status_code == 200
    assert bob_submit.status_code == 200
    alice_id = alice_submit.json()["submission_id"]
    bob_id = bob_submit.json()["submission_id"]

    assert client.get(f"/api/notices/{alice_id}", headers=_auth(alice)).status_code == 200
    for path in (
        f"/api/notices/{alice_id}",
        f"/api/notices/{alice_id}/candidates",
        f"/api/notices/{alice_id}/versions",
        f"/api/provenance/verify/{alice_id}",
    ):
        assert client.get(path, headers=_auth(bob)).status_code == 404
    assert client.post(f"/api/compare/{alice_id}", headers=_auth(bob)).status_code == 404

    listed = client.get("/api/notices?kind=submission", headers=_auth(bob))
    assert listed.status_code == 200
    assert [notice["id"] for notice in listed.json()] == [bob_id]
    assert client.get(f"/api/provenance/verify/{alice_id}").status_code == 401


def test_notice_detail_returns_document_extractions_separately(client, db_session):
    from finalsay.models import Institution, Notice, NoticeDocumentExtraction

    token = _token(client, "reader@example.com", "s3cret1")
    institution = Institution(name="Example University", slug="example-university", active=True)
    db_session.add(institution)
    db_session.flush()
    notice = Notice(
        institution_id=institution.id,
        kind="official",
        title="Exam schedule",
        redacted_text="Short listing summary",
        source_url="https://example.edu/notices/exam",
    )
    db_session.add(notice)
    db_session.flush()
    db_session.add(
        NoticeDocumentExtraction(
            notice_id=notice.id,
            source_url="https://example.edu/notices/exam.pdf",
            extracted_text="Full exam schedule extracted from PDF.",
            extracted_text_sha256="a" * 64,
            extraction_quality="extracted",
            extraction_method="pdf_text",
        )
    )
    db_session.commit()

    response = client.get(f"/api/notices/{notice.id}", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["redacted_text"] == "Short listing summary"
    assert payload["supplemental_extractions"][0]["extracted_text"] == (
        "Full exam schedule extracted from PDF."
    )
