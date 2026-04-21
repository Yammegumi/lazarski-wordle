from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from word_database import DEFAULT_DB_PATH, ensure_schema, get_connection  # noqa: E402
from wordle_logic import WORD_LENGTH, normalize_word  # noqa: E402

WIKTIONARY_API_URL = "https://pl.wiktionary.org/w/api.php"
WIKIPEDIA_API_URL = "https://pl.wikipedia.org/w/api.php"
DEFAULT_ODM_SOURCE = "https://raw.githubusercontent.com/ostr00000/jezyk-polski-slowniki/master/odm.txt"
USER_AGENT = "lazarski-wordle/1.0 (local dictionary enrichment script)"
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_RETRIES = 8
BATCH_SIZE = 50
WIKTIONARY_REQUEST_SLEEP_SECONDS = 0.05
WIKIPEDIA_REQUEST_SLEEP_SECONDS = 0.35
DB_WRITE_BATCH_SIZE = 1000
POLISH_SECTION_TOKEN = "({{j\u0119zyk polski}})"
PLACEHOLDER_DESCRIPTION = "Brak krotkiego opisu slownikowego."
MAX_MEANING_LENGTH = 190
WIKTIONARY_CACHE_PATH = Path("data/cache_wiktionary_meanings.json")
WIKIPEDIA_CACHE_PATH = Path("data/cache_wikipedia_summaries.json")

MEANING_LINE_PATTERN = re.compile(r"^:\s*\([0-9]+\.[0-9]+(?:-[0-9]+)?\)\s*(.+)$")
SELF_CLOSING_REF_PATTERN = re.compile(r"<ref[^>/]*/>")
REF_BLOCK_PATTERN = re.compile(r"<ref[^>]*>.*?</ref>", re.S)
TEMPLATE_PATTERN = re.compile(r"\{\{[^{}]*\}\}")
WIKI_LINK_WITH_LABEL_PATTERN = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(slots=True)
class MeaningStats:
    total_words: int = 0
    lemma_mapped_words: int = 0
    wiktionary_meanings: int = 0
    wikipedia_meanings: int = 0
    placeholders: int = 0


# Yield consecutive fixed-size chunks from a sequence.
def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


# Remove nested-less templates by repeatedly stripping innermost template fragments.
def remove_templates(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = TEMPLATE_PATTERN.sub("", text)
    return text.replace("{{", "").replace("}}", "")


# Convert Wikisyntax and HTML leftovers into compact plain text.
def cleanup_definition_text(text: str) -> str:
    cleaned = SELF_CLOSING_REF_PATTERN.sub("", text)
    cleaned = REF_BLOCK_PATTERN.sub("", cleaned)
    cleaned = remove_templates(cleaned)
    cleaned = WIKI_LINK_WITH_LABEL_PATTERN.sub(r"\2", cleaned)
    cleaned = WIKI_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = HTML_TAG_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("''", "")
    cleaned = unescape(cleaned)
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned).strip(" ;,:-")

    if ". " in cleaned:
        first_sentence = cleaned.split(". ", maxsplit=1)[0].strip()
        if len(first_sentence) >= 30:
            cleaned = first_sentence

    if len(cleaned) > MAX_MEANING_LENGTH:
        cleaned = f"{cleaned[: MAX_MEANING_LENGTH - 3].rstrip()}..."
    return cleaned


# Return Polish language section body from Wiktionary page wikitext.
def extract_polish_section(wikitext: str) -> str:
    lines = wikitext.splitlines()
    section_start = None

    for line_number, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("==") and stripped.endswith("==") and POLISH_SECTION_TOKEN in stripped:
            section_start = line_number + 1
            break

    if section_start is None:
        return ""

    section_end = len(lines)
    for line_number in range(section_start, len(lines)):
        stripped = lines[line_number].strip()
        if stripped.startswith("==") and stripped.endswith("=="):
            section_end = line_number
            break

    return "\n".join(lines[section_start:section_end])


