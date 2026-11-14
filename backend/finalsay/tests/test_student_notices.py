from __future__ import annotations

from datetime import date

from finalsay.models import Institution, Notice


def _register(client, email: str, institution_id: int | None = None) -> str:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "s3cret1",
            "institution_id": institution_id,
        },
    )
    assert response.status_code == 201, response.text
    login = client.post(
        "/api/auth/login",
        data={"username": email, "password": "s3cret1"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _institution(db_session, slug: str, name: str) -> Institution:
    institution = Institution(
        name=name,
        slug=slug,
        active=True,
        scrape_type="vtu_examination",
    )
    db_session.add(institution)
    db_session.flush()
    return institution


def _notice(db_session, institution: Institution, title: str, date_text: str | None, published_on):
    notice = Notice(
        institution_id=institution.id,
        kind="official",
        title=title,
        issuer="Examination Office",
        published_date=date_text,
        published_on=published_on,
        redacted_text=f"Official update: {title}",
    )
    db_session.add(notice)
    db_session.flush()
    return notice


def test_public_institution_picker_exposes_only_safe_active_choices(client, db_session):
    active = _institution(db_session, "active-school", "Active University")
    _notice(db_session, active, "December timetable", "01 Nov 2026", date(2026, 11, 1))
    disabled = Institution(
        name="Disabled University", slug="disabled-school", active=False,
        scrape_type="vtu_examination",
    )
    fixture = Institution(
        name="Fixture University", slug="fixture-school", active=True,
        scrape_type="fixture",
    )
    db_session.add_all([disabled, fixture])
    db_session.commit()

    response = client.get("/api/institutions")

    assert response.status_code == 200
    assert response.json() == [{
        "id": active.id,
        "name": "Active University",
        "current_notice_count": 1,
    }]


def test_registration_saves_selected_college_and_rejects_inactive_or_fixture(client, db_session):
    active = _institution(db_session, "active-college", "Active College")
    fixture = Institution(
        name="Fixture College", slug="fixture-college", active=True,
        scrape_type="fixture",
    )
    disabled = Institution(
        name="Disabled College", slug="disabled-college", active=False,
        scrape_type="vtu_examination",
    )
    db_session.add_all([fixture, disabled])
    db_session.commit()

    response = client.post(
        "/api/auth/register",
        json={
            "email": "campus-student@example.com",
            "password": "s3cret1",
            "institution_id": active.id,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["institution_id"] == active.id
    token = client.post(
        "/api/auth/login",
        data={"username": "campus-student@example.com", "password": "s3cret1"},
    ).json()["access_token"]
    me = client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["institution_id"] == active.id

    for email, institution_id in (
        ("fixture-student@example.com", fixture.id),
        ("disabled-student@example.com", disabled.id),
    ):
        rejected = client.post(
            "/api/auth/register",
            json={"email": email, "password": "s3cret1", "institution_id": institution_id},
        )
        assert rejected.status_code == 422


def test_student_feed_is_college_scoped_paginated_and_month_filterable(client, db_session):
    campus = _institution(db_session, "campus-one", "Campus One")
    other = _institution(db_session, "campus-two", "Campus Two")
    nov_a = _notice(db_session, campus, "November timetable", "05 Nov 2026", date(2026, 11, 5))
    _notice(db_session, campus, "Revised examination calendar", "01 Nov 2026", date(2026, 11, 1))
    _notice(db_session, campus, "October holiday notice", "16 Oct 2026", date(2026, 10, 16))
    _notice(db_session, campus, "Notice with no publication date", None, None)
    _notice(db_session, other, "Other campus notice", "08 Nov 2026", date(2026, 11, 8))
    db_session.commit()
    token = _register(client, "feed-student@example.com", campus.id)

    all_notices = client.get(
        "/api/notices/student/feed?page=1&page_size=2", headers=_auth(token)
    )
    assert all_notices.status_code == 200, all_notices.text
    body = all_notices.json()
    assert body["institution_id"] == campus.id
    assert body["institution_name"] == "Campus One"
    assert body["total"] == 4
    assert body["page_count"] == 2
    assert body["items"][0]["id"] == nov_a.id
    assert body["months"] == [
        {"month": "2026-11", "count": 2},
        {"month": "2026-10", "count": 1},
    ]
    assert body["undated_count"] == 1

    november = client.get(
        "/api/notices/student/feed?month=2026-11", headers=_auth(token)
    ).json()
    assert november["total"] == 2
    assert {item["title"] for item in november["items"]} == {
        "November timetable", "Revised examination calendar"
    }

    undated = client.get(
        "/api/notices/student/feed?month=undated", headers=_auth(token)
    ).json()
    assert undated["total"] == 1
    assert undated["items"][0]["published_on"] is None

    search = client.get(
        "/api/notices/student/feed?q=calendar", headers=_auth(token)
    ).json()
    assert search["total"] == 1
    assert search["items"][0]["title"] == "Revised examination calendar"

    cross_campus = client.get(
        f"/api/notices?institution_id={other.id}", headers=_auth(token)
    )
    assert cross_campus.status_code == 403
    default_list = client.get("/api/notices", headers=_auth(token))
    assert default_list.status_code == 200
    assert all(item["institution_id"] == campus.id for item in default_list.json())


def test_unselected_student_must_choose_college_and_privileged_user_cannot_change_preference(
    client, make_user, db_session
):
    campus = _institution(db_session, "available-campus", "Available Campus")
    _notice(db_session, campus, "A dated notice", "03 Nov 2026", date(2026, 11, 3))
    db_session.commit()
    student_token = _register(client, "unselected@example.com")
    assert client.get("/api/notices/student/feed", headers=_auth(student_token)).status_code == 409
    assert client.get("/api/notices", headers=_auth(student_token)).status_code == 409
    selected = client.patch(
        "/api/auth/me/institution",
        json={"institution_id": campus.id},
        headers=_auth(student_token),
    )
    assert selected.status_code == 200
    assert selected.json()["institution_id"] == campus.id
    assert client.get("/api/notices/student/feed", headers=_auth(student_token)).status_code == 200

    admin = make_user("admin-campus@example.com", "s3cret1", "admin")
    login = client.post(
        "/api/auth/login",
        data={"username": "admin-campus@example.com", "password": "s3cret1"},
    )
    assert login.status_code == 200
    rejected = client.patch(
        "/api/auth/me/institution",
        json={"institution_id": campus.id},
        headers=_auth(login.json()["access_token"]),
    )
    assert rejected.status_code == 403


def test_student_submission_cannot_select_a_different_college(client, db_session):
    own_campus = _institution(db_session, "student-campus", "Student Campus")
    other_campus = _institution(db_session, "other-student-campus", "Other Campus")
    _notice(db_session, own_campus, "Current official notice", "05 Nov 2026", date(2026, 11, 5))
    _notice(db_session, other_campus, "Other current notice", "06 Nov 2026", date(2026, 11, 6))
    db_session.commit()
    token = _register(client, "submit-campus@example.com", own_campus.id)

    mismatch = client.post(
        "/api/ingest/submit",
        data={
            "text": "The final examination schedule has been revised.",
            "institution_id": other_campus.id,
        },
        headers=_auth(token),
    )
    assert mismatch.status_code == 403

    accepted = client.post(
        "/api/ingest/submit",
        data={"text": "The final examination schedule has been revised."},
        headers=_auth(token),
    )
    assert accepted.status_code == 200, accepted.text
