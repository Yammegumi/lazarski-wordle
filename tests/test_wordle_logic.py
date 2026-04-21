from wordle_logic import score_guess, strip_polish_diacritics, validate_guess, validate_guess_easy


def test_score_guess_all_correct() -> None:
    assert score_guess("żółty", "żółty") == ["correct", "correct", "correct", "correct", "correct"]


def test_score_guess_repeated_letters() -> None:
    assert score_guess("alala", "lalka") == ["present", "present", "absent", "present", "correct"]


def test_score_guess_no_matches() -> None:
    assert score_guess("kotek", "żółty") == ["absent", "absent", "present", "absent", "absent"]


def test_strip_polish_diacritics() -> None:
    assert strip_polish_diacritics("Żółty") == "zolty"


def test_validate_guess_bad_length() -> None:
    dictionary = {"kotek"}
    assert validate_guess("kot", dictionary) == "Słowo musi mieć 5 liter."


def test_validate_guess_bad_characters() -> None:
    dictionary = {"kotek"}
    assert validate_guess("kot3k", dictionary) == "Dozwolone są wyłącznie litery alfabetu polskiego."


def test_validate_guess_not_in_dictionary() -> None:
    dictionary = {"kotek"}
    assert validate_guess("rower", dictionary) == "Słowo spoza słownika."


def test_validate_guess_easy_bad_characters() -> None:
    dictionary = {"zolty"}
    assert validate_guess_easy("żolty", dictionary) == "Dozwolone są wyłącznie litery bez polskich znaków."
