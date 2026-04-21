import sqlite3
from pathlib import Path

from word_database import ensure_schema, get_connection


def test_ensure_schema_removes_legacy_date_and_source_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE word_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            meaning TEXT,
            image_url TEXT,
            source_url TEXT NOT NULL,
            puzzle_number INTEGER,
            puzzle_date TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO word_entries (word, meaning, image_url, source_url, puzzle_number, puzzle_date)
        VALUES ('kotek', 'opis', NULL, 'https://example.com', 123, '2026-01-01')
        """
    )
    connection.commit()
    connection.close()

    with get_connection(db_path) as migrated:
        ensure_schema(migrated)
        columns = [row["name"] for row in migrated.execute("PRAGMA table_info(word_entries)").fetchall()]
        row = migrated.execute(
            "SELECT word, meaning, image_url, puzzle_number FROM word_entries WHERE word = 'kotek'"
        ).fetchone()

    assert "source_url" not in columns
    assert "puzzle_date" not in columns
    assert row["word"] == "kotek"
    assert row["meaning"] == "opis"
    assert row["image_url"] is None
    assert row["puzzle_number"] == 123
