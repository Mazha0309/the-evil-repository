from sqlalchemy import create_engine, text

import app.database as database


def test_create_schema_adds_archive_columns_to_legacy_sqlite(
    monkeypatch,
) -> None:
    legacy_engine = create_engine("sqlite://")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE platform_settings "
                "(name VARCHAR(80) PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE model_profiles "
                "(id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO model_profiles (id) VALUES ('legacy-profile')")
        )
        connection.execute(
            text(
                "CREATE TABLE benchmark_runs "
                "(id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO benchmark_runs (id) VALUES ('legacy-run')")
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.create_schema()
    database.create_schema()

    with legacy_engine.connect() as connection:
        model_columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(model_profiles)")
            )
        }
        run_columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(benchmark_runs)")
            )
        }
        stored_model = connection.execute(
            text(
                "SELECT id, archived_at FROM model_profiles "
                "WHERE id = 'legacy-profile'"
            )
        ).one()
        stored_run = connection.execute(
            text(
                "SELECT id, archived_at FROM benchmark_runs "
                "WHERE id = 'legacy-run'"
            )
        ).one()

    assert "archived_at" in model_columns
    assert "archived_at" in run_columns
    assert stored_model == ("legacy-profile", None)
    assert stored_run == ("legacy-run", None)
