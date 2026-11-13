from __future__ import annotations

import logging
import os
import subprocess
import sys
from threading import Event

from finalsay.models import Institution, ScrapeRun
from finalsay.services import scrape_runtime


class _FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_sqlite_scrape_slot_serializes_separate_processes():
    assert scrape_runtime.engine.dialect.name == "sqlite"
    assert scrape_runtime.acquire_scrape_slot() is True
    script = (
        "from finalsay.services.scrape_runtime import acquire_scrape_slot, release_scrape_slot; "
        "ok = acquire_scrape_slot(); print(ok); "
        "release_scrape_slot() if ok else None"
    )
    try:
        blocked = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        assert blocked.stdout.strip() == "False"
    finally:
        scrape_runtime.release_scrape_slot()

    released = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert released.stdout.strip() == "True"


def test_extraction_failure_is_persisted_on_latest_source_run(db_session):
    institution = Institution(
        name="Official Source University",
        slug="official-source-university",
        source_url="https://vtu.ac.in/",
        scrape_type="vtu_examination",
        scrape_enabled=True,
        active=True,
    )
    db_session.add(institution)
    db_session.flush()
    run = ScrapeRun(
        institution_id=institution.id,
        status="ok",
        found=1,
        created=1,
        modified=0,
        unchanged=0,
    )
    db_session.add(run)
    db_session.commit()

    scrape_runtime._persist_document_extraction_errors(
        db_session,
        {
            "institutions": [
                {
                    "institution_id": institution.id,
                    "slug": institution.slug,
                    "errors": ["notice 12: PdfStreamError: corrupt PDF"],
                }
            ]
        },
        logging.getLogger("test-scraper"),
    )
    db_session.commit()

    assert run.status == "partial"
    assert "document extraction errors: notice 12: PdfStreamError" in run.error


def test_scheduler_persists_a_cycle_and_releases_the_shared_slot(monkeypatch):
    stop = Event()
    session = _FakeSession()
    calls = []

    monkeypatch.setattr(scrape_runtime, "SessionLocal", lambda: session)

    def fake_fetch(db, **kwargs):
        calls.append(db)
        assert kwargs == {
            "include_fixtures": False,
            "commit_each_source": True,
        }
        stop.set()
        return {"created": 2, "modified": 1, "skipped": 4, "errors": 0}

    def fake_refresh(db, *, per_institution):
        assert per_institution == 2
        assert db is session
        return {"stored": 1, "errors": []}

    monkeypatch.setattr(scrape_runtime, "fetch_all", fake_fetch)
    monkeypatch.setattr(
        scrape_runtime, "refresh_unknown_document_extractions", fake_refresh
    )
    scrape_runtime.scheduled_scrape_loop(stop, 1, logging.getLogger("test-scraper"))

    assert calls == [session]
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True
    assert scrape_runtime.acquire_scrape_slot() is True
    scrape_runtime.release_scrape_slot()


def test_scheduler_retries_failed_source_cycle_before_normal_interval(monkeypatch):
    class StopAfterWait:
        def __init__(self):
            self.delays = []

        def is_set(self):
            return False

        def wait(self, timeout):
            self.delays.append(timeout)
            return True

    stop = StopAfterWait()
    session = _FakeSession()
    monkeypatch.setattr(scrape_runtime, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        scrape_runtime,
        "fetch_all",
        lambda _db, **_kwargs: {
            "created": 0,
            "modified": 0,
            "skipped": 0,
            "errors": 1,
            "institutions": [
                {"slug": "vtu", "error": "SourceFetchError: request failed: DNS temporarily unavailable"}
            ],
        },
    )
    monkeypatch.setattr(
        scrape_runtime,
        "refresh_unknown_document_extractions",
        lambda _db, *, per_institution: {"stored": 0, "errors": []},
    )

    scrape_runtime.scheduled_scrape_loop(
        stop, 7_200, logging.getLogger("test-scraper-retry")
    )

    assert stop.delays == [scrape_runtime._SOURCE_RETRY_BASE_SECONDS]
    assert session.committed is True
    assert session.closed is True


