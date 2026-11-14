"""Application configuration via pydantic-settings.

All settings are driven by environment variables with the ``FINALSAY_`` prefix
(see design.md section 2). A ``.env`` file in the working directory is honored.
Defaults use SQLite, local semantic comparison, and a LOCAL anchor. The cached
semantic models run on CPU without paid APIs; a first run may need model weights.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Feature switches and runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="FINALSAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "production"] = "development"

    # Database (SQLite default; Postgres opt-in via FINALSAY_DATABASE_URL).
    database_url: str = "sqlite:///./finalsay.db"

    # Semantic is the application default; mock remains the deterministic test/demo option.
    comparison_model: str = "semantic"
    hf_model_name: str = "facebook/bart-large-mnli"
    semantic_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    semantic_nli_model: str = "cross-encoder/nli-deberta-v3-small"

    # Anchor: local append-only hash chain (default) | polygon (opt-in).
    anchor: str = "local"

    # Gates are validated on non-held-out fixtures; scores are not calibrated probabilities.
    confidence_threshold: float = 0.20
    semantic_candidate_threshold: float = 0.55

    # Auth (HS256 signing secret; dev default, override in production).
    jwt_secret: str = "dev-insecure-finalsay-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24

    # Comma-separated browser origins allowed to call the API ("*" allows all).
    cors_origins: str = "*"

    # Automatic public notice polling; set to 0 to disable the background poller.
    # Poll public notice portals every two hours by default; this is frequent
    # enough to catch multiple daily postings while respecting host throttling.
    scrape_interval_seconds: int = Field(default=7_200, ge=0)

    # Polygon Amoy on-chain anchoring (only used when anchor == "polygon").
    polygon_rpc_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "POLYGON_AMOY_RPC_URL", "FINALSAY_POLYGON_RPC_URL"
        ),
    )
    polygon_private_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices(
            "POLYGON_AMOY_PRIVATE_KEY", "FINALSAY_POLYGON_PRIVATE_KEY"
        ),
    )
    polygon_contract: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "FINALSAY_ANCHOR_CONTRACT_ADDRESS", "FINALSAY_POLYGON_CONTRACT"
        ),
    )
    polygon_chain_id: int = Field(
        default=80002,
        validation_alias=AliasChoices(
            "POLYGON_AMOY_CHAIN_ID", "FINALSAY_POLYGON_CHAIN_ID"
        ),
    )
    polygon_receipt_timeout: int = 45

    # OCR: path to the tesseract binary, if present ("auto" -> autodetect).
    tesseract_cmd: str = "auto"
    tesseract_languages: str = "eng+hin+kan+mar"

    @model_validator(mode="after")
    def require_safe_production_configuration(self) -> "Settings":
        """Refuse production startup with local-only authentication or storage."""
        if self.environment != "production":
            return self

        if (
            self.jwt_secret == "dev-insecure-finalsay-secret-change-me"
            or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "production requires FINALSAY_JWT_SECRET with at least 32 characters"
            )

        if not self.database_url.startswith(
            ("postgresql://", "postgresql+psycopg2://")
        ):
            raise ValueError(
                "production requires FINALSAY_DATABASE_URL using the installed PostgreSQL driver"
            )

        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        invalid_origins = []
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or "*" in parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                invalid_origins.append(origin)
        if not origins or invalid_origins:
            raise ValueError(
                "production requires explicit HTTPS origins in FINALSAY_CORS_ORIGINS"
            )

        if self.comparison_model == "mock":
            raise ValueError("production cannot use the mock comparison model")

        if self.scrape_interval_seconds == 0:
            raise ValueError("production requires scheduled official-source polling")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
