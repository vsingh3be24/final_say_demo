"""Provenance (module 3, design.md section 6).

- ``sha256_notice(redacted_text, issuer, notice_date, deadline, audience,
  action)``: canonical SHA-256 over the notice's redacted content and every
  stored, evidence-bearing field, so a targeted edit to any single column is
  tamper-detectable.
- ``build_daily_merkle(db, day)``: collect that day's notice hashes, build a
  binary Merkle tree (duplicate the last leaf on odd count), store a
  ``merkle_root`` and one ``merkle_proof`` per notice, and anchor the root via
  the configured Anchor interface.
- ``verify_notice(db, notice_id, tamper=False)``: recompute the notice hash,
  recompute the root from its stored proof, and compare against the stored root
  -> ``{ok, tamper, details}``. ``tamper=True`` simulates content tampering for
  the demo verification path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.models import MerkleProof, MerkleRoot, Notice
from finalsay.config import get_settings
from finalsay.models_iface.anchor import (
    AMOY_EXPLORER,
    PolygonAmoyAnchor,
    get_anchor,
    make_batch_id,
    make_issuer_id,
    read_polygon_anchor,
)


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def sha256_notice(
    redacted_text: str | None,
    issuer: str | None,
    notice_date: str | None,
    deadline: str | None = None,
    audience: str | None = None,
    action: str | None = None,
) -> str:
    """Return the canonical SHA-256 hash of a notice's redacted content.

    The canonical form now covers every stored, evidence-bearing field
    (issuer, date, deadline, audience, action, redacted text) so a targeted edit
    to any one column is tamper-detectable, not just edits that also change
    ``redacted_text``. Fields are labelled and newline-joined so a value moving
    between columns cannot collide with another field's value.
    """
    canonical = "\n".join(
        [
            f"issuer:{(issuer or '').strip()}",
            f"date:{(notice_date or '').strip()}",
            f"deadline:{(deadline or '').strip()}",
            f"audience:{(audience or '').strip()}",
            f"action:{(action or '').strip()}",
            f"text:{(redacted_text or '').strip()}",
        ]
    )
    return _sha256_hex(canonical)


def hash_pair(left: str, right: str) -> str:
    """Hash two child node hashes into their parent (order-preserving)."""
    return _sha256_hex(left + right)


@dataclass
class MerkleBuildResult:
    root_id: int
    root_hash: str
    anchor_kind: str
    anchor_ref: str | None
    anchor_chain_id: int | None
    anchor_block_number: int | None
    anchor_network: str | None
    anchor_contract_address: str | None
    anchor_issuer_address: str | None
    anchor_issuer_id: str | None
    anchor_batch_id: str | None
    anchor_timestamp: datetime | None
    anchor_submitted_at: datetime | None
    anchor_status: str
    anchor_error: str | None
    leaf_count: int


def _build_tree_with_proofs(
    leaves: list[str],
) -> tuple[str, list[list[dict]]]:
    """Build a binary Merkle tree from leaf hashes.

    Duplicates the last node on odd counts at every level. Returns the root
    hash and, per leaf index, the sibling proof path as a list of
    ``{"hash": ..., "position": "left"|"right"}`` dicts (bottom-up).
    """
    if not leaves:
        return _sha256_hex(""), []

    proofs: list[list[dict]] = [[] for _ in leaves]
    # index_map[i] = position of original leaf i within the current level.
    index_map = list(range(len(leaves)))
    level = list(leaves)

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last node on odd count
        next_level: list[str] = []
        for i in range(0, len(level), 2):
            left, right = level[i], level[i + 1]
            parent = hash_pair(left, right)
            next_level.append(parent)
            for leaf_idx, pos in enumerate(index_map):
                if pos == i:
                    proofs[leaf_idx].append({"hash": right, "position": "right"})
                elif pos == i + 1:
                    proofs[leaf_idx].append({"hash": left, "position": "left"})
        # remap each original leaf to its parent's index in the next level.
        index_map = [pos // 2 for pos in index_map]
        level = next_level

    return level[0], proofs


def recompute_root_from_proof(leaf_hash: str, proof: list[dict]) -> str:
    """Recompute the Merkle root from a leaf hash and its sibling proof path."""
    current = leaf_hash
    for step in proof:
        sibling = step["hash"]
        if step["position"] == "left":
            current = hash_pair(sibling, current)
        else:
            current = hash_pair(current, sibling)
    return current


def _notices_for_day(db: Session, day: str) -> list[Notice]:
    """Return public official notices created on ``day`` (UTC).

    Student submissions are excluded: their hashes should not be published to
    a public chain without a separate consent and privacy design.
    """
    notices = db.scalars(select(Notice).order_by(Notice.id)).all()
    return [
        n for n in notices
        if n.kind == "official" and n.created_at.strftime("%Y-%m-%d") == day
    ]


def build_daily_merkle(db: Session, day: str) -> MerkleBuildResult:
    """Build (or rebuild) the Merkle tree over ``day``'s notices and anchor it.

    Ensures every notice for the day has a stored SHA-256 and a Merkle proof.
    """
    notices = _notices_for_day(db, day)
    if not notices:
        raise ValueError(f"No notices found for day {day}")

    leaves: list[str] = []
    for notice in notices:
        digest = sha256_notice(
            notice.redacted_text,
            notice.issuer,
            notice.notice_date,
            notice.deadline,
            notice.audience,
            notice.action,
        )
        if notice.sha256 != digest:
            notice.sha256 = digest
        leaves.append(digest)

    root_hash, proofs = _build_tree_with_proofs(leaves)

    # Reuse an existing anchor for an identical tree. A public anchor is never
    # downgraded to local mode; local/fallback anchors are upgraded once Amoy
    # credentials become available.
    anchor = get_anchor(db)
    root = db.scalar(
        select(MerkleRoot)
        .where(MerkleRoot.day == day, MerkleRoot.root_hash == root_hash)
        .order_by(MerkleRoot.id.desc())
        .limit(1)
    )
    settings = get_settings()
    batch_id = make_batch_id(day, root_hash)
    issuer_id = make_issuer_id([notice.issuer for notice in notices])
    polygon_ready = bool(
        settings.polygon_rpc_url
        and settings.polygon_private_key
        and settings.polygon_contract
    )
    public_anchor_stable = bool(
        root is not None
        and root.anchor_kind == "polygon"
        and (
            root.anchor_status in {"confirmed", "pending"}
            or (root.anchor_status == "failed" and anchor.kind == "local")
        )
    )
    local_anchor_stable = bool(
        root is not None
        and root.anchor_kind == "local"
        and root.anchor_status in {"local", "local_fallback"}
        and (anchor.kind == "local" or not polygon_ready)
    )
    if not public_anchor_stable and not local_anchor_stable:
        anchor_ref = anchor.anchor(root_hash, batch_id, issuer_id)
        if root is None:
            root = MerkleRoot(day=day, root_hash=root_hash)
            db.add(root)
        root.anchor_kind = anchor_ref.kind
        root.anchor_ref = anchor_ref.ref or None
        root.anchor_chain_id = anchor_ref.chain_id
        root.anchor_network = anchor_ref.network
        root.anchor_contract_address = anchor_ref.contract_address
        root.anchor_issuer_address = anchor_ref.issuer_address
        root.anchor_issuer_id = anchor_ref.issuer_id
        root.anchor_batch_id = anchor_ref.batch_id or batch_id
        root.anchor_block_number = anchor_ref.block_number
        root.anchor_timestamp = (
            anchor_ref.anchored_at.astimezone(timezone.utc).replace(tzinfo=None)
            if anchor_ref.anchored_at
            else None
        )
        root.anchor_submitted_at = (
            anchor_ref.submitted_at.astimezone(timezone.utc).replace(tzinfo=None)
            if anchor_ref.submitted_at
            else None
        )
        root.anchor_status = anchor_ref.status
        root.anchor_error = anchor_ref.error
        db.flush()

    # Keep proofs for older roots so the audit trail remains append-only. Refresh
    # only this exact root's proof rows. Use the positional loop index rather
    # than ``leaves.index`` so duplicate notice hashes keep distinct positions.
    for leaf_index, (notice, proof) in enumerate(zip(notices, proofs)):
        proof_row = db.scalar(
            select(MerkleProof).where(
                MerkleProof.notice_id == notice.id,
                MerkleProof.root_id == root.id,
            )
        )
        if proof_row is None:
            proof_row = MerkleProof(notice_id=notice.id, root_id=root.id)
            db.add(proof_row)
        proof_row.proof_json = json.dumps(proof)
        proof_row.leaf_index = leaf_index
    db.flush()

    return MerkleBuildResult(
        root_id=root.id,
        root_hash=root.root_hash,
        anchor_kind=root.anchor_kind,
        anchor_ref=root.anchor_ref,
        anchor_chain_id=root.anchor_chain_id,
        anchor_block_number=root.anchor_block_number,
        anchor_network=root.anchor_network,
        anchor_contract_address=root.anchor_contract_address,
        anchor_issuer_address=root.anchor_issuer_address,
        anchor_issuer_id=root.anchor_issuer_id,
        anchor_batch_id=root.anchor_batch_id,
        anchor_timestamp=root.anchor_timestamp,
        anchor_submitted_at=root.anchor_submitted_at,
        anchor_status=root.anchor_status,
        anchor_error=root.anchor_error,
        leaf_count=len(notices),
    )


def build_all_missing_roots(db: Session) -> list[MerkleBuildResult]:
    """Build or refresh one current Merkle root for every notice day.

    Recomputes each day's current leaf set so notices added after an earlier
    root receive proofs too. Identical roots reuse their existing anchor, making
    repeated seeding idempotent. Only official notices are included in public
    commitments; student-submitted documents remain off-chain and unanchored.
    """
    notices = db.scalars(select(Notice).where(Notice.kind == "official")).all()
    days = sorted({n.created_at.strftime("%Y-%m-%d") for n in notices})

    results: list[MerkleBuildResult] = []
    for day in days:
        results.append(build_daily_merkle(db, day))
    return results


def retry_anchor(db: Session, root_id: int) -> MerkleBuildResult:
    """Resume a pending transaction or retry a definitively failed root."""
    root = db.get(MerkleRoot, root_id)
    if root is None:
        raise ValueError(f"Merkle root {root_id} not found")
    if root.anchor_kind != "polygon" or root.anchor_status not in {"pending", "failed"}:
        raise ValueError("Only pending or failed Polygon roots can be retried")
    anchor_ref = PolygonAmoyAnchor(db).retry(
        root.root_hash,
        root.anchor_batch_id or make_batch_id(root.day, root.root_hash),
        root.anchor_issuer_id or make_issuer_id([]),
        root.anchor_ref,
    )
    root.anchor_kind = anchor_ref.kind
    root.anchor_ref = anchor_ref.ref or root.anchor_ref
    root.anchor_chain_id = anchor_ref.chain_id or root.anchor_chain_id
    root.anchor_network = anchor_ref.network or root.anchor_network
    root.anchor_contract_address = anchor_ref.contract_address or root.anchor_contract_address
    root.anchor_issuer_address = anchor_ref.issuer_address or root.anchor_issuer_address
    root.anchor_issuer_id = anchor_ref.issuer_id or root.anchor_issuer_id
    root.anchor_batch_id = anchor_ref.batch_id or root.anchor_batch_id
    root.anchor_block_number = anchor_ref.block_number or root.anchor_block_number
    if anchor_ref.anchored_at:
        root.anchor_timestamp = anchor_ref.anchored_at.astimezone(timezone.utc).replace(tzinfo=None)
    if anchor_ref.submitted_at:
        root.anchor_submitted_at = anchor_ref.submitted_at.astimezone(timezone.utc).replace(tzinfo=None)
    root.anchor_status = anchor_ref.status
    root.anchor_error = anchor_ref.error
    db.flush()
    leaf_count = len(db.scalars(select(MerkleProof).where(MerkleProof.root_id == root.id)).all())
    return MerkleBuildResult(
        root_id=root.id,
        root_hash=root.root_hash,
        anchor_kind=root.anchor_kind or "polygon",
        anchor_ref=root.anchor_ref,
        anchor_chain_id=root.anchor_chain_id,
        anchor_block_number=root.anchor_block_number,
        anchor_network=root.anchor_network,
        anchor_contract_address=root.anchor_contract_address,
        anchor_issuer_address=root.anchor_issuer_address,
        anchor_issuer_id=root.anchor_issuer_id,
        anchor_batch_id=root.anchor_batch_id,
        anchor_timestamp=root.anchor_timestamp,
        anchor_submitted_at=root.anchor_submitted_at,
        anchor_status=root.anchor_status,
        anchor_error=root.anchor_error,
        leaf_count=leaf_count,
    )


@dataclass
class VerifyResult:
    ok: bool
    tamper: bool
    integrity_status: str
    details: dict

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tamper": self.tamper,
            "integrity_status": self.integrity_status,
            "details": self.details,
        }


def verify_notice(db: Session, notice_id: int, tamper: bool = False) -> VerifyResult:
    """Check a notice against retained Merkle proofs and public anchors.

    ``VERIFIED`` requires a live contract read matching a root that contains the
    recomputed notice hash. Local hash-chain checks are labeled separately.
    """
    notice = db.get(Notice, notice_id)
    if notice is None:
        return VerifyResult(
            ok=False,
            tamper=False,
            integrity_status="NOT_ANCHORED",
            details={"error": f"notice {notice_id} not found"},
        )
    if notice.kind != "official":
        return VerifyResult(
            ok=False,
            tamper=False,
            integrity_status="NOT_ANCHORED",
            details={
                "error": "Only official notices are included in public provenance batches.",
                "notice_kind": notice.kind,
                "anchor_status": "not_anchored",
                "integrity_ok": False,
                "on_chain_verified": False,
            },
        )

    proof_rows = db.scalars(
        select(MerkleProof)
        .where(MerkleProof.notice_id == notice_id)
        .order_by(MerkleProof.id.desc())
    ).all()
    if not proof_rows:
        return VerifyResult(
            ok=False,
            tamper=False,
            integrity_status="NOT_ANCHORED",
            details={"error": "no merkle proof stored; build the daily root first"},
        )

    recomputed_hash = sha256_notice(
        notice.redacted_text,
        notice.issuer,
        notice.notice_date,
        notice.deadline,
        notice.audience,
        notice.action,
    )
    if tamper:
        recomputed_hash = _sha256_hex(recomputed_hash + "::tampered")

    matched: list[tuple[MerkleProof, MerkleRoot]] = []
    newest_proof_root: str | None = None
    newest_recomputed_root: str | None = None
    for proof_row in proof_rows:
        root = db.get(MerkleRoot, proof_row.root_id)
        if root is None:
            continue
        proof = json.loads(proof_row.proof_json)
        recomputed_root = recompute_root_from_proof(recomputed_hash, proof)
        if newest_proof_root is None:
            newest_proof_root = root.root_hash
            newest_recomputed_root = recomputed_root
        if recomputed_root == root.root_hash and notice.sha256 == recomputed_hash:
            matched.append((proof_row, root))

    if not matched:
        newest = db.get(MerkleRoot, proof_rows[0].root_id)
        return VerifyResult(
            ok=False,
            tamper=True,
            integrity_status="TAMPERED",
            details={
                "stored_hash": notice.sha256,
                "recomputed_hash": recomputed_hash,
                "stored_root": newest.root_hash if newest else None,
                "recomputed_root": newest_recomputed_root,
                "anchor_kind": newest.anchor_kind if newest else None,
                "transaction_status": newest.anchor_status if newest else None,
                "integrity_ok": False,
                "on_chain_verified": False,
                "simulated_tamper": tamper,
                "integrity_status": "TAMPERED",
            },
        )

    chosen_proof, chosen_root = matched[0]
    integrity_status = "NOT_ANCHORED"
    on_chain_verified = False
    anchor_status = chosen_root.anchor_status
    anchor_error = chosen_root.anchor_error
    for proof_row, root in matched:
        if root.anchor_kind == "local":
            if integrity_status == "NOT_ANCHORED":
                chosen_proof, chosen_root = proof_row, root
                integrity_status = "LOCAL_VERIFIED"
                anchor_status = root.anchor_status
                anchor_error = root.anchor_error
            continue
        if root.anchor_kind != "polygon":
            continue
        chain = read_polygon_anchor(
            root.root_hash,
            batch_id=root.anchor_batch_id,
            issuer_id=root.anchor_issuer_id,
            contract_address=root.anchor_contract_address,
            chain_id=root.anchor_chain_id,
            transaction_hash=root.anchor_ref,
        )
        if chain.status == "confirmed":
            chosen_proof, chosen_root = proof_row, root
            integrity_status = "VERIFIED"
            anchor_status = "confirmed"
            anchor_error = None
            on_chain_verified = True
            root.anchor_status = "confirmed"
            if chain.anchored_at:
                root.anchor_timestamp = chain.anchored_at.astimezone(
                    timezone.utc
                ).replace(tzinfo=None)
            if chain.publisher:
                root.anchor_issuer_address = chain.publisher
            if chain.block_number is not None:
                root.anchor_block_number = chain.block_number
            if chain.transaction_status:
                root.anchor_status = chain.transaction_status
            break
        if chain.status == "mismatch":
            integrity_status = "TAMPERED"
            anchor_status = "mismatch"
            anchor_error = chain.error
        elif chain.status == "unavailable":
            if integrity_status not in {"VERIFIED", "TAMPERED"}:
                integrity_status = "VERIFICATION_UNAVAILABLE"
                anchor_status = "unavailable"
                anchor_error = chain.error or root.anchor_error
        elif chain.status == "pending" or root.anchor_status == "pending":
            if integrity_status not in {"VERIFIED", "TAMPERED", "VERIFICATION_UNAVAILABLE"}:
                integrity_status = "PENDING"
                anchor_status = "pending"
                anchor_error = chain.error or root.anchor_error
        elif chain.status == "failed":
            root.anchor_status = "failed"
            root.anchor_error = chain.error

    overall_ok = integrity_status in {"VERIFIED", "LOCAL_VERIFIED"}
    return VerifyResult(
        ok=overall_ok,
        tamper=integrity_status == "TAMPERED",
        integrity_status=integrity_status,
        details={
            "stored_hash": notice.sha256,
            "recomputed_hash": recomputed_hash,
            "stored_root": chosen_root.root_hash,
            "recomputed_root": recompute_root_from_proof(
                recomputed_hash, json.loads(chosen_proof.proof_json)
            ),
            "leaf_index": chosen_proof.leaf_index,
            "anchor_kind": chosen_root.anchor_kind,
            "anchor_ref": chosen_root.anchor_ref,
            "anchor_chain_id": chosen_root.anchor_chain_id,
            "anchor_network": chosen_root.anchor_network,
            "anchor_contract_address": chosen_root.anchor_contract_address,
            "anchor_issuer_address": chosen_root.anchor_issuer_address,
            "anchor_issuer_id": chosen_root.anchor_issuer_id,
            "anchor_batch_id": chosen_root.anchor_batch_id,
            "anchor_block_number": chosen_root.anchor_block_number,
            "anchor_timestamp": chosen_root.anchor_timestamp.isoformat() + "Z" if chosen_root.anchor_timestamp else None,
            "anchor_submitted_at": chosen_root.anchor_submitted_at.isoformat() + "Z" if chosen_root.anchor_submitted_at else None,
            "transaction_hash": chosen_root.anchor_ref if chosen_root.anchor_kind == "polygon" else None,
            "transaction_status": chosen_root.anchor_status,
            "explorer_transaction_url": (
                f"{AMOY_EXPLORER}/tx/{chosen_root.anchor_ref}"
                if chosen_root.anchor_kind == "polygon" and chosen_root.anchor_ref
                else None
            ),
            "explorer_contract_url": (
                f"{AMOY_EXPLORER}/address/{chosen_root.anchor_contract_address}"
                if chosen_root.anchor_kind == "polygon" and chosen_root.anchor_contract_address
                else None
            ),
            "anchor_status": anchor_status,
            "anchor_error": anchor_error,
            "integrity_ok": True,
            "on_chain_verified": on_chain_verified,
            "simulated_tamper": tamper,
            "integrity_status": integrity_status,
        },
    )
