"""Small forward-only migrations for the prototype's SQLite/Postgres schema.

The project originally created its schema with ``metadata.create_all`` and had
no migration runner. New tables are created from ORM metadata; this module adds
the new nullable/defaulted columns to existing databases before the app serves
requests. Statements are intentionally explicit so they remain auditable.
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from finalsay.services.notice_dates import parse_publication_date


_COLUMNS: dict[str, dict[str, str]] = {
    "institution": {
        "scrape_type": "VARCHAR(32) NOT NULL DEFAULT 'unconfigured'",
        "scrape_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
    "user": {
        "institution_id": "INTEGER REFERENCES institution(id)",
    },
    "notice": {
        "title": "VARCHAR(500)",
        "published_date": "VARCHAR(80)",
        "published_on": "DATE",
        "source_key": "VARCHAR(500)",
        "source_content_sha256": "VARCHAR(64)",
        "extraction_quality": "VARCHAR(24) NOT NULL DEFAULT 'unknown'",
        "version_no": "INTEGER NOT NULL DEFAULT 1",
        "is_current": "BOOLEAN NOT NULL DEFAULT TRUE",
        "previous_version_id": "INTEGER",
    },
    "merkle_root": {
        "anchor_chain_id": "INTEGER",
        "anchor_network": "VARCHAR(40)",
        "anchor_contract_address": "VARCHAR(42)",
        "anchor_issuer_address": "VARCHAR(42)",
        "anchor_issuer_id": "VARCHAR(64)",
        "anchor_batch_id": "VARCHAR(64)",
        "anchor_block_number": "INTEGER",
        "anchor_timestamp": "TIMESTAMP",
        "anchor_submitted_at": "TIMESTAMP",
        "anchor_status": "VARCHAR(20) NOT NULL DEFAULT 'local'",
        "anchor_error": "TEXT",
    },
    "benchmark_annotation": {
        "user_id": "INTEGER REFERENCES user(id)",
    },
}


def run_migrations(engine: Engine) -> None:
    """Add missing columns once; safe to call at every application startup."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in _COLUMNS.items():
            if table not in existing_tables:
                continue
            current = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, sql_type in columns.items():
                if name not in current:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'
                    )
                    current.add(name)
                    if table == "notice" and name == "published_on":
                        existing_dates = connection.exec_driver_sql(
                            "SELECT id, published_date FROM notice "
                            "WHERE published_date IS NOT NULL"
                        ).all()
                        date_updates = [
                            {"notice_id": notice_id, "published_on": parsed}
                            for notice_id, raw_date in existing_dates
                            if (parsed := parse_publication_date(raw_date)) is not None
                        ]
                        if date_updates:
                            connection.execute(
                                text(
                                    "UPDATE notice SET published_on = :published_on "
                                    "WHERE id = :notice_id"
                                ),
                                date_updates,
                            )
        if "notice" in existing_tables:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_notice_student_feed "
                "ON notice (institution_id, kind, is_current, published_on, id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_notice_source_key ON notice (source_key)"
            )
            duplicate = connection.exec_driver_sql(
                """
                SELECT institution_id, source_key, COUNT(*)
                FROM notice
                WHERE kind = 'official'
                  AND is_current = TRUE
                  AND source_key IS NOT NULL
                GROUP BY institution_id, source_key
                HAVING COUNT(*) > 1
                LIMIT 1
                """
            ).first()
            if duplicate is not None:
                raise RuntimeError(
                    "cannot enforce unique current official source keys: "
                    f"institution_id={duplicate[0]}, source_key={str(duplicate[1])[:120]!r}, "
                    f"count={duplicate[2]}; resolve duplicate current rows before startup"
                )
            connection.exec_driver_sql(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_notice_current_official_source_key
                ON notice (institution_id, source_key)
                WHERE kind = 'official' AND is_current = TRUE AND source_key IS NOT NULL
                """
            )
        if "benchmark_annotation" in existing_tables:
            duplicate_annotation = connection.exec_driver_sql(
                """
                SELECT user_id, pair_id, COUNT(*)
                FROM benchmark_annotation
                WHERE user_id IS NOT NULL
                GROUP BY user_id, pair_id
                HAVING COUNT(*) > 1
                LIMIT 1
                """
            ).first()
            if duplicate_annotation is not None:
                raise RuntimeError(
                    "cannot enforce one benchmark annotation per reviewer and pair: "
                    f"user_id={duplicate_annotation[0]}, pair_id={duplicate_annotation[1]}, "
                    f"count={duplicate_annotation[2]}; resolve duplicate annotations before startup"
                )
            connection.exec_driver_sql(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    uq_benchmark_annotation_reviewer_pair
                ON benchmark_annotation (user_id, pair_id)
                WHERE user_id IS NOT NULL
                """
            )
