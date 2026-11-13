from __future__ import annotations

from types import SimpleNamespace

import pytest

from finalsay.models import AnchorBlock
from finalsay.models_iface import anchor as anchor_module
from finalsay.models_iface.anchor import PolygonAmoyAnchor, verify_polygon_root

ZERO32 = bytes(32)
_root = bytes.fromhex("11" * 32)
_batch = bytes.fromhex("22" * 32)
_publisher = "0x0000000000000000000000000000000000000001"


class _HexValue:
    def hex(self):
        return "0xabc123"


class TransactionNotFound(Exception):
    pass


class _Functions:
    records: dict[bytes, tuple[bytes, bytes, str, int]] = {}
    pending: tuple[bytes, bytes, bytes] | None = None

    def anchorRoot(self, root, batch_id, issuer_id):  # noqa: N802
        self.__class__.pending = (root, batch_id, issuer_id)
        return SimpleNamespace(build_transaction=lambda tx: tx)

    def getAnchor(self, root):  # noqa: N802
        return SimpleNamespace(
            call=lambda: self.__class__.records.get(
                root, (ZERO32, ZERO32, "0x0000000000000000000000000000000000000000", 0)
            )
        )

    def getRootForBatch(self, batch_id):  # noqa: N802
        return SimpleNamespace(
            call=lambda: next(
                (root for root, data in self.__class__.records.items() if data[0] == batch_id),
                ZERO32,
            )
        )


class _Account:
    address = _publisher

    def sign_transaction(self, tx):
        return SimpleNamespace(raw_transaction=b"signed", hash=_HexValue())


class _Eth:
    chain_id = 80002
    gas_price = 5
    receipt_status = 1
    wait_error: Exception | None = None
    in_pool = False
    sent_count = 0
    account = SimpleNamespace(from_key=lambda _key: _Account())

    def get_transaction_count(self, _address, _block="latest"):
        return 3

    def contract(self, **_kwargs):
        return SimpleNamespace(functions=_Functions())

    def send_raw_transaction(self, _raw):
        type(self).sent_count += 1
        return _HexValue()

    def wait_for_transaction_receipt(self, *_args, **_kwargs):
        if self.wait_error:
            raise self.wait_error
        if self.receipt_status == 1 and _Functions.pending:
            root, batch_id, issuer_id = _Functions.pending
            _Functions.records[root] = (batch_id, issuer_id, _publisher, 1_725_000_000)
        return SimpleNamespace(status=self.receipt_status, blockNumber=456)

    def get_transaction_receipt(self, _tx_hash):
        if self.receipt_status == 0:
            return SimpleNamespace(status=0, blockNumber=457)
        if not _Functions.records:
            raise TransactionNotFound()
        return SimpleNamespace(status=1, blockNumber=456)

    def get_transaction(self, _tx_hash):
        if self.in_pool:
            return SimpleNamespace(hash=_tx_hash)
        raise TransactionNotFound()

    def get_block(self, _number):
        return SimpleNamespace(timestamp=1_725_000_000)


class _Web3:
    eth = _Eth()

    def __init__(self, _provider):
        pass

    @staticmethod
    def HTTPProvider(_url, **_kwargs):
        return object()

    @staticmethod
    def to_checksum_address(address):
        return address

    @staticmethod
    def to_hex(value):
        return value.hex() if hasattr(value, "hex") else "0x" + bytes(value).hex()

    @staticmethod
    def keccak(value):
        import hashlib
        return hashlib.sha256(value).digest()

    def is_connected(self):
        return True


@pytest.fixture(autouse=True)
def reset_fake_chain():
    _Functions.records = {}
    _Functions.pending = None
    _Eth.receipt_status = 1
    _Eth.wait_error = None
    _Eth.in_pool = False
    _Eth.sent_count = 0


