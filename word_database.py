from __future__ import annotations

import sqlite3
from pathlib import Path

from wordle_logic import WORD_LENGTH, is_valid_word_shape

DEFAULT_DB_PATH = Path("data/wordle_pl.sqlite3")


# Return a list of column names for the given SQLite table.
def _table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


# Rebuild legacy word_entries schema without deprecated source and date columns.
def _migrate_word_entries_without_date_and_source(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            CREATE TABLE word_entries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL UNIQUE,
                meaning TEXT,
                image_url TEXT,
                puzzle_number INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO word_entries_new (
                id,
                word,
                meaning,
                image_url,
                puzzle_number,
                created_at,
                updated_at
            )
            SELECT
                id,
                word,
                meaning,
                image_url,
                puzzle_number,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
            FROM word_entries
            """
        )
        connection.execute("DROP TABLE word_entries")
        connection.execute("ALTER TABLE word_entries_new RENAME TO word_entries")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


# Ensure the current schema exists and run required migrations before use.
def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS word_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            meaning TEXT,
            image_url TEXT,
            puzzle_number INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = _table_columns(connection, "word_entries")
    if "source_url" in columns or "puzzle_date" in columns:
        _migrate_word_entries_without_date_and_source(connection)
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_word_entries_puzzle_number
        ON word_entries (puzzle_number)
        """
    )
    connection.commit()


# Open a SQLite connection with Row access and ensure the parent directory exists.
def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


# Load and validate all 5-letter words from the database dictionary table.
def load_words_from_database(db_path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    path = Path(db_path)
    if not path.exists():
        raise ValueError(f"Nie znaleziono bazy słów: {path}")

    with get_connection(path) as connection:
        ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT word
            FROM word_entries
            WHERE length(word) = ?
            ORDER BY word
            """,
            (WORD_LENGTH,),
        ).fetchall()

    words = [row["word"] for row in rows]
    invalid = [word for word in words if not is_valid_word_shape(word)]
    if invalid:
        raise ValueError(
            "Baza zawiera niepoprawne słowa, np.: "
            + ", ".join(invalid[:5])
        )
    if not words:
        raise ValueError("Baza słów nie zawiera poprawnych 5-literowych haseł.")
    return words
