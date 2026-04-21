import app as wordle_app


def _new_game(client, mode: str | None = None):
    payload = {}
    if mode is not None:
        payload["mode"] = mode
    response = client.post("/api/new-game", json=payload)
    assert response.status_code == 200
    return response.get_json()


def test_new_game_schema(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: seq[0])
    app = wordle_app.create_app(words_override=["kotek", "rower", "żółty"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        payload = _new_game(client)
        assert "game_id" in payload
        assert payload["max_rows"] == 6
        assert payload["word_length"] == 5
        assert payload["mode"] == "normal"


def test_new_game_rejects_invalid_mode(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: seq[0])
    app = wordle_app.create_app(words_override=["kotek", "rower", "żółty"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/new-game", json={"mode": "ultra"})
        assert response.status_code == 400
        assert response.get_json()["message"] == "Niepoprawny tryb gry."


def test_guess_valid_word(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client)
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "rower"})
        data = response.get_json()

        assert response.status_code == 200
        assert data["attempt"] == 1
        assert data["game_status"] == "in_progress"
        assert data["mode"] == "normal"
        assert len(data["row_result"]) == 5


def test_guess_wrong_length(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client)
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "kot"})

        assert response.status_code == 400
        assert response.get_json()["message"] == "Słowo musi mieć 5 liter."


def test_guess_invalid_characters(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client)
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "ko1ek"})

        assert response.status_code == 400
        assert response.get_json()["message"] == "Dozwolone są wyłącznie litery alfabetu polskiego."


def test_guess_outside_dictionary(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client)
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "żółty"})

        assert response.status_code == 400
        assert response.get_json()["message"] == "Słowo spoza słownika."


def test_game_lost_after_six_attempts(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client)

        last_response = None
        for _ in range(6):
            last_response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "rower"})

        assert last_response is not None
        data = last_response.get_json()
        assert last_response.status_code == 200
        assert data["attempt"] == 6
        assert data["game_status"] == "lost"
        assert data["target_word"] == "kotek"


def test_game_won(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "żółty")
    app = wordle_app.create_app(words_override=["żółty", "kotek"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client)
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "żółty"})
        data = response.get_json()

        assert response.status_code == 200
        assert data["attempt"] == 1
        assert data["game_status"] == "won"


def test_easy_mode_guess_won_without_diacritics(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "zolty")
    app = wordle_app.create_app(words_override=["żółty", "kotek"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client, mode="easy")
        assert game["mode"] == "easy"
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "zolty"})
        data = response.get_json()

        assert response.status_code == 200
        assert data["game_status"] == "won"
        assert data["mode"] == "easy"


def test_easy_mode_rejects_polish_letters_in_guess(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "zolty")
    app = wordle_app.create_app(words_override=["żółty", "kotek"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        game = _new_game(client, mode="easy")
        response = client.post("/api/guess", json={"game_id": game["game_id"], "guess": "żolty"})

        assert response.status_code == 400
        assert response.get_json()["message"] == "Dozwolone są wyłącznie litery bez polskich znaków."


def test_unknown_game_id(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/guess", json={"game_id": "nie-ma-takiej-gry", "guess": "rower"})
        assert response.status_code == 404
        assert response.get_json()["message"] == "Nie znaleziono gry."


def test_words_page_lists_available_words(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower", "żółty"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.get("/words")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "SŁOWA" in html
        assert "/words/kotek" in html
        assert "/words/rower" in html


def test_word_detail_page_exists(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower", "żółty"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.get("/words/żółty")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "ŻÓŁTY" in html
        assert "Zdjęcie (przyszły feature)" in html


def test_word_detail_404_for_unknown_word(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower", "żółty"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.get("/words/abcde")
        assert response.status_code == 404


def test_index_contains_settings_menu_and_about_modal(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "choice", lambda seq: "kotek")
    app = wordle_app.create_app(words_override=["kotek", "rower", "żółty"])
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.get("/")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'id="menu-new-game"' in html
        assert 'id="menu-mode-toggle"' in html
        assert "/slownikowo" in html
        assert "ABOUT ME" in html
        assert "WORDLE</h1>" in html
        assert 'id="about-modal"' in html
        assert "images/logo_pl.svg" in html
        assert "Wojciecha Draba" in html
        assert "53758" in html
        assert "53906" in html
        assert 'id="new-game-btn"' not in html
