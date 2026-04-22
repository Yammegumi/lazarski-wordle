import app as wordle_app


def _new_slownikowo_game(client):
    response = client.post("/api/slownikowo/new-game", json={})
    assert response.status_code == 200
    return response.get_json()


def _build_test_app():
    app = wordle_app.create_app(
        words_override=["kotek", "rower", "żółty"],
        slownikowo_words_override=["biedny", "niespodziewane", "państwo", "przyjemność", "wschód"],
    )
    app.config["TESTING"] = True
    return app


def test_slownikowo_page_is_available():
    app = _build_test_app()

    with app.test_client() as client:
        response = client.get("/slownikowo")
        html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "S&#321;OWNIKOWO" in html
    assert "WPISZ SLOWO" in html
    assert 'id="settings-menu"' in html
    assert 'id="tutorial-trigger"' in html
    assert 'id="tutorial-modal"' in html


def test_slownikowo_new_game_returns_randomized_schema(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "randrange", lambda _: 2)
    app = _build_test_app()

    with app.test_client() as client:
        payload = _new_slownikowo_game(client)

    assert "game_id" in payload
    assert payload["max_attempts"] == 15
    assert payload["pool_size"] == 5


def test_slownikowo_direction_feedback_and_win(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "randrange", lambda _: 2)
    app = _build_test_app()

    with app.test_client() as client:
        game = _new_slownikowo_game(client)
        game_id = game["game_id"]

        up_response = client.post("/api/slownikowo/guess", json={"game_id": game_id, "guess": "biedny"})
        down_response = client.post("/api/slownikowo/guess", json={"game_id": game_id, "guess": "wschód"})
        win_response = client.post("/api/slownikowo/guess", json={"game_id": game_id, "guess": "państwo"})

    up_payload = up_response.get_json()
    down_payload = down_response.get_json()
    win_payload = win_response.get_json()

    assert up_response.status_code == 200
    assert up_payload["direction"] == "up"
    assert up_payload["game_status"] == "in_progress"
    assert up_payload["guess_index"] < win_payload["guess_index"]
    assert 0 <= up_payload["distance_ratio"] <= 1

    assert down_response.status_code == 200
    assert down_payload["direction"] == "down"
    assert down_payload["game_status"] == "in_progress"
    assert down_payload["guess_index"] > win_payload["guess_index"]
    assert 0 <= down_payload["distance_ratio"] <= 1

    assert win_response.status_code == 200
    assert win_payload["direction"] == "correct"
    assert win_payload["game_status"] == "won"
    assert win_payload["target_word"] == "państwo"
    assert win_payload["distance"] == 0
    assert win_payload["distance_ratio"] == 0


def test_slownikowo_rejects_word_outside_dictionary(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "randrange", lambda _: 2)
    app = _build_test_app()

    with app.test_client() as client:
        game = _new_slownikowo_game(client)
        response = client.post("/api/slownikowo/guess", json={"game_id": game["game_id"], "guess": "kosmos"})

    assert response.status_code == 400
    assert response.get_json()["message"] == "Slowo spoza slownika."


def test_slownikowo_loses_after_fifteen_attempts(monkeypatch):
    monkeypatch.setattr(wordle_app.random, "randrange", lambda _: 2)
    app = _build_test_app()

    with app.test_client() as client:
        game = _new_slownikowo_game(client)
        game_id = game["game_id"]

        final_response = None
        for _ in range(15):
            final_response = client.post(
                "/api/slownikowo/guess",
                json={"game_id": game_id, "guess": "biedny"},
            )

    assert final_response is not None
    final_payload = final_response.get_json()
    assert final_response.status_code == 200
    assert final_payload["attempt"] == 15
    assert final_payload["remaining_attempts"] == 0
    assert final_payload["game_status"] == "lost"
    assert final_payload["target_word"] == "państwo"
