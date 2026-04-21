from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from word_database import DEFAULT_DB_PATH, ensure_schema, get_connection  # noqa: E402
from wordle_logic import is_valid_word_shape, normalize_word  # noqa: E402

DEFAULT_SOURCE_PATH = Path("data/slowa.txt")
DEFAULT_FALLBACK_PATH = Path("words.txt")
IMPORT_TABLE_NAME = "word_entries_import"
BATCH_SIZE = 5000
PROGRESS_EVERY_LINES = 250000


# Create or clear a temporary import table used for deduplication via UNIQUE constraint.
def prepare_import_table(connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {IMPORT_TABLE_NAME} (
            word TEXT PRIMARY KEY
        )
        """
    )
    connection.execute(f"DELETE FROM {IMPORT_TABLE_NAME}")
    connection.commit()


# Insert one batch into the import table while ignoring duplicate words.
def flush_import_batch(connection, batch: list[tuple[str]]) -> None:
    if not batch:
        return
    connection.executemany(
        f"INSERT OR IGNORE INTO {IMPORT_TABLE_NAME} (word) VALUES (?)",
        batch,
    )


# Load valid words into the temporary import table and report input/filter stats.
def import_filtered_words(connection, source_path: Path) -> tuple[int, int]:
    total_lines = 0
    valid_lines = 0
    batch: list[tuple[str]] = []

    with source_path.open("r", encoding="utf-8") as source_file:
        for line in source_file:
            total_lines += 1
            if total_lines % PROGRESS_EVERY_LINES == 0:
                print(f"[import] processed lines: {total_lines}")

            candidate = normalize_word(line)
            if not candidate:
                continue
            if not is_valid_word_shape(candidate):
                continue

            valid_lines += 1
            batch.append((candidate,))
            if len(batch) >= BATCH_SIZE:
                flush_import_batch(connection, batch)
                connection.commit()
                batch.clear()

    if batch:
        flush_import_batch(connection, batch)
        connection.commit()

    return total_lines, valid_lines


# Replace the game dictionary table with sorted words from the deduplicated import table.
def replace_wordle_dictionary(connection) -> int:
    connection.execute("BEGIN")
    connection.execute("DELETE FROM word_entries")
    connection.execute(
        f"""
        INSERT INTO word_entries (word, meaning, image_url, puzzle_number)
        SELECT word, NULL, NULL, NULL
        FROM {IMPORT_TABLE_NAME}
        ORDER BY word
        """
    )
    connection.execute(f"DELETE FROM {IMPORT_TABLE_NAME}")
    connection.execute("COMMIT")
    return connection.execute("SELECT COUNT(*) FROM word_entries").fetchone()[0]


# Export the active Wordle dictionary into fallback text format, one word per line.
def export_fallback_words(connection, fallback_path: Path) -> int:
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    words = connection.execute("SELECT word FROM word_entries ORDER BY word").fetchall()
    with fallback_path.open("w", encoding="utf-8", newline="\n") as fallback_file:
        for row in words:
            fallback_file.write(f"{row['word']}\n")
    return len(words)


# Parse CLI arguments and run the dictionary replacement pipeline.
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Filtruje data/slowa.txt do poprawnych słów 5-literowych i podmienia "
            "słownik Wordle w SQLite oraz w pliku words.txt."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_PATH,
        help=f"Plik źródłowy ze słowami (domyślnie: {DEFAULT_SOURCE_PATH})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Plik bazy SQLite Wordle (domyślnie: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--fallback",
        type=Path,
        default=DEFAULT_FALLBACK_PATH,
        help=f"Plik fallback words.txt (domyślnie: {DEFAULT_FALLBACK_PATH})",
    )
    args = parser.parse_args()

    source_path = args.source
    if not source_path.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku źródłowego: {source_path}")

    with get_connection(args.db) as connection:
        ensure_schema(connection)
        prepare_import_table(connection)
        total_lines, valid_lines = import_filtered_words(connection, source_path)
        unique_words = connection.execute(
            f"SELECT COUNT(*) FROM {IMPORT_TABLE_NAME}"
        ).fetchone()[0]
        final_count = replace_wordle_dictionary(connection)
        exported_count = export_fallback_words(connection, args.fallback)

    print(f"[done] source lines: {total_lines}")
    print(f"[done] valid 5-letter entries: {valid_lines}")
    print(f"[done] unique 5-letter entries: {unique_words}")
    print(f"[done] dictionary replaced in DB: {final_count}")
    print(f"[done] words exported to fallback: {exported_count}")


if __name__ == "__main__":
    main()
