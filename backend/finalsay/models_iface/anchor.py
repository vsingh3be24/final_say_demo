"""Public and local Merkle-root anchors.

The public adapter stores only a root, opaque batch and issuer-set identifiers,
the publisher wallet address, and the block timestamp. Transaction hashes and
receipt metadata remain in the local database. It never treats a submitted
transaction as confirmed without a successful receipt and a matching contract
read.
"""

from __future__ import annotations

import hashlib
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.config import get_settings
from finalsay.models import AnchorBlock

AMOY_CHAIN_ID = 80002
AMOY_NETWORK = "polygon-amoy"
AMOY_EXPLORER = "https://amoy.polygonscan.com"

_SEND_LOCK = threading.Lock()

ANCHOR_ABI = [
    {
        "type": "function",
        "name": "anchorRoot",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "root", "type": "bytes32"},
            {"name": "batchId", "type": "bytes32"},
            {"name": "issuerId", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "getAnchor",
        "stateMutability": "view",
        "inputs": [{"name": "root", "type": "bytes32"}],
        "outputs": [
            {"name": "batchId", "type": "bytes32"},
            {"name": "issuerId", "type": "bytes32"},
            {"name": "publisher", "type": "address"},
            {"name": "anchoredAt", "type": "uint64"},
        ],
    },
    {
        "type": "function",
        "name": "getRootForBatch",
        "stateMutability": "view",
        "inputs": [{"name": "batchId", "type": "bytes32"}],
        "outputs": [{"name": "root", "type": "bytes32"}],
    },
]


@dataclass
class AnchorRef:
    """Where and how a Merkle root was anchored."""

    kind: str
    ref: str
    chain_id: int | None = None
    block_number: int | None = None
    status: str = "local"
    error: str | None = None
    network: str | None = None
    contract_address: str | None = None
    issuer_address: str | None = None
    issuer_id: str | None = None
    batch_id: str | None = None
    anchored_at: datetime | None = None
    submitted_at: datetime | None = None


@dataclass
class ChainAnchorRead:
    status: str
    error: str | None = None
    batch_id: str | None = None
    publisher: str | None = None
    issuer_id: str | None = None
    anchored_at: datetime | None = None
    block_number: int | None = None
    transaction_status: str | None = None


class Anchor(ABC):
    kind: str = "abstract"

    @abstractmethod
    def anchor(self, root_hash: str, batch_id: str | None = None, issuer_id: str | None = None) -> AnchorRef:
        raise NotImplementedError


class LocalHashChainAnchor(Anchor):
    """Append-only local hash chain, explicitly distinct from public anchoring."""

    kind = "local"

    def __init__(self, db: Session):
        self._db = db

    def anchor(self, root_hash: str, batch_id: str | None = None, issuer_id: str | None = None) -> AnchorRef:
        last = self._db.scalar(
            select(AnchorBlock).order_by(AnchorBlock.index.desc()).limit(1)
        )
        index = (last.index + 1) if last is not None else 0
        prev_hash = last.this_hash if last is not None else None
        this_hash = self._compute_hash(index, prev_hash, root_hash)
        self._db.add(
            AnchorBlock(
                index=index,
                prev_hash=prev_hash,
                data_hash=root_hash,
                this_hash=this_hash,
            )
        )
        self._db.flush()
        return AnchorRef(
            kind=self.kind,
            ref=this_hash,
            status="local",
            batch_id=batch_id,
            issuer_id=issuer_id,
        )

    @staticmethod
    def _compute_hash(index: int, prev_hash: str | None, data_hash: str) -> str:
        payload = f"{index}|{prev_hash or ''}|{data_hash}".encode()
        return hashlib.sha256(payload).hexdigest()


def _hex32(value: str) -> bytes:
    raw = bytes.fromhex(value.removeprefix("0x"))
    if len(raw) != 32:
        raise ValueError("expected a 32-byte value")
    return raw


def make_batch_id(day: str, root_hash: str) -> str:
    """Stable opaque id tying the on-chain root to its UTC-day batch."""
    digest = hashlib.sha256(
        f"finalsay:batch:v1:{day}:{root_hash.removeprefix('0x').lower()}".encode()
    ).hexdigest()
    return digest


