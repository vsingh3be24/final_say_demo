"""Production configuration must not inherit local-only defaults."""

import pytest
from pydantic import ValidationError

from finalsay.config import Settings


def _production_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "environment": "production",
        "database_url": "postgresql+psycopg2://app:secret@db.example/finalsay",
        "jwt_secret": "r" * 48,
        "cors_origins": "https://finalsay.example.edu",
        "comparison_model": "semantic",
        "scrape_interval_seconds": 7200,
    }
    values.update(overrides)
    return Settings(**values)


def test_local_configuration_keeps_development_defaults():
    # The test suite sets FINALSAY_DATABASE_URL before importing settings.
    settings = Settings(
        _env_file=None,
        environment="development",
        database_url="sqlite:///./finalsay.db",
    )

    assert settings.environment == "development"
    assert settings.database_url == "sqlite:///./finalsay.db"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("jwt_secret", "dev-insecure-finalsay-secret-change-me", "JWT_SECRET"),
        ("jwt_secret", "short", "JWT_SECRET"),
        ("database_url", "sqlite:///./finalsay.db", "PostgreSQL"),
        ("cors_origins", "*", "HTTPS origins"),
        ("cors_origins", "http://finalsay.example.edu", "HTTPS origins"),
        ("cors_origins", "https://*.example.edu", "HTTPS origins"),
        ("cors_origins", "https://finalsay.example.edu/path", "HTTPS origins"),
        ("comparison_model", "mock", "mock comparison model"),
        ("scrape_interval_seconds", 0, "scheduled official-source polling"),
    ],
)
def test_production_rejects_local_or_unsafe_settings(key, value, message):
    with pytest.raises(ValidationError, match=message):
        _production_settings(**{key: value})


def test_production_accepts_managed_database_and_explicit_https_origins():
    settings = _production_settings(
        cors_origins="https://finalsay.example.edu,https://www.example.edu"
    )

    assert settings.environment == "production"