# Extract first short definition from the Polish meanings block in Wiktionary content.
def extract_wiktionary_definition(wikitext: str) -> str | None:
    polish_section = extract_polish_section(wikitext)
    if not polish_section:
        return None

    marker = "{{znaczenia}}"
    marker_index = polish_section.find(marker)
    if marker_index < 0:
        return None

    tail = polish_section[marker_index + len(marker) :]
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("{{") and (
            stripped.startswith("{{odmiana")
            or stripped.startswith("{{przyk")
            or stripped.startswith("{{sk")
            or stripped.startswith("{{kolok")
            or stripped.startswith("{{synon")
        ):
            break

        match = MEANING_LINE_PATTERN.match(stripped)
        if not match:
            continue

        candidate = cleanup_definition_text(match.group(1))
        if candidate:
            return candidate

    return None


# Resolve MediaWiki normalized/redirected titles back to requested term keys.
def resolve_requested_title(
    term: str,
    normalized_map: dict[str, str],
    redirect_map: dict[str, str],
) -> str:
    resolved = normalize_word(term)
    resolved = normalize_word(normalized_map.get(resolved, resolved))

    visited: set[str] = set()
    while resolved in redirect_map and resolved not in visited:
        visited.add(resolved)
        resolved = normalize_word(redirect_map[resolved])

    return resolved


# Perform one POST request against MediaWiki API with retry/backoff.
def mediawiki_post(api_url: str, payload: dict[str, str]) -> dict:
    encoded_payload = urlencode(payload).encode("utf-8")
    request = Request(
        api_url,
        data=encoded_payload,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )

    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            last_error = error
            retry_after = error.headers.get("Retry-After") if error.headers else None
            if retry_after and retry_after.isdigit():
                sleep_seconds = int(retry_after)
            elif error.code in {429, 503}:
                sleep_seconds = min(60, 2**attempt)
            else:
                sleep_seconds = 0.6 * attempt

            if attempt < REQUEST_RETRIES:
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"MediaWiki request failed after retries: {error}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < REQUEST_RETRIES:
                time.sleep(0.8 * attempt)
                continue
            raise RuntimeError(f"MediaWiki request failed after retries: {error}") from error

    raise RuntimeError(f"MediaWiki request failed: {last_error}")


# Load JSON cache dictionary from disk if present.
def load_cache(cache_path: Path) -> dict[str, str | None]:
    if not cache_path.exists():
        return {}
    with cache_path.open("r", encoding="utf-8") as cache_file:
        data = json.load(cache_file)
    if not isinstance(data, dict):
        return {}
    normalized: dict[str, str | None] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        if value is None or isinstance(value, str):
            normalized[key] = value
    return normalized


