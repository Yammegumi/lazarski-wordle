from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from word_database import DEFAULT_DB_PATH, ensure_schema, get_connection  # noqa: E402

BASE_URL = "https://wordle.global"
ARCHIVE_URL = f"{BASE_URL}/pl/archive?page=1"
USER_AGENT = "Mozilla/5.0 (compatible; WordlePLArchiveImporter/1.0)"
TIMEOUT_SECONDS = 25
CARD_PATTERN = re.compile(
    r'<a href="(?P<href>/pl/word/[^"]+)" class="[^"]*card[^"]*"[^>]*>(?P<body>.*?)</a>',
    re.DOTALL,
)


@dataclass(slots=True)
class WordRecord:
    word: str
    meaning: str | None
    image_url: str | None
    puzzle_number: int | None


class NextPageParser(HTMLParser):
    # Initialize parser state that stores the next archive page URL when present.
    def __init__(self) -> None:
        super().__init__()
        self.next_url: str | None = None

    # Capture <link rel="next"> and convert it to an absolute URL.
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        attr_map = dict(attrs)
        rel_value = (attr_map.get("rel") or "").lower()
        href = attr_map.get("href")
        if href and "next" in rel_value.split():
            self.next_url = urljoin(BASE_URL, href)


# Download a single archive page and decode it as UTF-8 HTML.
def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


# Remove HTML tags to extract plain text content.
def strip_tags(raw_html: str) -> str:
    return re.sub(r"<[^>]+>", "", raw_html)


# Extract text from card HTML using a regex and normalize entities.
def extract_text(body: str, pattern: str) -> str | None:
    match = re.search(pattern, body, re.DOTALL)
    if not match:
        return None
    value = unescape(strip_tags(match.group(1))).strip()
    return value or None


# Parse one archive card into a structured word record for database sync.
def parse_record_from_card(href: str, body: str, include_images: bool) -> WordRecord | None:
    word = extract_text(body, r'<div class="word-display"[^>]*>(.*?)</div>')
    if not word:
        slug = unquote(href.rstrip("/").split("/")[-1]).lower()
        word = slug
    if len(word) != 5:
        return None

    puzzle_number_text = extract_text(body, r'<span class="day-idx"[^>]*>#(\d+)</span>')
    puzzle_number = int(puzzle_number_text) if puzzle_number_text else None

    meaning = extract_text(body, r'<span class="def-body"[^>]*>(.*?)</span>')

    image_url: str | None = None
    if include_images:
        image_src = extract_text(body, r'<img src="([^"]+)"[^>]*class="art"')
        if image_src:
            image_url = urljoin(BASE_URL, image_src)

    return WordRecord(
        word=word.lower(),
        meaning=meaning,
        image_url=image_url,
        puzzle_number=puzzle_number,
    )


# Parse one archive page into unique records plus an optional next page URL.
def parse_archive_page(html: str, include_images: bool) -> tuple[list[WordRecord], str | None]:
    records: list[WordRecord] = []
    seen_words: set[str] = set()

    for match in CARD_PATTERN.finditer(html):
        href = match.group("href")
        body = match.group("body")
        record = parse_record_from_card(href=href, body=body, include_images=include_images)
        if record is None:
            continue
        if record.word in seen_words:
            continue
        seen_words.add(record.word)
        records.append(record)

    parser = NextPageParser()
    parser.feed(html)
    return records, parser.next_url


# Crawl all archive pages and aggregate unique records across pagination.
def crawl_archive_records(include_images: bool) -> list[WordRecord]:
    all_records: list[WordRecord] = []
    seen_words: set[str] = set()
    seen_pages: set[str] = set()
    next_page = ARCHIVE_URL
    page_number = 0

    while next_page:
        if next_page in seen_pages:
            break
        seen_pages.add(next_page)
        page_number += 1

        html = fetch_html(next_page)
        page_records, next_url = parse_archive_page(html=html, include_images=include_images)

        added = 0
        for record in page_records:
            if record.word in seen_words:
                continue
            seen_words.add(record.word)
            all_records.append(record)
            added += 1

        print(f"[archive] strona {page_number}: +{added} słów (łącznie {len(all_records)})")
        next_page = next_url
        time.sleep(0.08)

    return all_records


# Insert or update a single record in the local word_entries table.
def upsert_record(connection: sqlite3.Connection, record: WordRecord) -> None:
    connection.execute(
        """
        INSERT INTO word_entries (
            word,
            meaning,
            image_url,
            puzzle_number,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(word) DO UPDATE SET
            meaning = COALESCE(excluded.meaning, word_entries.meaning),
            image_url = COALESCE(excluded.image_url, word_entries.image_url),
            puzzle_number = COALESCE(excluded.puzzle_number, word_entries.puzzle_number),
            updated_at = excluded.updated_at
        """,
        (
            record.word,
            record.meaning,
            record.image_url,
            record.puzzle_number,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


# Synchronize the local SQLite database with records scraped from the archive.
def sync_database(db_path: Path, include_images: bool) -> None:
    records = crawl_archive_records(include_images=include_images)
    if not records:
        raise RuntimeError("Nie znaleziono rekordów do importu.")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as connection:
        ensure_schema(connection)

        for index, record in enumerate(records, start=1):
            upsert_record(connection, record)
            if index % 250 == 0:
                connection.commit()
                print(f"[sync] Zapisano {index}/{len(records)} rekordów...")

        connection.commit()
        total = connection.execute("SELECT COUNT(*) FROM word_entries").fetchone()[0]
        with_meaning = connection.execute(
            "SELECT COUNT(*) FROM word_entries WHERE meaning IS NOT NULL AND trim(meaning) <> ''"
        ).fetchone()[0]
        print(
            f"[done] Zaimportowano/odświeżono {len(records)} rekordów. "
            f"W bazie: {total}, z opisem: {with_meaning}."
        )


# Parse CLI arguments and run the archive synchronization procedure.
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Pobiera polskie archiwum Wordle z wordle.global i zapisuje bazę SQLite "
            "ze słowem, opisem oraz polem image_url."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Ścieżka do bazy SQLite (domyślnie: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--fetch-images",
        action="store_true",
        help=(
            "Zapisz URL-e miniatur z kart archiwum do kolumny image_url. "
            "Bez tej flagi image_url zostaje puste (miejsce pod przyszły feature)."
        ),
    )
    args = parser.parse_args()
    sync_database(db_path=args.db, include_images=args.fetch_images)


if __name__ == "__main__":
    main()
