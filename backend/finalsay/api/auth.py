"""Auth API: register, login (returns JWT), and me."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from finalsay.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
    normalize_email_address,
)
from finalsay.db import get_db
from finalsay.models import Institution, User
from finalsay.schemas import StudentInstitutionUpdate, Token, UserOut, UserRegister

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# Public self-registration always yields a student account. Privileged roles
# are provisioned by trusted operator tooling so anonymous callers cannot
# self-assign privilege and reach role-protected routes.
SELF_REGISTER_ROLE = "student"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> UserOut:
    email = normalize_email_address(str(payload.email))
    institution = None
    if payload.institution_id is not None:
        institution = db.get(Institution, payload.institution_id)
        if (
            institution is None
            or not institution.active
            or institution.scrape_type == "fixture"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Select an active supported college.",
            )
    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        role=SELF_REGISTER_ROLE,
        display_name=(payload.display_name or "").strip() or None,
        institution_id=institution.id if institution else None,
    )
    try:
        existing = db.scalar(select(User).where(func.lower(User.email) == email))
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        db.add(user)
        db.flush()
        response = UserOut.model_validate(user)
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        # The pre-check gives a friendly response in the common case; the
        # unique constraint remains authoritative when requests race.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        # Keep DB/driver details (which may contain query parameters) out of
        # both the response and logs.
        logger.error("Registration could not persist a user (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration is temporarily unavailable. Please try again.",
        ) from exc


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 password-flow login. ``username`` is the email address."""
    try:
        email = normalize_email_address(form_data.username)
    except ValueError:
        email = form_data.username.strip().lower()
    user = authenticate_user(db, email, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id, role=user.role)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me/institution", response_model=UserOut)
def update_student_institution(
    payload: StudentInstitutionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Set or change the signed-in student's default college."""
    if current_user.role != SELF_REGISTER_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only student accounts have a personal college preference.",
        )
    institution = db.get(Institution, payload.institution_id)
    if (
        institution is None
        or not institution.active
        or institution.scrape_type == "fixture"
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select an active supported college.",
        )
    current_user.institution_id = institution.id
    db.commit()
    db.refresh(current_user)
    return current_user
