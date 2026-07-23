from sqlalchemy import create_engine, text

import app.database as database


def test_create_schema_adds_model_archive_column_to_legacy_sqlite(
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

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.create_schema()
    database.create_schema()

    with legacy_engine.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(model_profiles)")
            )
        }
        stored = connection.execute(
            text(
                "SELECT id, archived_at FROM model_profiles "
                "WHERE id = 'legacy-profile'"
            )
        ).one()

    assert "archived_at" in columns
    assert stored == ("legacy-profile", None)
