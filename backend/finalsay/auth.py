"""Authentication: password hashing (bcrypt), JWT HS256 issue/verify, role deps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import EmailStr, TypeAdapter, ValidationError
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.config import get_settings
from finalsay.db import get_db
from finalsay.models import Notice, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_EMAIL_ADAPTER = TypeAdapter(EmailStr)

# tokenUrl points at the login endpoint so /docs "Authorize" works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def normalize_email_address(email: str) -> str:
    """Apply the same email validation used by API schemas to provisioners."""
    try:
        return str(_EMAIL_ADAPTER.validate_python(email.strip())).lower()
    except ValidationError as exc:
        raise ValueError("provide a valid email address") from exc


def create_access_token(subject: str, role: str) -> str:
    """Issue an HS256 JWT for the given user id (subject) and role."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current user from a bearer token or raise 401."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        subject = payload.get("sub")
        if subject is None:
            raise credentials_error
    except JWTError as exc:  # noqa: PERF203
        raise credentials_error from exc

    user = db.get(User, int(subject))
    if user is None:
        raise credentials_error
    return user


def require_role(*roles: str):
    """Return a dependency enforcing that the current user has one of ``roles``."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return current_user

    return dependency


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


def ensure_notice_access(notice: Notice, user: User) -> None:
    """Prevent students and issuers from reading another student's submission."""
    if notice.kind == "submission" and user.role not in {"admin", "reviewer"}:
        if notice.submitted_by != user.id:
            raise HTTPException(status_code=404, detail="notice not found")
    elif notice.kind not in {"official", "submission"} and user.role != "admin":
        raise HTTPException(status_code=404, detail="notice not found")
