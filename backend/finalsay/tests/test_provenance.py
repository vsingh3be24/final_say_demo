"""Provenance tests: Merkle proofs verify for all leaves, tamper detection,
and the local anchor hash chain links via prev_hash."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from finalsay.models import AnchorBlock, Notice
from finalsay.services import provenance


def _make_notice(db, idx: int) -> Notice:
    notice = Notice(
        kind="official",
        issuer=f"Office {idx}",
        notice_date=f"2024-09-{idx:02d}",
        redacted_text=f"Official notice number {idx} content.",
    )
    db.add(notice)
    db.flush()
    return notice


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_merkle_proof_verifies_for_all_leaves(db_session):
    # Use an odd count to exercise the duplicate-last-leaf path.
    notices = [_make_notice(db_session, i) for i in range(1, 6)]
    db_session.commit()

    result = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    assert result.leaf_count == 5

    for notice in notices:
        verify = provenance.verify_notice(db_session, notice.id)
        assert verify.ok is True, verify.details
        assert verify.tamper is False


def test_daily_root_refreshes_for_new_same_day_notices_and_is_idempotent(db_session):
    from finalsay.models import MerkleProof, MerkleRoot

    first = _make_notice(db_session, 1)
    db_session.commit()
    original = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    assert original.leaf_count == 1

    second = _make_notice(db_session, 2)
    db_session.commit()
    refreshed = provenance.build_all_missing_roots(db_session)
    db_session.commit()
    assert len(refreshed) == 1
    assert refreshed[0].leaf_count == 2
    assert refreshed[0].root_hash != original.root_hash
    assert provenance.verify_notice(db_session, first.id).ok is True
    assert provenance.verify_notice(db_session, second.id).ok is True

    root_count = db_session.query(MerkleRoot).count()
    anchor_count = db_session.query(AnchorBlock).count()
    repeated = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    assert repeated.root_id == refreshed[0].root_id
    assert repeated.leaf_count == 2
    assert db_session.query(MerkleRoot).count() == root_count
    assert db_session.query(AnchorBlock).count() == anchor_count
    assert db_session.query(MerkleProof).count() == 3
    assert db_session.query(MerkleProof).filter_by(root_id=refreshed[0].root_id).count() == 2


def test_tampered_content_flips_tamper_flag(db_session):
    notices = [_make_notice(db_session, i) for i in range(1, 4)]
    db_session.commit()
    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    target = notices[0]

    # Simulated tamper via the demo flag.
    simulated = provenance.verify_notice(db_session, target.id, tamper=True)
    assert simulated.ok is False
    assert simulated.tamper is True

    # Real tamper: mutate stored content after the root was built.
    target.redacted_text = "This content was altered after anchoring."
    db_session.flush()
    real = provenance.verify_notice(db_session, target.id)
    assert real.ok is False
    assert real.tamper is True


def test_local_anchor_chain_prev_hash_links(db_session):
    # Two successive daily tree versions -> two blocks chained by prev_hash.
    _make_notice(db_session, 1)
    db_session.commit()
    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    _make_notice(db_session, 2)
    db_session.commit()
    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    blocks = db_session.scalars(
        select(AnchorBlock).order_by(AnchorBlock.index)
    ).all()
    assert len(blocks) >= 2
    assert blocks[0].prev_hash is None
    # Each block's prev_hash equals the previous block's this_hash.
    for prev, curr in zip(blocks, blocks[1:]):
        assert curr.prev_hash == prev.this_hash


def test_identical_root_reuses_existing_polygon_anchor(monkeypatch, db_session):
    from types import SimpleNamespace

    from finalsay.models import MerkleRoot

    notice = _make_notice(db_session, 1)
    db_session.commit()
    first = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    root = db_session.get(MerkleRoot, first.root_id)
    root.anchor_kind = "polygon"
    root.anchor_status = "confirmed"
    root.anchor_ref = "0xconfirmed"
    root.anchor_chain_id = 80002
    root.anchor_block_number = 10
    db_session.commit()

    class _PolygonAnchor:
        kind = "polygon"

        def anchor(self, _root_hash, _batch_id=None):
            raise AssertionError("must not broadcast an already confirmed root")

    monkeypatch.setattr(provenance, "get_anchor", lambda _db: _PolygonAnchor())
    from finalsay.models_iface.anchor import ChainAnchorRead
    monkeypatch.setattr(
        provenance,
        "read_polygon_anchor",
        lambda _root, **_kwargs: ChainAnchorRead("confirmed", batch_id=root.anchor_batch_id),
    )
    monkeypatch.setattr(
        provenance,
        "get_settings",
        lambda: SimpleNamespace(
            polygon_rpc_url="https://rpc.example",
            polygon_private_key="test-key",
            polygon_contract="0x0000000000000000000000000000000000000001",
        ),
    )

    repeated = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    assert repeated.root_id == first.root_id
    assert repeated.anchor_ref == "0xconfirmed"
    assert repeated.anchor_status == "confirmed"
    assert provenance.verify_notice(db_session, notice.id).details["anchor_kind"] == "polygon"


def test_default_anchor_is_local(db_session):
    notice = _make_notice(db_session, 1)
    db_session.commit()
    result = provenance.build_daily_merkle(db_session, _today())
    assert result.anchor_kind == "local"
    verified = provenance.verify_notice(db_session, notice.id)
    assert verified.integrity_status == "LOCAL_VERIFIED"
    assert verified.details["on_chain_verified"] is False


def test_student_submissions_are_excluded_from_public_merkle_batches(db_session):
    official = _make_notice(db_session, 1)
    submission = Notice(
        kind="submission",
        redacted_text="Private student submission text.",
    )
    db_session.add(submission)
    db_session.flush()

    result = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    assert result.leaf_count == 1
    assert provenance.verify_notice(db_session, official.id).integrity_status == "LOCAL_VERIFIED"
    verify_submission = provenance.verify_notice(db_session, submission.id)
    assert verify_submission.integrity_status == "NOT_ANCHORED"
    assert verify_submission.details["notice_kind"] == "submission"


def test_chain_outage_never_becomes_verified(monkeypatch, db_session):
    from finalsay.models import MerkleRoot
    from finalsay.models_iface.anchor import ChainAnchorRead

    notice = _make_notice(db_session, 1)
    db_session.flush()
    built = provenance.build_daily_merkle(db_session, _today())
    root = db_session.get(MerkleRoot, built.root_id)
    root.anchor_kind = "polygon"
    root.anchor_status = "confirmed"
    root.anchor_chain_id = 80002
    root.anchor_network = "polygon-amoy"
    root.anchor_batch_id = built.anchor_batch_id
    root.anchor_contract_address = "0x0000000000000000000000000000000000000001"
    db_session.flush()
    monkeypatch.setattr(
        provenance,
        "read_polygon_anchor",
        lambda *_args, **_kwargs: ChainAnchorRead(
            "unavailable", "RPC temporarily unavailable"
        ),
    )

    result = provenance.verify_notice(db_session, notice.id)
    assert result.ok is False
    assert result.integrity_status == "VERIFICATION_UNAVAILABLE"
    assert result.details["integrity_ok"] is True
    assert result.details["on_chain_verified"] is False


def test_polygon_receipt_fields_persist_and_mapping_is_verified(monkeypatch, db_session):
    """Exercise the complete backend handoff with a mocked Amoy receipt.

    This validates DB persistence and contract-map verification without
    pretending that a real testnet transaction occurred.
    """
    from types import SimpleNamespace

    from finalsay.models import MerkleRoot
    from finalsay.models_iface.anchor import AnchorRef

    notice = _make_notice(db_session, 1)
    db_session.commit()

    class _MockPolygonAnchor:
        kind = "polygon"

        def anchor(self, _root_hash, batch_id=None, issuer_id=None):
            return AnchorRef(
                kind="polygon",
                ref="0xmock-receipt",
                chain_id=80002,
                block_number=456,
                status="confirmed",
                network="polygon-amoy",
                contract_address="0x0000000000000000000000000000000000000001",
                issuer_address="0x0000000000000000000000000000000000000002",
                issuer_id=issuer_id,
                batch_id=batch_id,
            )

    monkeypatch.setattr(provenance, "get_anchor", lambda _db: _MockPolygonAnchor())
    from finalsay.models_iface.anchor import ChainAnchorRead
    monkeypatch.setattr(
        provenance,
        "read_polygon_anchor",
        lambda _root, batch_id=None, **_kwargs: ChainAnchorRead(
            "confirmed", batch_id=batch_id,
            publisher="0x0000000000000000000000000000000000000002",
            block_number=456,
        ),
    )
    monkeypatch.setattr(
        provenance,
        "get_settings",
        lambda: SimpleNamespace(
            polygon_rpc_url="https://amoy-rpc.invalid",
            polygon_private_key="test-only",
            polygon_contract="0x0000000000000000000000000000000000000001",
        ),
    )

    result = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    root = db_session.get(MerkleRoot, result.root_id)
    assert root.anchor_kind == "polygon"
    assert root.anchor_ref == "0xmock-receipt"
    assert root.anchor_chain_id == 80002
    assert root.anchor_block_number == 456
    assert root.anchor_network == "polygon-amoy"
    assert root.anchor_contract_address == "0x0000000000000000000000000000000000000001"
    assert root.anchor_batch_id
    assert root.anchor_status == "confirmed"

    verified = provenance.verify_notice(db_session, notice.id)
    assert verified.ok is True
    assert verified.integrity_status == "VERIFIED"
    assert verified.details["integrity_ok"] is True
    assert verified.details["on_chain_verified"] is True
    assert verified.details["anchor_status"] == "confirmed"


def test_structured_field_edit_is_tamper_detectable(db_session):
    """A targeted edit to deadline/audience/action (without touching
    redacted_text) must fail verification: the canonical hash covers them."""
    notice = Notice(
        kind="official",
        issuer="Registrar",
        notice_date="15 Sep",
        deadline="20 Sep",
        audience="all students",
        action="Exam scheduled on 15 Sep.",
        redacted_text="Exam scheduled on 15 Sep for all students.",
    )
    db_session.add(notice)
    db_session.flush()
    db_session.commit()

    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    ok = provenance.verify_notice(db_session, notice.id)
    assert ok.ok is True, ok.details

    # Edit only the deadline column (redacted_text is unchanged).
    notice.deadline = "28 Sep"
    db_session.flush()
    tampered = provenance.verify_notice(db_session, notice.id)
    assert tampered.ok is False
    assert tampered.tamper is True


def test_leaf_index_is_positional_on_duplicate_hashes(db_session):
    """Two notices with identical content (identical hash) must get distinct,
    positional leaf indices, not the first-match index from list.index()."""
    for _ in range(3):
        dup = Notice(
            kind="official",
            issuer="",
            notice_date="",
            redacted_text="Identical ambiguous circular text.",
        )
        db_session.add(dup)
    db_session.flush()
    db_session.commit()

    from finalsay.models import MerkleProof

    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    proofs = db_session.scalars(select(MerkleProof).order_by(MerkleProof.id)).all()
    indices = sorted(p.leaf_index for p in proofs)
    assert indices == [0, 1, 2], indices


def test_polygon_receipt_pending_is_not_reported_as_tamper(db_session, monkeypatch):
    from finalsay.models import MerkleRoot

    notice = _make_notice(db_session, 1)
    db_session.commit()
    result = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    root = db_session.get(MerkleRoot, result.root_id)
    root.anchor_kind = "polygon"
    root.anchor_status = "pending"
    root.anchor_error = "receipt timeout"
    root.anchor_batch_id = result.anchor_batch_id
    root.anchor_contract_address = "0x0000000000000000000000000000000000000001"
    db_session.commit()
    from finalsay.models_iface.anchor import ChainAnchorRead
    monkeypatch.setattr(
        provenance,
        "read_polygon_anchor",
        lambda _root, **_kwargs: ChainAnchorRead("pending", "not mined yet"),
    )

    verified = provenance.verify_notice(db_session, notice.id)
    assert verified.ok is False
    assert verified.tamper is False
    assert verified.integrity_status == "PENDING"
    assert verified.details["integrity_ok"] is True
    assert verified.details["anchor_status"] == "pending"
    assert verified.details["on_chain_verified"] is False


def test_retry_anchor_persists_confirmed_receipt_metadata(monkeypatch, db_session):
    from finalsay.models import MerkleRoot
    from finalsay.models_iface.anchor import AnchorRef

    notice = _make_notice(db_session, 1)
    built = provenance.build_daily_merkle(db_session, _today())
    root = db_session.get(MerkleRoot, built.root_id)
    root.anchor_kind = "polygon"
    root.anchor_status = "pending"
    root.anchor_ref = "0xpending"
    root.anchor_chain_id = 80002
    root.anchor_batch_id = built.anchor_batch_id
    root.anchor_contract_address = "0x0000000000000000000000000000000000000001"
    db_session.flush()

    class _MockRetry:
        def __init__(self, _db):
            pass

        def retry(self, root_hash, batch_id, issuer_id, transaction_hash):
            assert root_hash == built.root_hash
            assert batch_id == built.anchor_batch_id
            assert issuer_id == built.anchor_issuer_id
            assert transaction_hash == "0xpending"
            from datetime import datetime, timezone
            return AnchorRef(
                kind="polygon",
                ref="0xconfirmed",
                chain_id=80002,
                block_number=77,
                status="confirmed",
                network="polygon-amoy",
                contract_address=root.anchor_contract_address,
                issuer_address="0x0000000000000000000000000000000000000002",
                issuer_id=issuer_id,
                batch_id=batch_id,
                anchored_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
            )

    monkeypatch.setattr(provenance, "PolygonAmoyAnchor", _MockRetry)
    result = provenance.retry_anchor(db_session, root.id)

    assert result.anchor_status == "confirmed"
    assert result.anchor_ref == "0xconfirmed"
    assert result.anchor_block_number == 77
    assert result.anchor_network == "polygon-amoy"
    assert root.anchor_issuer_address == "0x0000000000000000000000000000000000000002"