def make_issuer_id(issuers: list[str | None]) -> str:
    """Hash the sorted public issuer names included in a daily root."""
    normalized = sorted(
        {issuer.strip().casefold() for issuer in issuers if isinstance(issuer, str) and issuer.strip()}
    )
    payload = "finalsay:issuer-set:v1:" + "|".join(normalized)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _configured_contract(w3, contract_address: str | None = None):
    settings = get_settings()
    address = contract_address or settings.polygon_contract
    if not address:
        raise RuntimeError("anchor contract address is not configured")
    checksum = w3.to_checksum_address(address)
    return w3.eth.contract(address=checksum, abi=ANCHOR_ABI), checksum


def _make_web3():
    settings = get_settings()
    if not settings.polygon_rpc_url:
        raise RuntimeError("Polygon Amoy RPC is not configured")
    from web3 import Web3

    w3 = Web3(
        Web3.HTTPProvider(
            settings.polygon_rpc_url,
            request_kwargs={"timeout": 15},
        )
    )
    if not w3.is_connected():
        raise RuntimeError("Polygon Amoy RPC is unavailable")
    expected_chain = int(settings.polygon_chain_id)
    actual_chain = int(w3.eth.chain_id)
    if actual_chain != expected_chain or actual_chain != AMOY_CHAIN_ID:
        raise RuntimeError(f"unexpected chain ID {actual_chain}")
    return w3


def _record_from_contract(contract, root_bytes: bytes) -> tuple[str, str, str, int]:
    batch_id, issuer_id, publisher, anchored_at = contract.functions.getAnchor(root_bytes).call()
    return (
        bytes(batch_id).hex(),
        bytes(issuer_id).hex(),
        str(publisher),
        int(anchored_at),
    )


