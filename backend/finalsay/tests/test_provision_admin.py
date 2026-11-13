import pytest

from finalsay.models import User
from finalsay.services.provision_admin import create_first_admin
from finalsay.models import Institution, IssuerMembership
from finalsay.services.provision_issuer import create_issuer


def test_first_admin_bootstrap_uses_normal_password_hashing_and_requires_strong_password(db_session):
    admin = create_first_admin(
        db_session,
        "OWNER@EXAMPLE.EDU",
        "a-strong-local-admin-password",
        "Local Owner",
    )
    db_session.commit()
    assert admin.email == "owner@example.edu"
    assert admin.role == "admin"
    assert admin.hashed_password != "a-strong-local-admin-password"


def test_first_admin_bootstrap_refuses_role_escalation_or_second_admin(db_session):
    db_session.add(User(email="student@example.edu", hashed_password="hash", role="student"))
    db_session.commit()
    with pytest.raises(ValueError, match="at least 16"):
        create_first_admin(db_session, "owner@example.edu", "short")

    create_first_admin(db_session, "owner@example.edu", "a-strong-local-admin-password")
    db_session.commit()
    with pytest.raises(ValueError, match="already exists"):
        create_first_admin(db_session, "second@example.edu", "another-strong-admin-password")


def test_privileged_account_provisioning_uses_api_email_validation(db_session):
    with pytest.raises(ValueError, match="valid email address"):
        create_first_admin(
            db_session,
            "local-ui-check@example.invalid",
            "a-strong-local-admin-password",
        )
    assert db_session.query(User).count() == 0


def test_issuer_provisioning_grants_only_a_selected_active_source(db_session):
    institution = Institution(
        name="Visvesvaraya Technological University",
        slug="vtu",
        source_url="https://vtu.ac.in/category/examination/",
        scrape_type="vtu_examination",
        active=True,
        scrape_enabled=True,
    )
    db_session.add(institution)
    db_session.flush()

    issuer, membership = create_issuer(
        db_session,
        "official@example.edu",
        "a-strong-local-issuer-password",
        "vtu",
        "Official Publisher",
    )
    db_session.commit()
    assert issuer.role == "issuer"
    assert membership.institution_id == institution.id
    assert membership.active is True
    assert db_session.query(IssuerMembership).count() == 1

    with pytest.raises(ValueError, match="selected official sources"):
        create_issuer(
            db_session,
            "another@example.edu",
            "another-strong-issuer-password",
            "thapar-institute",
        )
