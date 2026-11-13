"""FastAPI application factory: logging, middleware, routers, table creation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Event, Thread
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from finalsay.api import auth as auth_api
from finalsay.api import benchmark_admin as benchmark_admin_api
from finalsay.api import comparison as comparison_api
from finalsay.api import ingestion as ingestion_api
from finalsay.api import issuer as issuer_api
from finalsay.api import issuer_memberships as issuer_memberships_api
from finalsay.api import notices as notices_api
from finalsay.api import provenance as provenance_api
from finalsay.api import reviewer as reviewer_api
from finalsay.config import get_settings
from finalsay.db import Base, engine, get_db
from finalsay.logging_conf import configure_logging
from finalsay.migrations import run_migrations
from finalsay.schemas import HealthResponse

# Import models so their tables register on Base.metadata before create_all.
from finalsay import models  # noqa: F401


def create_app() -> FastAPI:
    logger = configure_logging()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        interval = settings.scrape_interval_seconds
        stop_event = Event()
        worker: Thread | None = None
        if interval > 0:
            worker = Thread(
                target=scheduled_scrape_loop,
                args=(stop_event, interval, logger),
                name="finalsay-notice-scraper",
                daemon=True,
            )
            worker.start()
            logger.info("Scheduled notice polling enabled (every %d seconds)", interval)
        else:
            logger.info("Scheduled notice polling disabled")
        try:
            yield
        finally:
            stop_event.set()
            if worker is not None:
                worker.join(timeout=2)

    from finalsay.services.scrape_runtime import scheduled_scrape_loop

    app = FastAPI(title="FinalSay", version="0.2.0", lifespan=lifespan)

    # CORS for split deployment (e.g. GitHub Pages frontend talking to an EC2
    # backend). Auth rides in the Authorization header, not cookies, so
    # credentialed requests are never needed — which is what lets a deployment
    # keep the wildcard default without the browser rejecting the response.
    origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Create tables on startup (fine for SQLite demo; Postgres uses same models).
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    try:
        from finalsay.db import SessionLocal
        from finalsay.seed.seed import _seed_users
        with SessionLocal() as seed_db:
            _seed_users(seed_db)
            seed_db.commit()
    except Exception as exc:
        logger.warning("Auto-seed users skipped: %s", exc)

    try:
        from finalsay.services.source_onboarding import onboard
        onboard(apply=True)
    except Exception as exc:
        logger.warning("Auto-onboard sources skipped: %s", exc)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/health/ready", response_model=HealthResponse, tags=["health"])
    def health_ready(db: Session = Depends(get_db)) -> HealthResponse:
        """Readiness probe: fails while the database is unreachable."""
        db.execute(text("SELECT 1"))
        return HealthResponse(status="ok")

    app.include_router(auth_api.router)
    app.include_router(benchmark_admin_api.router)
    app.include_router(provenance_api.router)
    app.include_router(comparison_api.router)
    app.include_router(ingestion_api.router)
    app.include_router(notices_api.router)
    app.include_router(reviewer_api.router)
    app.include_router(issuer_api.router)
    app.include_router(issuer_memberships_api.router)
    return app


app = create_app()

