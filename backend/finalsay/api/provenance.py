"""Admin root-build/retry and authenticated notice integrity verification."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from finalsay.auth import ensure_notice_access, get_current_user, require_role
from finalsay.db import get_db
from finalsay.models import MerkleRoot, Notice, User
from finalsay.schemas import MerkleBuildRequest, MerkleBuildResponse, VerifyResponse
from finalsay.services import provenance

router = APIRouter(prefix="/api/provenance", tags=["provenance"])


def _build_response(result, day: str) -> MerkleBuildResponse:
    return MerkleBuildResponse(
        root_id=result.root_id,
        day=day,
        root_hash=result.root_hash,
        anchor_kind=result.anchor_kind,
        anchor_ref=result.anchor_ref,
        anchor_chain_id=result.anchor_chain_id,
        anchor_block_number=result.anchor_block_number,
        anchor_network=result.anchor_network,
        anchor_contract_address=result.anchor_contract_address,
        anchor_issuer_address=result.anchor_issuer_address,
        anchor_issuer_id=result.anchor_issuer_id,
        anchor_batch_id=result.anchor_batch_id,
        anchor_timestamp=result.anchor_timestamp,
        anchor_submitted_at=result.anchor_submitted_at,
        anchor_status=result.anchor_status,
        anchor_error=result.anchor_error,
        leaf_count=result.leaf_count,
    )


@router.post(
    "/build",
    response_model=MerkleBuildResponse,
    dependencies=[Depends(require_role("admin"))],
)
def build_daily_root(
    payload: MerkleBuildRequest | None = None,
    db: Session = Depends(get_db),
) -> MerkleBuildResponse:
    day = (
        payload.day
        if payload and payload.day
        else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    try:
        result = provenance.build_daily_merkle(db, day)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    db.commit()
    return _build_response(result, day)


@router.post(
    "/retry/{root_id}",
    response_model=MerkleBuildResponse,
    dependencies=[Depends(require_role("admin"))],
)
def retry_root_anchor(
    root_id: int,
    db: Session = Depends(get_db),
) -> MerkleBuildResponse:
    """Resume a pending transaction or safely retry a failed public anchor."""
    try:
        result = provenance.retry_anchor(db, root_id)
    except ValueError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in str(exc)
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    root = db.get(MerkleRoot, root_id)
    db.commit()
    return _build_response(result, root.day)


@router.get("/verify/{notice_id}", response_model=VerifyResponse)
def verify(
    notice_id: int,
    tamper: bool = Query(False, description="Simulate tampered content (demo)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VerifyResponse:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail=f"notice {notice_id} not found")
    ensure_notice_access(notice, current_user)
    result = provenance.verify_notice(db, notice_id, tamper=tamper)
    if result.details.get("anchor_kind") == "polygon":
        db.commit()
    return VerifyResponse(**result.as_dict())
