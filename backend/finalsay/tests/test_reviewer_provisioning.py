import pytest

from finalsay.auth import verify_password
from finalsay.models import User
from finalsay.seed.create_reviewer import provision_reviewer


def test_reviewer_provisioning_hashes_password_and_limits_role(db_session):
    reviewer = provision_reviewer(
        db_session,
        "  First.Reviewer@Example.edu ",
        "a-long-local-password",
        "First Reviewer",
    )

    assert reviewer.email == "first.reviewer@example.edu"
    assert reviewer.role == "reviewer"
    assert reviewer.display_name == "First Reviewer"
    assert reviewer.hashed_password != "a-long-local-password"
    assert verify_password("a-long-local-password", reviewer.hashed_password)


def test_reviewer_provisioning_refuses_duplicate_without_role_change(db_session):
    existing = User(
        email="admin@example.edu",
        hashed_password="already-hashed",
        role="admin",
    )
    db_session.add(existing)
    db_session.flush()

    with pytest.raises(ValueError, match="no role was changed"):
        provision_reviewer(db_session, existing.email, "a-long-local-password")

    assert existing.role == "admin"


def test_reviewer_provisioning_rejects_weak_password(db_session):
    with pytest.raises(ValueError, match="at least 16 characters"):
        provision_reviewer(db_session, "reviewer@example.edu", "short")