class PolygonAmoyAnchor(Anchor):
    """Submit and confirm a root on Polygon Amoy, with honest local fallback."""

    kind = "polygon"

    def __init__(self, db: Session):
        self._db = db
        self._fallback = LocalHashChainAnchor(db)

    def _local_fallback(self, root_hash: str, batch_id: str | None, issuer_id: str | None, error: str) -> AnchorRef:
        local = self._fallback.anchor(root_hash, batch_id, issuer_id)
        return AnchorRef(
            kind="local",
            ref=local.ref,
            status="local_fallback",
            error=error,
            batch_id=batch_id,
            issuer_id=issuer_id,
        )

    def anchor(self, root_hash: str, batch_id: str | None = None, issuer_id: str | None = None) -> AnchorRef:
        settings = get_settings()
        batch_id = batch_id or make_batch_id("unknown", root_hash)
        issuer_id = issuer_id or make_issuer_id([])
        try:
            root_bytes = _hex32(root_hash)
            batch_bytes = _hex32(batch_id)
            issuer_bytes = _hex32(issuer_id)
            if not settings.polygon_private_key:
                raise RuntimeError("Polygon Amoy signing wallet is not configured")
            w3 = _make_web3()
            contract, contract_address = _configured_contract(w3)
            account = w3.eth.account.from_key(settings.polygon_private_key)
        except Exception as exc:  # no transaction has been broadcast yet
            return self._local_fallback(
                root_hash,
                batch_id,
                issuer_id,
                f"Public anchoring unavailable before submission ({type(exc).__name__})",
            )

        try:
            stored_batch, stored_issuer, stored_publisher, stored_timestamp = _record_from_contract(
                contract, root_bytes
            )
            if stored_timestamp:
                if stored_batch.lower() != batch_id.lower() or stored_issuer.lower() != issuer_id.lower():
                    return AnchorRef(
                        kind="polygon",
                        ref="",
                        chain_id=AMOY_CHAIN_ID,
                        status="failed",
                        error="The existing root is associated with a different batch identifier.",
                        network=AMOY_NETWORK,
                        contract_address=contract_address,
                        issuer_address=stored_publisher,
                        issuer_id=stored_issuer,
                        batch_id=stored_batch,
                        anchored_at=datetime.fromtimestamp(stored_timestamp, timezone.utc),
                    )
                return AnchorRef(
                    kind="polygon",
                    ref="",
                    chain_id=AMOY_CHAIN_ID,
                    status="confirmed",
                    network=AMOY_NETWORK,
                    contract_address=contract_address,
                    issuer_address=stored_publisher,
                    issuer_id=stored_issuer,
                    batch_id=stored_batch,
                    anchored_at=datetime.fromtimestamp(stored_timestamp, timezone.utc),
                )
        except Exception as exc:
            return self._local_fallback(
                root_hash,
                batch_id,
                issuer_id,
                f"Contract read failed before submission ({type(exc).__name__})",
            )

        # Serialize sends within this worker. The contract also rejects duplicate
        # roots/batches, which protects against concurrent app workers.
        with _SEND_LOCK:
            try:
                nonce = w3.eth.get_transaction_count(account.address, "pending")
                call = contract.functions.anchorRoot(root_bytes, batch_bytes, issuer_bytes)
                tx = call.build_transaction(
                    {
                        "from": account.address,
                        "nonce": nonce,
                        "chainId": AMOY_CHAIN_ID,
                        "gas": 160_000,
                        "gasPrice": int(w3.eth.gas_price),
                    }
                )
                signed = account.sign_transaction(tx)
                raw_tx = getattr(signed, "raw_transaction", None) or signed.rawTransaction
                signed_hash = getattr(signed, "hash", None)
                tx_hash = (
                    w3.to_hex(signed_hash)
                    if signed_hash
                    else w3.to_hex(w3.keccak(raw_tx))
                )
            except Exception as exc:
                return self._local_fallback(
                    root_hash,
                    batch_id,
                    issuer_id,
                    f"Transaction could not be prepared ({type(exc).__name__})",
                )

            submitted_at = datetime.now(timezone.utc)
            try:
                sent_hash = w3.eth.send_raw_transaction(raw_tx)
                tx_hash = w3.to_hex(sent_hash)
            except Exception as exc:
                # A timeout from send_raw_transaction is ambiguous: the node may
                # have accepted the signed transaction. Preserve its hash and
                # report pending; never send a local fallback for an uncertain
                # broadcast.
                return AnchorRef(
                    kind="polygon",
                    ref=tx_hash or "",
                    chain_id=AMOY_CHAIN_ID,
                    status="pending",
                    error=f"Broadcast result is not yet known ({type(exc).__name__})",
                    network=AMOY_NETWORK,
                    contract_address=contract_address,
                    issuer_address=account.address,
                    issuer_id=issuer_id,
                    batch_id=batch_id,
                    submitted_at=submitted_at,
                )

        try:
            receipt = w3.eth.wait_for_transaction_receipt(
                sent_hash, timeout=settings.polygon_receipt_timeout, poll_latency=2
            )
        except Exception as exc:
            return AnchorRef(
                kind="polygon",
                ref=tx_hash or "",
                chain_id=AMOY_CHAIN_ID,
                status="pending",
                error=f"Transaction receipt is not confirmed yet ({type(exc).__name__})",
                network=AMOY_NETWORK,
                contract_address=contract_address,
                issuer_address=account.address,
                issuer_id=issuer_id,
                batch_id=batch_id,
                submitted_at=submitted_at,
            )

        if int(receipt.status) != 1:
            # A duplicate transaction can revert after another worker mined the
            # same root. Accept it only if a fresh contract read proves the exact
            # requested root/batch is present.
            try:
                stored_batch, stored_issuer, publisher, timestamp = _record_from_contract(contract, root_bytes)
            except Exception:
                stored_batch, stored_issuer, publisher, timestamp = "", "", "", 0
            if timestamp and stored_batch.lower() == batch_id.lower() and stored_issuer.lower() == issuer_id.lower():
                return AnchorRef(
                    kind="polygon",
                    ref="",
                    chain_id=AMOY_CHAIN_ID,
                    status="confirmed",
                    network=AMOY_NETWORK,
                    contract_address=contract_address,
                    issuer_address=publisher,
                    issuer_id=stored_issuer,
                    batch_id=stored_batch,
                    anchored_at=datetime.fromtimestamp(timestamp, timezone.utc),
                    submitted_at=submitted_at,
                )
            return AnchorRef(
                kind="polygon",
                ref=tx_hash or "",
                chain_id=AMOY_CHAIN_ID,
                block_number=int(receipt.blockNumber),
                status="failed",
                error="Transaction receipt has status 0.",
                network=AMOY_NETWORK,
                contract_address=contract_address,
                issuer_address=account.address,
                issuer_id=issuer_id,
                batch_id=batch_id,
                submitted_at=submitted_at,
            )

        try:
            stored_batch, stored_issuer, publisher, timestamp = _record_from_contract(contract, root_bytes)
        except Exception as exc:
            return AnchorRef(
                kind="polygon",
                ref=tx_hash or "",
                chain_id=AMOY_CHAIN_ID,
                block_number=int(receipt.blockNumber),
                status="pending",
                error=f"Receipt succeeded; contract readback is pending ({type(exc).__name__})",
                network=AMOY_NETWORK,
                contract_address=contract_address,
                issuer_address=account.address,
                issuer_id=issuer_id,
                batch_id=batch_id,
                submitted_at=submitted_at,
            )
        if not timestamp or stored_batch.lower() != batch_id.lower() or stored_issuer.lower() != issuer_id.lower():
            return AnchorRef(
                kind="polygon",
                ref=tx_hash or "",
                chain_id=AMOY_CHAIN_ID,
                block_number=int(receipt.blockNumber),
                status="failed",
                error="Receipt succeeded but the contract record did not match.",
                network=AMOY_NETWORK,
                contract_address=contract_address,
                issuer_address=account.address,
                issuer_id=issuer_id,
                batch_id=batch_id,
                submitted_at=submitted_at,
            )
        return self._confirmed_ref(
            w3, receipt, tx_hash, contract_address, publisher,
            stored_batch, stored_issuer, submitted_at,
        )

    def retry(self, root_hash: str, batch_id: str, issuer_id: str, transaction_hash: str | None) -> AnchorRef:
        """Safely resume a pending transaction or retry a dropped/failed one."""
        if not transaction_hash:
            return self.anchor(root_hash, batch_id, issuer_id)
        try:
            w3 = _make_web3()
            contract, contract_address = _configured_contract(w3)
            try:
                receipt = w3.eth.get_transaction_receipt(transaction_hash)
            except Exception as exc:
                if type(exc).__name__ not in {"TransactionNotFound", "TransactionNotFoundError"}:
                    raise
                try:
                    w3.eth.get_transaction(transaction_hash)
                    return AnchorRef(
                        kind="polygon",
                        ref=transaction_hash,
                        chain_id=AMOY_CHAIN_ID,
                        status="pending",
                        error="The transaction is still present in the node transaction pool.",
                        network=AMOY_NETWORK,
                        contract_address=contract_address,
                        batch_id=batch_id,
                        issuer_id=issuer_id,
                    )
                except Exception as tx_exc:
                    if type(tx_exc).__name__ not in {"TransactionNotFound", "TransactionNotFoundError"}:
                        raise
                    return self.anchor(root_hash, batch_id, issuer_id)

            if int(receipt.status) == 0:
                # A failed receipt is definitive; anchor() checks the contract
                # first and sends a fresh transaction only if the record is absent.
                return self.anchor(root_hash, batch_id, issuer_id)

            record_batch, record_issuer, publisher, timestamp = _record_from_contract(
                contract, _hex32(root_hash)
            )
            if not timestamp or record_batch.lower() != batch_id.removeprefix("0x").lower() or record_issuer.lower() != issuer_id.removeprefix("0x").lower():
                return AnchorRef(
                    kind="polygon",
                    ref=transaction_hash,
                    chain_id=AMOY_CHAIN_ID,
                    block_number=int(receipt.blockNumber),
                    status="failed",
                    error="Successful receipt did not produce the expected contract record.",
                    network=AMOY_NETWORK,
                    contract_address=contract_address,
                    batch_id=record_batch,
                    issuer_id=record_issuer,
                )
            return self._confirmed_ref(
                w3,
                receipt,
                transaction_hash,
                contract_address,
                publisher,
                record_batch,
                record_issuer,
                None,
            )
        except Exception as exc:
            # A retry lookup outage must not create a second transaction.
            return AnchorRef(
                kind="polygon",
                ref=transaction_hash,
                chain_id=AMOY_CHAIN_ID,
                status="pending",
                error=f"Retry check is unavailable ({type(exc).__name__}).",
                network=AMOY_NETWORK,
                batch_id=batch_id,
                issuer_id=issuer_id,
            )

    @staticmethod
    def _confirmed_ref(w3, receipt, tx_hash, contract_address, publisher, batch_id, issuer_id, submitted_at):
        try:
            block = w3.eth.get_block(int(receipt.blockNumber))
            timestamp = datetime.fromtimestamp(int(block.timestamp), timezone.utc)
        except Exception:
            timestamp = None
        return AnchorRef(
            kind="polygon",
            ref=tx_hash or "",
            chain_id=AMOY_CHAIN_ID,
            block_number=int(receipt.blockNumber),
            status="confirmed",
            network=AMOY_NETWORK,
            contract_address=contract_address,
            issuer_address=publisher,
            issuer_id=issuer_id,
            batch_id=batch_id,
            anchored_at=timestamp,
            submitted_at=submitted_at,
        )


