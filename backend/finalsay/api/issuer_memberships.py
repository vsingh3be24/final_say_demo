"""Admin-managed issuer grants, scoped to a single active institution."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import Institution, IssuerMembership, User
from finalsay.schemas import IssuerMembershipCreate, IssuerMembershipOut

router = APIRouter(prefix="/api/issuer-memberships", tags=["issuer memberships"])


def _out(grant: IssuerMembership) -> IssuerMembershipOut:
    return IssuerMembershipOut(
        user_id=grant.user_id,
        issuer_email=grant.user.email,
        display_name=grant.user.display_name,
        institution_id=grant.institution_id,
        institution_name=grant.institution.name,
        institution_slug=grant.institution.slug,
        active=grant.active,
    )


@router.get(
    "",
    response_model=list[IssuerMembershipOut],
    dependencies=[Depends(require_role("admin"))],
)
def list_memberships(db: Session = Depends(get_db)) -> list[IssuerMembershipOut]:
    grants = db.scalars(
        select(IssuerMembership)
        .options(joinedload(IssuerMembership.user), joinedload(IssuerMembership.institution))
        .order_by(IssuerMembership.id)
    ).all()
    return [_out(grant) for grant in grants]


@router.post(
    "",
    response_model=IssuerMembershipOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
)
def grant_membership(
    payload: IssuerMembershipCreate, db: Session = Depends(get_db)
) -> IssuerMembershipOut:
    user = db.scalar(select(User).where(User.email == str(payload.issuer_email)))
    if user is None:
        raise HTTPException(status_code=404, detail="issuer account not found")
    if user.role != "issuer":
        raise HTTPException(status_code=422, detail="account must have the issuer role")
    institution = db.get(Institution, payload.institution_id)
    if institution is None or not institution.active:
        raise HTTPException(status_code=404, detail="active institution not found")

    grant = db.scalar(
        select(IssuerMembership).where(
            IssuerMembership.user_id == user.id,
            IssuerMembership.institution_id == institution.id,
        )
    )
    if grant is None:
        grant = IssuerMembership(
            user_id=user.id, institution_id=institution.id, active=True
        )
        db.add(grant)
    elif grant.active:
        raise HTTPException(status_code=409, detail="issuer grant already exists")
    else:
        grant.active = True

    db.commit()
    db.refresh(grant)
    return _out(grant)


@router.delete(
    "/{user_id}/{institution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role("admin"))],
)
def revoke_membership(
    user_id: int, institution_id: int, db: Session = Depends(get_db)
) -> None:
    grant = db.scalar(
        select(IssuerMembership).where(
            IssuerMembership.user_id == user_id,
            IssuerMembership.institution_id == institution_id,
            IssuerMembership.active.is_(True),
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="active issuer grant not found")
    db.delete(grant)
    db.commit()
