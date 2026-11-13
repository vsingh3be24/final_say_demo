"""Securely bootstrap the first administrator for an empty FinalSay database.

Run from backend/ after the application has initialized its schema:
    python -m finalsay.services.provision_admin admin@example.edu

The password is entered interactively, never passed on the command line.
This tool refuses to change existing accounts or add another administrator.
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finalsay.auth import hash_password, normalize_email_address
from finalsay.db import Base, SessionLocal, engine
from finalsay.migrations import run_migrations
from finalsay.models import User


def create_first_admin(
    db: Session, email: str, password: str, display_name: str | None = None
) -> User:
    normalized_email = normalize_email_address(email)
    if len(password) < 16:
        raise ValueError("administrator passwords must contain at least 16 characters")
    if db.scalar(select(User).where(User.email == normalized_email)) is not None:
        raise ValueError("an account with this email already exists; no role was changed")
    admins = db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0
    if admins:
        raise ValueError("an administrator already exists; bootstrap only works on an empty admin role")
    admin = User(
        email=normalized_email,
        hashed_password=hash_password(password),
        role="admin",
        display_name=display_name.strip() if display_name and display_name.strip() else None,
    )
    db.add(admin)
    db.flush()
    return admin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="first administrator's login email")
    parser.add_argument("--display-name", help="name shown in the application")
    args = parser.parse_args()

    password = getpass.getpass("New administrator password (16+ characters): ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        parser.error("passwords did not match")

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    db = SessionLocal()
    try:
        admin = create_first_admin(db, args.email, password, args.display_name)
        db.commit()
        print(f"Created the first administrator account {admin.email}.")
        return 0
    except ValueError as exc:
        db.rollback()
        parser.error(str(exc))
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