def test_scheduler_retries_soon_after_another_poller_releases_lock(monkeypatch):
    class StopAfterWait:
        def __init__(self):
            self.delays = []

        def is_set(self):
            return False

        def wait(self, timeout):
            self.delays.append(timeout)
            return True

    stop = StopAfterWait()
    monkeypatch.setattr(scrape_runtime, "acquire_scrape_slot", lambda: False)

    scrape_runtime.scheduled_scrape_loop(
        stop, 7_200, logging.getLogger("test-scraper-contention")
    )

    assert stop.delays == [60]


def test_scheduler_keeps_normal_interval_for_expected_partial_results(monkeypatch):
    class StopAfterWait:
        def __init__(self):
            self.delays = []

        def is_set(self):
            return False

        def wait(self, timeout):
            self.delays.append(timeout)
            return True

    stop = StopAfterWait()
    session = _FakeSession()
    monkeypatch.setattr(scrape_runtime, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        scrape_runtime,
        "fetch_all",
        lambda _db, **_kwargs: {
            "created": 0,
            "modified": 0,
            "skipped": 90,
            "errors": 2,
            "institutions": [
                {"slug": "delhi", "error": "attachment is hosted outside the institution allowlist"},
                {"slug": "mumbai", "error": "backfill continuing after circular code 123"},
            ],
        },
    )
    monkeypatch.setattr(
        scrape_runtime,
        "refresh_unknown_document_extractions",
        lambda _db, *, per_institution: {"stored": 0, "errors": []},
    )

    scrape_runtime.scheduled_scrape_loop(
        stop, 7_200, logging.getLogger("test-scraper-partial")
    )

    assert stop.delays == [7_200]
    assert session.committed is True
    assert session.closed is True


def test_source_retry_delay_exponentially_increases_and_caps():
    assert [
        scrape_runtime._source_retry_delay(7_200, streak)
        for streak in range(1, 7)
    ] == [300, 600, 1_200, 2_400, 3_600, 3_600]
    assert scrape_runtime._source_retry_delay(60, 1) == 60


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _FakePostgresConnection:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []
        self.committed = 0
        self.closed = False

    def execute(self, statement, _params=None):
        self.statements.append(str(statement))
        return _FakeResult(next(self.results))

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


class _FakePostgresEngine:
    class dialect:
        name = "postgresql"

    def __init__(self, connection=None, error=None):
        self.connection = connection
        self.error = error

    def connect(self):
        if self.error:
            raise self.error
        return self.connection


def test_postgres_scrape_slot_uses_and_releases_database_advisory_lock(monkeypatch):
    connection = _FakePostgresConnection([True, True])
    monkeypatch.setattr(
        scrape_runtime, "engine", _FakePostgresEngine(connection=connection)
    )

    assert scrape_runtime.acquire_scrape_slot() is True
    assert connection.statements[0].startswith("SELECT pg_try_advisory_lock")
    scrape_runtime.release_scrape_slot()

    assert connection.statements[1].startswith("SELECT pg_advisory_unlock")
    assert connection.committed == 2
    assert connection.closed is True


def test_postgres_advisory_lock_conflict_releases_local_mutex(monkeypatch):
    connection = _FakePostgresConnection([False])
    monkeypatch.setattr(
        scrape_runtime, "engine", _FakePostgresEngine(connection=connection)
    )

    assert scrape_runtime.acquire_scrape_slot() is False
    assert connection.closed is True

    # A later caller can retry after the remote lock becomes available.
    next_connection = _FakePostgresConnection([True, True])
    monkeypatch.setattr(
        scrape_runtime, "engine", _FakePostgresEngine(connection=next_connection)
    )
    assert scrape_runtime.acquire_scrape_slot() is True
    scrape_runtime.release_scrape_slot()


def test_postgres_advisory_lock_connection_error_releases_local_mutex(monkeypatch):
    monkeypatch.setattr(
        scrape_runtime,
        "engine",
        _FakePostgresEngine(error=OSError("database unavailable")),
    )

    try:
        scrape_runtime.acquire_scrape_slot()
    except OSError as exc:
        assert str(exc) == "database unavailable"
    else:
        raise AssertionError("database lock acquisition error was suppressed")

    assert scrape_runtime._SCRAPE_LOCK.acquire(blocking=False) is True
    scrape_runtime._SCRAPE_LOCK.release()
