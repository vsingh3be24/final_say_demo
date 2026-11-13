import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from finalsay.migrations import run_migrations


def test_existing_notice_table_gets_defaulted_extraction_quality_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE notice (id INTEGER PRIMARY KEY, institution_id INTEGER, "
                "kind VARCHAR(20) NOT NULL, is_current BOOLEAN NOT NULL DEFAULT TRUE, "
                "source_key VARCHAR(500))"
            )

        run_migrations(engine)

        columns = {column["name"]: column for column in inspect(engine).get_columns("notice")}
        assert "extraction_quality" in columns
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO notice (id, kind) VALUES (1, 'official')"
            )
            quality = connection.exec_driver_sql(
                "SELECT extraction_quality FROM notice WHERE id = 1"
            ).scalar_one()
        assert quality == "unknown"
    finally:
        engine.dispose()


def test_legacy_institution_schema_defaults_scraper_to_unconfigured(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-institution.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE institution (id INTEGER PRIMARY KEY, name VARCHAR(200) "
                "NOT NULL, slug VARCHAR(100) NOT NULL, source_url VARCHAR(500), "
                "active BOOLEAN NOT NULL DEFAULT TRUE)"
            )

        run_migrations(engine)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO institution (id, name, slug) VALUES (1, 'Example', 'example')"
            )
            scrape_type = connection.exec_driver_sql(
                "SELECT scrape_type FROM institution WHERE id = 1"
            ).scalar_one()
        assert scrape_type == "unconfigured"
    finally:
        engine.dispose()


def test_benchmark_annotations_are_unique_per_reviewer_and_pair(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'benchmark-unique.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE benchmark_annotation (id INTEGER PRIMARY KEY, "
                "pair_id INTEGER NOT NULL, annotator VARCHAR(100) NOT NULL, "
                "user_id INTEGER, label VARCHAR(20) NOT NULL)"
            )

        run_migrations(engine)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO benchmark_annotation (pair_id, annotator, user_id, label) "
                "VALUES (1, 'reviewer-a', 10, 'consistent'), "
                "(1, 'reviewer-b', 11, 'contradictory'), "
                "(1, 'legacy-seed-a', NULL, 'cancelled'), "
                "(1, 'legacy-seed-b', NULL, 'extended')"
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO benchmark_annotation "
                    "(pair_id, annotator, user_id, label) "
                    "VALUES (1, 'reviewer-a-again', 10, 'superseded')"
                )
    finally:
        engine.dispose()


def test_benchmark_migration_refuses_preexisting_duplicate_reviewer_labels(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'benchmark-duplicate.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE benchmark_annotation (id INTEGER PRIMARY KEY, "
                "pair_id INTEGER NOT NULL, annotator VARCHAR(100) NOT NULL, "
                "user_id INTEGER, label VARCHAR(20) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO benchmark_annotation "
                "(pair_id, annotator, user_id, label) VALUES "
                "(1, 'reviewer-a', 10, 'consistent'), "
                "(1, 'reviewer-a', 10, 'contradictory')"
            )

        with pytest.raises(RuntimeError, match="one benchmark annotation per reviewer and pair"):
            run_migrations(engine)
    finally:
        engine.dispose()


def test_current_official_source_keys_are_unique_but_versions_can_share_a_key(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'source-key-unique.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE notice (id INTEGER PRIMARY KEY, institution_id INTEGER, "
                "kind VARCHAR(20) NOT NULL, is_current BOOLEAN NOT NULL DEFAULT TRUE, "
                "source_key VARCHAR(500))"
            )

        run_migrations(engine)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO notice (institution_id, kind, is_current, source_key) "
                "VALUES (7, 'official', TRUE, 'portal:notice-1')"
            )
            connection.exec_driver_sql(
                "INSERT INTO notice (institution_id, kind, is_current, source_key) "
                "VALUES (7, 'official', FALSE, 'portal:notice-1')"
            )
            connection.exec_driver_sql(
                "INSERT INTO notice (institution_id, kind, is_current, source_key) "
                "VALUES (7, 'submission', TRUE, 'portal:notice-1')"
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO notice (institution_id, kind, is_current, source_key) "
                    "VALUES (7, 'official', TRUE, 'portal:notice-1')"
                )
    finally:
        engine.dispose()


def test_migration_refuses_existing_duplicate_current_official_source_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'source-key-duplicate.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE notice (id INTEGER PRIMARY KEY, institution_id INTEGER, "
                "kind VARCHAR(20) NOT NULL, is_current BOOLEAN NOT NULL DEFAULT TRUE, "
                "source_key VARCHAR(500))"
            )
            connection.exec_driver_sql(
                "INSERT INTO notice VALUES "
                "(1, 7, 'official', TRUE, 'portal:notice-1'), "
                "(2, 7, 'official', TRUE, 'portal:notice-1')"
            )

        with pytest.raises(RuntimeError, match="resolve duplicate current rows"):
            run_migrations(engine)
    finally:
        engine.dispose()
