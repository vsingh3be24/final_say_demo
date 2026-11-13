"""Create an issuer account scoped to one selected active institution.

Run from backend/:
    python -m finalsay.services.provision_issuer issuer@example.edu vtu

The password is entered interactively. This operator-side tool does not expose
role assignment through public registration or weaken the API's issuer grant
checks.
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import hash_password, normalize_email_address
from finalsay.db import Base, SessionLocal, engine
from finalsay.migrations import run_migrations
from finalsay.models import Institution, IssuerMembership, User

ALLOWED_ISSUER_SLUGS = {"vtu", "university-of-delhi", "university-of-mumbai"}


def create_issuer(
    db: Session,
    email: str,
    password: str,
    institution_slug: str,
    display_name: str | None = None,
) -> tuple[User, IssuerMembership]:
    normalized_email = normalize_email_address(email)
    if len(password) < 16:
        raise ValueError("issuer passwords must contain at least 16 characters")
    if institution_slug not in ALLOWED_ISSUER_SLUGS:
        raise ValueError("issuer grants are restricted to the selected official sources")
    if db.scalar(select(User).where(User.email == normalized_email)) is not None:
        raise ValueError("an account with this email already exists; no role was changed")
    institution = db.scalar(
        select(Institution).where(
            Institution.slug == institution_slug,
            Institution.active.is_(True),
        )
    )
    if institution is None:
        raise ValueError("selected institution source is missing or inactive")
    user = User(
        email=normalized_email,
        hashed_password=hash_password(password),
        role="issuer",
        display_name=display_name.strip() if display_name and display_name.strip() else None,
    )
    db.add(user)
    db.flush()
    membership = IssuerMembership(
        user_id=user.id,
        institution_id=institution.id,
        active=True,
    )
    db.add(membership)
    db.flush()
    return user, membership


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="issuer login email")
    parser.add_argument("institution_slug", choices=sorted(ALLOWED_ISSUER_SLUGS))
    parser.add_argument("--display-name", help="name shown in the publisher")
    args = parser.parse_args()
    password = getpass.getpass("New issuer password (16+ characters): ")
    confirmation = getpass.getpass("Confirm issuer password: ")
    if password != confirmation:
        parser.error("passwords did not match")

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    db = SessionLocal()
    try:
        issuer, _membership = create_issuer(
            db, args.email, password, args.institution_slug, args.display_name
        )
        db.commit()
        print(f"Created issuer {issuer.email} with publishing access to {args.institution_slug}.")
        return 0
    except ValueError as exc:
        db.rollback()
        parser.error(str(exc))
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
