"""Provision a local reviewer account without opening reviewer self-registration.

Run from ``backend`` as ``python -m finalsay.seed.create_reviewer EMAIL``.
Passwords are prompted twice and are never accepted as command-line arguments.
The command creates reviewers only; it cannot create admins or issuers.
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import hash_password, normalize_email_address
from finalsay.db import SessionLocal
from finalsay.models import User


def provision_reviewer(
    db: Session, email: str, password: str, display_name: str | None = None
) -> User:
    """Add a reviewer identity; refuse role changes and duplicate accounts."""
    normalized_email = normalize_email_address(email)
    if len(password) < 16:
        raise ValueError("reviewer passwords must contain at least 16 characters")
    if db.scalar(select(User).where(User.email == normalized_email)) is not None:
        raise ValueError("an account with this email already exists; no role was changed")

    user = User(
        email=normalized_email,
        hashed_password=hash_password(password),
        role="reviewer",
        display_name=display_name.strip() if display_name and display_name.strip() else None,
    )
    db.add(user)
    db.flush()
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local FinalSay reviewer account.")
    parser.add_argument("email", help="reviewer's login email")
    parser.add_argument("--display-name", help="name shown in the reviewer console")
    args = parser.parse_args()

    password = getpass.getpass("New reviewer password (16+ characters): ")
    confirmation = getpass.getpass("Confirm reviewer password: ")
    if password != confirmation:
        parser.error("passwords did not match")

    db = SessionLocal()
    try:
        user = provision_reviewer(db, args.email, password, args.display_name)
        db.commit()
        print(f"Created reviewer account {user.email} (id {user.id}).")
        return 0
    except ValueError as exc:
        db.rollback()
        parser.error(str(exc))
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