def _settings(**overrides):
    values = {
        "polygon_rpc_url": "https://rpc.invalid",
        "polygon_private_key": "test-key",
        "polygon_contract": "0x0000000000000000000000000000000000000002",
        "polygon_chain_id": 80002,
        "polygon_receipt_timeout": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _install_fake_web3(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "web3", SimpleNamespace(Web3=_Web3))


def test_polygon_anchor_waits_for_receipt_and_reads_contract(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)

    result = PolygonAmoyAnchor(None).anchor(_root.hex(), _batch.hex())
    assert result.kind == "polygon"
    assert result.ref == "0xabc123"
    assert result.chain_id == 80002
    assert result.block_number == 456
    assert result.status == "confirmed"
    assert result.network == "polygon-amoy"
    assert result.contract_address == _settings().polygon_contract
    assert result.issuer_address == _publisher
    assert result.batch_id == _batch.hex()
    assert result.anchored_at is not None


def test_missing_credentials_use_local_fallback(db_session, monkeypatch):
    monkeypatch.setattr(
        anchor_module,
        "get_settings",
        lambda: _settings(polygon_private_key=None),
    )

    result = PolygonAmoyAnchor(db_session).anchor(_root.hex(), _batch.hex())
    assert result.kind == "local"
    assert result.status == "local_fallback"
    assert db_session.query(AnchorBlock).count() == 1


def test_contract_mapping_read_verifies_root_batch_and_publisher(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)
    _issuer = bytes.fromhex(anchor_module.make_issuer_id([]))
    _Functions.records[_root] = (_batch, _issuer, _publisher, 1_725_000_000)

    assert verify_polygon_root(_root.hex()) == ("confirmed", None)
    result = anchor_module.read_polygon_anchor(
        _root.hex(), _batch.hex(), issuer_id=_issuer.hex()
    )
    assert result.status == "confirmed"
    assert result.publisher == _publisher
    assert result.issuer_id == _issuer.hex()

    mismatch = anchor_module.read_polygon_anchor(
        _root.hex(), _batch.hex(), issuer_id=anchor_module.make_issuer_id(["other issuer"])
    )
    assert mismatch.status == "mismatch"


def test_failed_transaction_receipt_cannot_verify_existing_mapping(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)
    _Eth.receipt_status = 0
    _issuer = bytes.fromhex(anchor_module.make_issuer_id([]))
    _Functions.records[_root] = (_batch, _issuer, _publisher, 1_725_000_000)

    result = anchor_module.read_polygon_anchor(
        _root.hex(), _batch.hex(), issuer_id=_issuer.hex(), transaction_hash="0xbadtx"
    )
    assert result.status == "failed"
    assert result.transaction_status == "failed"


def test_receipt_timeout_is_retained_as_pending(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _Eth.wait_error = TimeoutError("receipt not mined")
    _install_fake_web3(monkeypatch)

    result = PolygonAmoyAnchor(None).anchor(_root.hex(), _batch.hex())
    assert result.kind == "polygon"
    assert result.ref == "0xabc123"
    assert result.status == "pending"
    assert result.block_number is None


def test_rpc_outage_falls_back_locally_before_submission(db_session, monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())

    class OfflineWeb3(_Web3):
        def is_connected(self):
            return False

    monkeypatch.setitem(__import__("sys").modules, "web3", SimpleNamespace(Web3=OfflineWeb3))
    result = PolygonAmoyAnchor(db_session).anchor(_root.hex(), _batch.hex())
    assert result.kind == "local"
    assert result.status == "local_fallback"
    assert db_session.query(AnchorBlock).count() == 1


def test_reverted_receipt_is_failed_not_confirmed(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _Eth.receipt_status = 0
    _install_fake_web3(monkeypatch)

    result = PolygonAmoyAnchor(None).anchor(_root.hex(), _batch.hex())
    assert result.kind == "polygon"
    assert result.status == "failed"
    assert result.block_number == 456


def test_transaction_broadcast_timeout_is_pending_not_local_fallback(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)
    monkeypatch.setattr(
        _Eth,
        "send_raw_transaction",
        lambda *_args: (_ for _ in ()).throw(TimeoutError("ambiguous send timeout")),
    )

    result = PolygonAmoyAnchor(None).anchor(_root.hex(), _batch.hex())
    assert result.kind == "polygon"
    assert result.status == "pending"
    assert result.ref == "0xabc123"


def test_existing_contract_root_is_not_sent_twice(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)
    _issuer = bytes.fromhex(anchor_module.make_issuer_id([]))
    _Functions.records[_root] = (_batch, _issuer, _publisher, 1_725_000_000)

    result = PolygonAmoyAnchor(None).anchor(_root.hex(), _batch.hex())
    assert result.status == "confirmed"
    assert _Eth.sent_count == 0


def test_retry_keeps_live_pending_transaction_without_resubmitting(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)
    _Eth.in_pool = True

    result = PolygonAmoyAnchor(None).retry(_root.hex(), _batch.hex(), anchor_module.make_issuer_id([]), "0xabc123")
    assert result.status == "pending"
    assert result.ref == "0xabc123"
    assert _Eth.sent_count == 0


def test_retry_resubmits_a_transaction_missing_from_receipt_and_pool(monkeypatch):
    monkeypatch.setattr(anchor_module, "get_settings", lambda: _settings())
    _install_fake_web3(monkeypatch)

    result = PolygonAmoyAnchor(None).retry(_root.hex(), _batch.hex(), anchor_module.make_issuer_id([]), "0xoldtx")
    assert result.status == "confirmed"
    assert _Eth.sent_count == 1


def test_requested_environment_variable_names_are_supported(monkeypatch):
    from finalsay.config import Settings

    monkeypatch.setenv("POLYGON_AMOY_RPC_URL", "https://rpc-amoy.example")
    monkeypatch.setenv("POLYGON_AMOY_PRIVATE_KEY", "test-only-key")
    monkeypatch.setenv("POLYGON_AMOY_CHAIN_ID", "80002")
    monkeypatch.setenv(
        "FINALSAY_ANCHOR_CONTRACT_ADDRESS",
        "0x0000000000000000000000000000000000000003",
    )
    settings = Settings(_env_file=None)
    assert settings.polygon_rpc_url == "https://rpc-amoy.example"
    assert settings.polygon_private_key == "test-only-key"
    assert settings.polygon_chain_id == 80002
    assert settings.polygon_contract == "0x0000000000000000000000000000000000000003"
    assert "test-only-key" not in repr(settings)