def read_polygon_anchor(
    root_hash: str,
    batch_id: str | None = None,
    issuer_id: str | None = None,
    contract_address: str | None = None,
    chain_id: int | None = None,
    transaction_hash: str | None = None,
) -> ChainAnchorRead:
    """Read the configured contract and compare its record to stored metadata."""
    try:
        w3 = _make_web3()
        settings = get_settings()
        expected_chain = int(chain_id or settings.polygon_chain_id)
        if expected_chain != AMOY_CHAIN_ID or int(w3.eth.chain_id) != expected_chain:
            return ChainAnchorRead("unavailable", "Configured chain does not match Polygon Amoy.")
        contract, _address = _configured_contract(w3, contract_address)
        receipt = None
        if transaction_hash:
            try:
                receipt = w3.eth.get_transaction_receipt(transaction_hash)
            except Exception as exc:
                # A missing receipt is a normal pending state; other transport
                # failures are reported as unavailable below.
                if type(exc).__name__ not in {"TransactionNotFound", "TransactionNotFoundError"}:
                    raise
        if receipt is not None and int(receipt.status) == 0:
            return ChainAnchorRead(
                "failed",
                "The submitted transaction reverted.",
                block_number=int(receipt.blockNumber),
                transaction_status="failed",
            )
        onchain_batch, onchain_issuer, publisher, timestamp = _record_from_contract(
            contract, _hex32(root_hash)
        )
        if timestamp and int(publisher, 16) != 0:
            if (
                (batch_id and onchain_batch.lower() != batch_id.removeprefix("0x").lower())
                or (issuer_id and onchain_issuer.lower() != issuer_id.removeprefix("0x").lower())
            ):
                return ChainAnchorRead(
                    "mismatch",
                    "The on-chain batch or issuer-set identifier differs from stored metadata.",
                    batch_id=onchain_batch,
                    publisher=publisher,
                    issuer_id=onchain_issuer,
                    anchored_at=datetime.fromtimestamp(timestamp, timezone.utc),
                    block_number=int(receipt.blockNumber) if receipt is not None else None,
                    transaction_status="confirmed" if receipt is not None and int(receipt.status) == 1 else None,
                )
            return ChainAnchorRead(
                "confirmed",
                batch_id=onchain_batch,
                publisher=publisher,
                issuer_id=onchain_issuer,
                anchored_at=datetime.fromtimestamp(timestamp, timezone.utc),
                block_number=int(receipt.blockNumber) if receipt is not None and int(receipt.status) == 1 else None,
                transaction_status="confirmed" if receipt is not None and int(receipt.status) == 1 else None,
            )
        if receipt is None and transaction_hash:
            return ChainAnchorRead(
                "pending",
                "The transaction has not produced a receipt yet.",
                transaction_status="pending",
            )
        if not timestamp or int(publisher, 16) == 0:
            return ChainAnchorRead("missing", "No on-chain record exists for this root.")
        if (
            (batch_id and onchain_batch.lower() != batch_id.removeprefix("0x").lower())
            or (issuer_id and onchain_issuer.lower() != issuer_id.removeprefix("0x").lower())
        ):
            return ChainAnchorRead(
                "mismatch",
                "The on-chain batch or issuer-set identifier differs from stored metadata.",
                batch_id=onchain_batch,
                publisher=publisher,
                issuer_id=onchain_issuer,
                anchored_at=datetime.fromtimestamp(timestamp, timezone.utc),
                block_number=int(receipt.blockNumber) if receipt is not None else None,
                transaction_status="confirmed" if receipt is not None else None,
            )
        return ChainAnchorRead(
            "confirmed",
            batch_id=onchain_batch,
            publisher=publisher,
            issuer_id=onchain_issuer,
            anchored_at=datetime.fromtimestamp(timestamp, timezone.utc),
            block_number=int(receipt.blockNumber) if receipt is not None else None,
            transaction_status="confirmed" if receipt is not None else None,
        )
    except Exception as exc:
        return ChainAnchorRead(
            "unavailable",
            f"Polygon verification is unavailable ({type(exc).__name__}).",
        )


def verify_polygon_root(root_hash: str) -> tuple[str, str | None]:
    """Compatibility wrapper used by older callers and tests."""
    result = read_polygon_anchor(root_hash)
    return result.status, result.error


def get_anchor(db: Session) -> Anchor:
    settings = get_settings()
    if settings.anchor == "polygon":
        return PolygonAmoyAnchor(db)
    return LocalHashChainAnchor(db)