# Persist cache dictionary to disk in UTF-8 JSON format.
def save_cache(cache_path: Path, cache_data: dict[str, str | None]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as cache_file:
        json.dump(cache_data, cache_file, ensure_ascii=False, indent=2)


# Fetch short definitions from Polish Wiktionary for many terms in batched API calls.
def fetch_wiktionary_definitions(
    terms: list[str],
    cache_path: Path = WIKTIONARY_CACHE_PATH,
) -> dict[str, str | None]:
    cache = load_cache(cache_path)
    results = {term: cache.get(term) for term in terms}
    terms_to_fetch = [term for term in terms if term not in cache]
    total_batches = (len(terms_to_fetch) + BATCH_SIZE - 1) // BATCH_SIZE

    if total_batches == 0:
        print("[wiktionary] all terms loaded from cache")
        return results

    for batch_index, batch in enumerate(chunked(terms_to_fetch, BATCH_SIZE), start=1):
        payload = mediawiki_post(
            api_url=WIKTIONARY_API_URL,
            payload={
                "action": "query",
                "format": "json",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "redirects": "1",
                "titles": "|".join(batch),
            },
        )

        query = payload.get("query", {})
        normalized_map = {
            normalize_word(item.get("from", "")): normalize_word(item.get("to", ""))
            for item in query.get("normalized", []) or []
            if item.get("from") and item.get("to")
        }
        redirect_map = {
            normalize_word(item.get("from", "")): normalize_word(item.get("to", ""))
            for item in query.get("redirects", []) or []
            if item.get("from") and item.get("to")
        }

        definitions_by_title: dict[str, str] = {}
        for page in query.get("pages", {}).values():
            if "missing" in page:
                continue

            title = normalize_word(page.get("title", ""))
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            content = ((revisions[0].get("slots") or {}).get("main") or {}).get("*", "")
            definition = extract_wiktionary_definition(content)
            if definition:
                definitions_by_title[title] = definition

        for term in batch:
            resolved_title = resolve_requested_title(term, normalized_map, redirect_map)
            resolved_definition = definitions_by_title.get(resolved_title)
            results[term] = resolved_definition
            cache[term] = resolved_definition

        print(f"[wiktionary] batch {batch_index}/{total_batches}")
        if batch_index % 10 == 0 or batch_index == total_batches:
            save_cache(cache_path, cache)
        time.sleep(WIKTIONARY_REQUEST_SLEEP_SECONDS)

    return results


# Fetch short intro extracts from Polish Wikipedia for missing terms.
def fetch_wikipedia_summaries(
    terms: list[str],
    cache_path: Path = WIKIPEDIA_CACHE_PATH,
) -> dict[str, str | None]:
    cache = load_cache(cache_path)
    results = {term: cache.get(term) for term in terms}
    if not terms:
        return results

    terms_to_fetch = [term for term in terms if term not in cache]
    total_batches = (len(terms_to_fetch) + BATCH_SIZE - 1) // BATCH_SIZE

    if total_batches == 0:
        print("[wikipedia] all terms loaded from cache")
        return results

    for batch_index, batch in enumerate(chunked(terms_to_fetch, BATCH_SIZE), start=1):
        try:
            payload = mediawiki_post(
                api_url=WIKIPEDIA_API_URL,
                payload={
                    "action": "query",
                    "format": "json",
                    "prop": "extracts",
                    "exintro": "1",
                    "explaintext": "1",
                    "redirects": "1",
                    "titles": "|".join(batch),
                },
            )
        except RuntimeError as error:
            print(f"[wikipedia] batch {batch_index}/{total_batches} failed: {error}")
            for term in batch:
                results[term] = None
                cache[term] = None
            if batch_index % 10 == 0 or batch_index == total_batches:
                save_cache(cache_path, cache)
            time.sleep(WIKIPEDIA_REQUEST_SLEEP_SECONDS)
            continue

        query = payload.get("query", {})
        normalized_map = {
            normalize_word(item.get("from", "")): normalize_word(item.get("to", ""))
            for item in query.get("normalized", []) or []
            if item.get("from") and item.get("to")
        }
        redirect_map = {
            normalize_word(item.get("from", "")): normalize_word(item.get("to", ""))
            for item in query.get("redirects", []) or []
            if item.get("from") and item.get("to")
        }

        summaries_by_title: dict[str, str] = {}
        for page in query.get("pages", {}).values():
            if "missing" in page:
                continue

            title = normalize_word(page.get("title", ""))
            extract = (page.get("extract") or "").strip()
            if not extract:
                continue

            first_paragraph = extract.split("\n", maxsplit=1)[0]
            summary = cleanup_definition_text(first_paragraph)
            if summary:
                summaries_by_title[title] = summary

        for term in batch:
            resolved_title = resolve_requested_title(term, normalized_map, redirect_map)
            resolved_summary = summaries_by_title.get(resolved_title)
            results[term] = resolved_summary
            cache[term] = resolved_summary

        print(f"[wikipedia] batch {batch_index}/{total_batches}")
        if batch_index % 10 == 0 or batch_index == total_batches:
            save_cache(cache_path, cache)
        time.sleep(WIKIPEDIA_REQUEST_SLEEP_SECONDS)

    return results


# Open either a local file path or a remote URL as line-by-line text iterator.
def iterate_source_lines(source: str) -> Iterable[str]:
    if source.startswith("http://") or source.startswith("https://"):
        request = Request(source, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                yield raw_line.decode("utf-8", errors="ignore")
        return

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    with source_path.open("r", encoding="utf-8") as source_file:
        for line in source_file:
            yield line


# Map each 5-letter dictionary form to its base form using ODM inflection groups.
def build_lemma_map(words: list[str], odm_source: str) -> dict[str, str]:
    word_set = set(words)
    lemma_map = {word: word for word in words}
    line_count = 0
    matched_forms = 0

    for line in iterate_source_lines(odm_source):
        line_count += 1
        if line_count % 250_000 == 0:
            print(f"[odm] processed lines: {line_count}")

        raw = line.strip()
        if not raw:
            continue

        forms = [normalize_word(part) for part in raw.split(",") if part.strip()]
        if not forms:
            continue

        base_form = forms[0]
        for form in forms:
            if len(form) != WORD_LENGTH:
                continue
            if form not in word_set:
                continue
            if lemma_map.get(form) != base_form:
                matched_forms += 1
            lemma_map[form] = base_form

    print(f"[odm] total lines: {line_count}")
    print(f"[odm] mapped forms updated: {matched_forms}")
    return lemma_map


# Build final meaning text for each dictionary word from best available source.
def compose_meanings(
    words: list[str],
    lemma_map: dict[str, str],
    wiktionary_by_lemma: dict[str, str | None],
    wikipedia_by_lemma: dict[str, str | None],
) -> tuple[list[tuple[str, str]], MeaningStats]:
    updates: list[tuple[str, str]] = []
    stats = MeaningStats(total_words=len(words))

    for word in words:
        lemma = lemma_map.get(word, word)
        if lemma != word:
            stats.lemma_mapped_words += 1

        meaning = wiktionary_by_lemma.get(lemma)
        if meaning:
            stats.wiktionary_meanings += 1
        else:
            meaning = wikipedia_by_lemma.get(lemma)
            if meaning:
                stats.wikipedia_meanings += 1
            else:
                meaning = PLACEHOLDER_DESCRIPTION
                stats.placeholders += 1

        updates.append((meaning, word))

    return updates, stats


# Persist prepared meanings into the SQLite dictionary table in write batches.
def write_meanings_to_database(db_path: Path, updates: list[tuple[str, str]]) -> None:
    with get_connection(db_path) as connection:
        ensure_schema(connection)
        for batch in chunked(updates, DB_WRITE_BATCH_SIZE):
            connection.executemany("UPDATE word_entries SET meaning = ? WHERE word = ?", batch)
            connection.commit()


# Read all active 5-letter Wordle words from SQLite dictionary table.
def load_word_list(db_path: Path) -> list[str]:
    with get_connection(db_path) as connection:
        ensure_schema(connection)
        rows = connection.execute(
            "SELECT word FROM word_entries WHERE length(word) = ? ORDER BY word",
            (WORD_LENGTH,),
        ).fetchall()
    words = [normalize_word(row["word"]) for row in rows]
    if not words:
        raise ValueError("Dictionary table is empty for 5-letter words.")
    return words


# Parse CLI args and run full enrichment pipeline for all current Wordle entries.
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fill short meanings for Wordle dictionary words using Polish Wiktionary, "
            "with Polish Wikipedia as fallback for missing lemmas."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite dictionary path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--odm-source",
        type=str,
        default=DEFAULT_ODM_SOURCE,
        help="ODM source URL or local file path for form->lemma mapping.",
    )
    args = parser.parse_args()

    words = load_word_list(args.db)
    print(f"[start] words to enrich: {len(words)}")

    lemma_map = build_lemma_map(words, args.odm_source)
    unique_lemmas = sorted(set(lemma_map.values()))
    print(f"[lemma] unique lemmas: {len(unique_lemmas)}")

    wiktionary_by_lemma = fetch_wiktionary_definitions(unique_lemmas)
    lemmas_without_wiktionary = [lemma for lemma in unique_lemmas if not wiktionary_by_lemma.get(lemma)]
    print(f"[wiktionary] missing lemmas: {len(lemmas_without_wiktionary)}")

    wikipedia_by_lemma = fetch_wikipedia_summaries(lemmas_without_wiktionary)
    updates, stats = compose_meanings(
        words=words,
        lemma_map=lemma_map,
        wiktionary_by_lemma=wiktionary_by_lemma,
        wikipedia_by_lemma=wikipedia_by_lemma,
    )
    write_meanings_to_database(args.db, updates)

    print(f"[done] total words: {stats.total_words}")
    print(f"[done] lemma-mapped words: {stats.lemma_mapped_words}")
    print(f"[done] meanings from Wiktionary: {stats.wiktionary_meanings}")
    print(f"[done] meanings from Wikipedia: {stats.wikipedia_meanings}")
    print(f"[done] placeholders used: {stats.placeholders}")


if __name__ == "__main__":
    main()
