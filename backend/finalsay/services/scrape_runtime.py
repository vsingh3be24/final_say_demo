"""Shared lock and interval scheduler for configured source polling."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import tempfile
from threading import Event, Lock, local

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from finalsay.db import SessionLocal, engine
from finalsay.models import ScrapeRun
from finalsay.services.document_extraction_backfill import (
    refresh_unknown_document_extractions,
)
from finalsay.services.ingestion import fetch_all

_SCRAPE_LOCK = Lock()
_DATABASE_LOCK = local()
_POSTGRES_ADVISORY_LOCK_KEY = 0x46494E414C534159  # stable ASCII key: "FINALSAY"
_SOURCE_RETRY_BASE_SECONDS = 300
_SOURCE_RETRY_MAX_SECONDS = 3_600
_TRANSIENT_SOURCE_ERROR_MARKERS = (
    "request failed:",
    "could not resolve configured source host",
    "dns lookup timed out",
    "timed out",
    "timeouterror",
    "connection reset",
    "connection refused",
    "temporary failure",
    "temporarily unavailable",
    "http error 429",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _source_retry_delay(interval_seconds: int, failure_streak: int) -> int:
    """Return a bounded exponential delay after a failed scheduled cycle."""
    exponent = max(0, failure_streak - 1)
    retry_seconds = min(
        _SOURCE_RETRY_MAX_SECONDS,
        _SOURCE_RETRY_BASE_SECONDS * (2**exponent),
    )
    return min(interval_seconds, retry_seconds)


def _has_transient_source_errors(summary: dict, extraction_summary: dict) -> bool:
    """Only accelerate retries for failures likely to clear without operator action.

    Expected partial results such as an in-progress historical backfill,
    allowlist-skipped attachments, or a consistently oversized PDF remain on
    the normal cadence. Network and upstream service failures retry sooner.
    """
    errors = [
        str(result.get("error") or "")
        for result in summary.get("institutions", [])
    ]
    errors.extend(str(error) for error in extraction_summary.get("errors", []))
    if summary.get("errors") and not errors:
        # An aggregate error without source details is safer to retry.
        return True
    return any(
        marker in error.casefold()
        for error in errors
        for marker in _TRANSIENT_SOURCE_ERROR_MARKERS
    )


def _persist_document_extraction_errors(
    db: Session, extraction_summary: dict, logger: logging.Logger
) -> None:
    for institution_result in extraction_summary.get("institutions", []):
        institution_errors = institution_result.get("errors", [])
        if not institution_errors:
            continue
        for error in institution_errors:
            logger.warning(
                "Scheduled document extraction failed for %s: %s",
                institution_result["slug"],
                error,
            )
        latest_run = db.scalar(
            select(ScrapeRun)
            .where(ScrapeRun.institution_id == institution_result["institution_id"])
            .order_by(ScrapeRun.id.desc())
            .limit(1)
        )
        if latest_run is None:
            continue
        detail = "; ".join(institution_errors)[:1500]
        prefix = f"document extraction errors: {detail}"
        latest_run.error = (
            f"{latest_run.error} | {prefix}" if latest_run.error else prefix
        )[:4000]
        if latest_run.status == "ok":
            latest_run.status = "partial"


def acquire_scrape_slot() -> bool:
    """Claim the poll slot locally and, on PostgreSQL, across API processes.

    PostgreSQL holds a session-level advisory lock on a dedicated pooled
    connection for the duration of a poll. SQLite uses a host-local file lock
    so an API worker and a separate CLI/manual poll cannot overlap.
    """
    if not _SCRAPE_LOCK.acquire(blocking=False):
        return False

    connection = None
    try:
        if engine.dialect.name == "postgresql":
            connection = engine.connect()
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": _POSTGRES_ADVISORY_LOCK_KEY},
            ).scalar_one()
            connection.commit()
            if not acquired:
                connection.close()
                _SCRAPE_LOCK.release()
                return False
            _DATABASE_LOCK.connection = connection
        elif engine.dialect.name == "sqlite":
            database_path = engine.url.database
            if database_path and database_path != ":memory:":
                absolute_path = os.path.abspath(database_path)
                lock_name = hashlib.sha256(absolute_path.encode()).hexdigest()
                lock_path = os.path.join(
                    tempfile.gettempdir(), f"finalsay-scrape-{lock_name}.lock"
                )
                file_descriptor = os.open(
                    lock_path, os.O_CREAT | os.O_RDWR, 0o600
                )
                try:
                    fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(file_descriptor)
                    _SCRAPE_LOCK.release()
                    return False
                _DATABASE_LOCK.file_descriptor = file_descriptor
        return True
    except Exception:
        try:
            if connection is not None:
                connection.close()
        finally:
            _SCRAPE_LOCK.release()
        raise


def release_scrape_slot() -> None:
    connection = getattr(_DATABASE_LOCK, "connection", None)
    file_descriptor = getattr(_DATABASE_LOCK, "file_descriptor", None)
    try:
        if connection is not None:
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": _POSTGRES_ADVISORY_LOCK_KEY},
                ).scalar_one()
                connection.commit()
            finally:
                connection.close()
                del _DATABASE_LOCK.connection
        if file_descriptor is not None:
            try:
                fcntl.flock(file_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(file_descriptor)
                del _DATABASE_LOCK.file_descriptor
    finally:
        _SCRAPE_LOCK.release()


def scheduled_scrape_loop(stop_event: Event, interval_seconds: int, logger: logging.Logger) -> None:
    """Poll configured sources periodically without overlapping another poll.

    The first poll runs on startup. Manual admin polling is also available
    immediately through the API/UI and shares the same local and database lock.
    """
    failure_streak = 0
    while not stop_event.is_set():
        try:
            acquired = acquire_scrape_slot()
        except Exception:  # noqa: BLE001 - retry coordination outages next cycle
            logger.exception("Could not acquire the source-poll coordination lock")
            if stop_event.wait(min(interval_seconds, 60)):
                break
            continue
        if not acquired:
            logger.info("Skipping scheduled notice poll because another poll is active")
            # A CLI/manual replay may hold the shared lock for many minutes.
            # Retry soon after contention clears instead of silently missing
            # the next scheduled poll for the entire normal interval.
            if stop_event.wait(min(interval_seconds, 60)):
                break
            continue
        next_delay = interval_seconds
        db = SessionLocal()
        try:
            summary = fetch_all(
                db, include_fixtures=False, commit_each_source=True
            )
            extraction_refresh = refresh_unknown_document_extractions(
                db, per_institution=2
            )
            _persist_document_extraction_errors(db, extraction_refresh, logger)
            db.commit()
            if _has_transient_source_errors(summary, extraction_refresh):
                failure_streak += 1
                next_delay = _source_retry_delay(interval_seconds, failure_streak)
                logger.warning(
                    "Source poll had transient errors; retrying in %d seconds (failure streak %d)",
                    next_delay,
                    failure_streak,
                )
            else:
                failure_streak = 0
            logger.info(
                "Scheduled notice poll completed: created=%d modified=%d unchanged=%d errors=%d extractions=%d extraction_errors=%d",
                summary["created"], summary["modified"], summary["skipped"], summary["errors"],
                extraction_refresh["stored"], len(extraction_refresh["errors"]),
            )
        except Exception:  # noqa: BLE001 - scheduler must survive a failed cycle
            db.rollback()
            failure_streak += 1
            next_delay = _source_retry_delay(interval_seconds, failure_streak)
            logger.exception("Scheduled notice poll failed")
        finally:
            db.close()
            release_scrape_slot()
        if stop_event.wait(next_delay):
            break
