"""Public institution choices for student registration and onboarding."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from finalsay.db import get_db
from finalsay.models import Institution, Notice
from finalsay.schemas import InstitutionChoiceOut

router = APIRouter(prefix="/api/institutions", tags=["institutions"])


@router.get("", response_model=list[InstitutionChoiceOut])
def institution_choices(db: Session = Depends(get_db)) -> list[InstitutionChoiceOut]:
    """Return only public picker fields for active, non-fixture institutions."""
    rows = db.execute(
        select(Institution.id, Institution.name, func.count(Notice.id))
        .outerjoin(
            Notice,
            and_(
                Notice.institution_id == Institution.id,
                Notice.kind == "official",
                Notice.is_current.is_(True),
            ),
        )
        .where(Institution.active.is_(True), Institution.scrape_type != "fixture")
        .group_by(Institution.id, Institution.name)
        .order_by(Institution.name)
    ).all()
    return [
        InstitutionChoiceOut(
            id=institution_id,
            name=name,
            current_notice_count=notice_count,
        )
        for institution_id, name, notice_count in rows
    ]
