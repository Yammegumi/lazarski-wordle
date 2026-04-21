from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

SLOWNIKOWO_SOURCE_URL = (
    "https://raw.githubusercontent.com/ostr00000/jezyk-polski-slowniki/refs/heads/master/class_a.txt"
)
SLOWNIKOWO_FREQUENCY_URL = (
    "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/pl/pl_50k.txt"
)
DEFAULT_SLOWNIKOWO_WORDS_PATH = Path("data/slownikowo_words.txt")
SLOWNIKOWO_MAX_ATTEMPTS = 15
SLOWNIKOWO_USER_AGENT = "Mozilla/5.0 (compatible; LazarskiWordle/1.0)"
SLOWNIKOWO_FREQUENCY_TOP_N = 30_000
SLOWNIKOWO_SHORT_WORD_MAX_LENGTH = 6
SLOWNIKOWO_MIN_WORD_LENGTH = 3
SLOWNIKOWO_MAX_WORD_LENGTH = 14

POLISH_SORT_ORDER = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
POLISH_SORT_INDEX = {letter: index for index, letter in enumerate(POLISH_SORT_ORDER)}


# Normalize a candidate word by trimming whitespace and forcing lowercase.
def normalize_slownikowo_word(word: str) -> str:
    return word.strip().lower()


# Extract and normalize the source lemma from one raw dictionary line.
def parse_source_line(line: str) -> str | None:
    lemma = normalize_slownikowo_word(line.split(";", maxsplit=1)[0])
    if not lemma:
        return None
    if not lemma.isalpha():
        return None
    return lemma


# Build a stable Polish-aware sort key so UI and API use deterministic ordering.
def polish_sort_key(word: str) -> tuple[tuple[int, ...], int]:
    weights = tuple(POLISH_SORT_INDEX.get(letter, 10_000 + ord(letter)) for letter in word)
    return weights, len(word)


# Normalize, deduplicate, and sort words for Slownikowo runtime usage.
def prepare_slownikowo_words(candidates: list[str]) -> list[str]:
    normalized: list[str] = []
    for candidate in candidates:
        word = normalize_slownikowo_word(candidate)
        if not word:
            continue
        if not word.isalpha():
            continue
        normalized.append(word)

    unique_words = list(dict.fromkeys(normalized))
    if not unique_words:
        raise ValueError("Slownikowo dictionary is empty.")
    return sorted(unique_words, key=polish_sort_key)


# Keep mostly common words using frequency data plus short everyday-like words.
def filter_common_slownikowo_words(
    words: list[str],
    frequency_words: set[str],
) -> list[str]:
    filtered: list[str] = []
    for word in words:
        length = len(word)
        if length < SLOWNIKOWO_MIN_WORD_LENGTH or length > SLOWNIKOWO_MAX_WORD_LENGTH:
            continue

        if frequency_words:
            if word in frequency_words or length <= SLOWNIKOWO_SHORT_WORD_MAX_LENGTH:
                filtered.append(word)
            continue

        if length <= SLOWNIKOWO_SHORT_WORD_MAX_LENGTH:
            filtered.append(word)

    if not filtered:
        raise ValueError("Slownikowo common-word filter removed all entries.")
    return filtered


# Download a ranked set of frequent Polish words used to slim the source dictionary.
def download_frequency_words(
    source_url: str = SLOWNIKOWO_FREQUENCY_URL,
    top_n: int = SLOWNIKOWO_FREQUENCY_TOP_N,
) -> set[str]:
    request = Request(source_url, headers={"User-Agent": SLOWNIKOWO_USER_AGENT})
    with urlopen(request, timeout=30) as response:
        raw_text = response.read().decode("utf-8")

    words: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        token = normalize_slownikowo_word(line.split(maxsplit=1)[0])
        if not token:
            continue
        words.append(token)

    return set(words[:top_n])


# Download source lemmas, filter uncommon entries, and return prepared dictionary words.
def download_slownikowo_words(
    source_url: str = SLOWNIKOWO_SOURCE_URL,
    frequency_url: str = SLOWNIKOWO_FREQUENCY_URL,
) -> list[str]:
    request = Request(source_url, headers={"User-Agent": SLOWNIKOWO_USER_AGENT})
    with urlopen(request, timeout=30) as response:
        raw_text = response.read().decode("utf-8")

    lemmas: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = parse_source_line(line)
        if parsed is not None:
            lemmas.append(parsed)

    prepared = prepare_slownikowo_words(lemmas)
    try:
        frequency_words = download_frequency_words(source_url=frequency_url)
    except Exception:
        frequency_words = set()

    filtered = filter_common_slownikowo_words(prepared, frequency_words)
    return prepare_slownikowo_words(filtered)


# Persist prepared words to local cache for fast startup and stable deploys.
def save_cached_slownikowo_words(
    words: list[str], path: str | Path = DEFAULT_SLOWNIKOWO_WORDS_PATH
) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(words))
        file.write("\n")


# Load prepared words from local cache file and normalize them again for safety.
def load_cached_slownikowo_words(path: str | Path = DEFAULT_SLOWNIKOWO_WORDS_PATH) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise ValueError(f"Nie znaleziono pliku Slownikowo: {file_path}")

    words: list[str] = []
    with file_path.open("r", encoding="utf-8") as file:
        for line in file:
            word = normalize_slownikowo_word(line)
            if not word:
                continue
            words.append(word)
    return prepare_slownikowo_words(words)


# Load Slownikowo words from cache or regenerate them from remote sources when missing.
def load_slownikowo_words(
    path: str | Path = DEFAULT_SLOWNIKOWO_WORDS_PATH,
    source_url: str = SLOWNIKOWO_SOURCE_URL,
    frequency_url: str = SLOWNIKOWO_FREQUENCY_URL,
) -> list[str]:
    file_path = Path(path)
    if file_path.exists():
        return load_cached_slownikowo_words(file_path)

    downloaded = download_slownikowo_words(source_url=source_url, frequency_url=frequency_url)
    save_cached_slownikowo_words(downloaded, path=file_path)
    return downloaded


# Validate one Slownikowo guess against format and dictionary membership rules.
def validate_slownikowo_guess(guess: str, dictionary: set[str]) -> str | None:
    if not guess:
        return "Wpisz slowo."
    if not guess.isalpha():
        return "Dozwolone sa wylacznie litery."
    if guess not in dictionary:
        return "Slowo spoza slownika."
    return None


# Compare dictionary positions and return direction used by the frontend.
def compare_word_positions(guess_index: int, target_index: int) -> str:
    if guess_index < target_index:
        return "up"
    if guess_index > target_index:
        return "down"
    return "correct"
