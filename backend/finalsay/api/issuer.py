"""Issuer API for granted institution publishing and official-notice ingestion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import Institution, IssuerMembership, User
from finalsay.schemas import InstitutionOut, IssuerPublishRequest, NoticeDetail
from finalsay.services import ingestion
from finalsay.services import provenance

router = APIRouter(prefix="/api/issuer", tags=["issuer"])


@router.get("/institutions", response_model=list[InstitutionOut])
def issuer_institutions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("issuer")),
) -> list[Institution]:
    """Return only active institutions this issuer has been granted."""
    return list(
        db.scalars(
            select(Institution)
            .join(IssuerMembership, IssuerMembership.institution_id == Institution.id)
            .where(
                IssuerMembership.user_id == current_user.id,
                IssuerMembership.active.is_(True),
                Institution.active.is_(True),
            )
            .order_by(Institution.name)
        ).all()
    )


@router.post("/publish", response_model=NoticeDetail, status_code=status.HTTP_201_CREATED)
def publish(
    payload: IssuerPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("issuer")),
):
    institution: Institution | None = None
    if payload.institution_id is not None:
        institution = db.get(Institution, payload.institution_id)
    elif payload.institution_slug is not None:
        institution = db.scalar(
            select(Institution).where(Institution.slug == payload.institution_slug)
        )
    else:
        memberships = db.scalars(
            select(IssuerMembership)
            .options(joinedload(IssuerMembership.institution))
            .where(
                IssuerMembership.user_id == current_user.id,
                IssuerMembership.active.is_(True),
            )
        ).all()
        active_institutions = [
            grant.institution for grant in memberships if grant.institution.active
        ]
        if len(active_institutions) == 1:
            institution = active_institutions[0]
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="select an institution granted to this issuer",
            )

    if institution is None or not institution.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="active institution not found",
        )

    grant = db.scalar(
        select(IssuerMembership).where(
            IssuerMembership.user_id == current_user.id,
            IssuerMembership.institution_id == institution.id,
            IssuerMembership.active.is_(True),
        )
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="issuer is not authorized for this institution",
        )

    notice = ingestion.publish_official(
        db,
        text=payload.text,
        institution=institution,
        source_url=payload.source_url,
    )
    provenance.build_daily_merkle(db, notice.created_at.strftime("%Y-%m-%d"))
    db.commit()
    db.refresh(notice)
    return notice
