from __future__ import annotations

from collections import Counter
from pathlib import Path

WORD_LENGTH = 5
MAX_ATTEMPTS = 6
ALLOWED_LETTERS = "a\u0105bc\u0107de\u0119fghijkl\u0142mn\u0144o\u00f3pqrs\u015btuvwxyz\u017a\u017c"
ALLOWED_LETTER_SET = set(ALLOWED_LETTERS)
ALLOWED_LETTERS_EASY = "abcdefghijklmnopqrstuvwxyz"
ALLOWED_LETTER_SET_EASY = set(ALLOWED_LETTERS_EASY)

POLISH_TO_BASIC_TRANSLATION = str.maketrans(
    {
        "\u0105": "a",
        "\u0107": "c",
        "\u0119": "e",
        "\u0142": "l",
        "\u0144": "n",
        "\u00f3": "o",
        "\u015b": "s",
        "\u017a": "z",
        "\u017c": "z",
    }
)


# Normalize input by trimming surrounding whitespace and forcing lowercase.
def normalize_word(word: str) -> str:
    return word.strip().lower()


# Validate standard mode letter shape against Polish alphabet and fixed length.
def is_valid_word_shape(word: str) -> bool:
    return len(word) == WORD_LENGTH and all(letter in ALLOWED_LETTER_SET for letter in word)


# Replace Polish diacritics so words can be reused in easy mode.
def strip_polish_diacritics(word: str) -> str:
    return normalize_word(word).translate(POLISH_TO_BASIC_TRANSLATION)


# Validate easy mode letter shape against plain Latin alphabet and fixed length.
def is_valid_easy_word_shape(word: str) -> bool:
    return len(word) == WORD_LENGTH and all(letter in ALLOWED_LETTER_SET_EASY for letter in word)


# Load, validate, and deduplicate dictionary entries from a UTF-8 text file.
def load_words(path: Path) -> list[str]:
    if not path.exists():
        raise ValueError(f"Nie znaleziono s\u0142ownika: {path}")

    words: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            word = normalize_word(line)
            if not word:
                continue
            if not is_valid_word_shape(word):
                raise ValueError(
                    f"Niepoprawne s\u0142owo w s\u0142owniku (linia {line_number}): {word!r}. "
                    f"Oczekiwano 5 liter i wy\u0142\u0105cznie znak\u00f3w z alfabetu polskiego."
                )
            words.append(word)

    words = list(dict.fromkeys(words))
    if not words:
        raise ValueError("S\u0142ownik jest pusty.")
    return words


# Run shared guess validation rules for both game modes.
def _validate_guess_with_alphabet(
    guess: str,
    dictionary: set[str],
    allowed_letters: set[str],
    invalid_letters_message: str,
) -> str | None:
    if len(guess) != WORD_LENGTH:
        return "S\u0142owo musi mie\u0107 5 liter."
    if not all(letter in allowed_letters for letter in guess):
        return invalid_letters_message
    if guess not in dictionary:
        return "S\u0142owo spoza s\u0142ownika."
    return None


# Validate a guess in normal mode against Polish letters and the active dictionary.
def validate_guess(guess: str, dictionary: set[str]) -> str | None:
    return _validate_guess_with_alphabet(
        guess=guess,
        dictionary=dictionary,
        allowed_letters=ALLOWED_LETTER_SET,
        invalid_letters_message="Dozwolone s\u0105 wy\u0142\u0105cznie litery alfabetu polskiego.",
    )


# Validate a guess in easy mode against ASCII letters and the active dictionary.
def validate_guess_easy(guess: str, dictionary: set[str]) -> str | None:
    return _validate_guess_with_alphabet(
        guess=guess,
        dictionary=dictionary,
        allowed_letters=ALLOWED_LETTER_SET_EASY,
        invalid_letters_message="Dozwolone s\u0105 wy\u0142\u0105cznie litery bez polskich znak\u00f3w.",
    )


# Score each guessed letter as correct, present, or absent using Wordle rules.
def score_guess(guess: str, target: str) -> list[str]:
    result = ["absent"] * WORD_LENGTH
    remaining_target_letters = Counter()

    for index, (guess_letter, target_letter) in enumerate(zip(guess, target)):
        if guess_letter == target_letter:
            result[index] = "correct"
        else:
            remaining_target_letters[target_letter] += 1

    for index, guess_letter in enumerate(guess):
        if result[index] == "correct":
            continue
        if remaining_target_letters[guess_letter] > 0:
            result[index] = "present"
            remaining_target_letters[guess_letter] -= 1

    return result
