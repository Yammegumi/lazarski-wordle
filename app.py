from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from slownikowo_logic import (
    SLOWNIKOWO_MAX_ATTEMPTS,
    compare_word_positions,
    load_slownikowo_words,
    normalize_slownikowo_word,
    prepare_slownikowo_words,
    validate_slownikowo_guess,
)
from word_database import DEFAULT_DB_PATH, ensure_schema, get_connection, load_words_from_database
from wordle_logic import (
    MAX_ATTEMPTS,
    WORD_LENGTH,
    is_valid_easy_word_shape,
    is_valid_word_shape,
    load_words,
    normalize_word,
    score_guess,
    strip_polish_diacritics,
    validate_guess,
    validate_guess_easy,
)


@dataclass
class GameState:
    target_word: str
    mode: str = "normal"
    guesses: list[str] = field(default_factory=list)
    status: str = "in_progress"


@dataclass
class SlownikowoGameState:
    target_word: str
    target_index: int
    guesses: list[str] = field(default_factory=list)
    status: str = "in_progress"


# Build and configure the Flask application together with game and dictionary state.
def create_app(
    words_path: str | Path = "data/words.txt",
    words_override: list[str] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    slownikowo_words_override: list[str] | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    resolved_db_path = Path(db_path)
    words_from_database = words_override is None and resolved_db_path.exists()

    if words_override is None:
        if words_from_database:
            words = load_words_from_database(resolved_db_path)
        else:
            words = load_words(Path(words_path))
    else:
        words = [normalize_word(word) for word in words_override if word.strip()]
        if not words:
            raise ValueError("Slownik nie moze byc pusty.")
        for word in words:
            if not is_valid_word_shape(word):
                raise ValueError(f"Niepoprawne słowo testowe: {word}")
        words = list(dict.fromkeys(words))

    word_set = set(words)
    easy_words: list[str] = []
    seen_easy_words: set[str] = set()
    for word in words:
        easy_word = strip_polish_diacritics(word)
        if not is_valid_easy_word_shape(easy_word):
            continue
        if easy_word in seen_easy_words:
            continue
        seen_easy_words.add(easy_word)
        easy_words.append(easy_word)

    if not easy_words:
        raise ValueError("Brak słów dla trybu easy.")

    easy_word_set = set(easy_words)
    games: dict[str, GameState] = {}

    if words_from_database:
        with get_connection(resolved_db_path) as connection:
            ensure_schema(connection)

    if slownikowo_words_override is None:
        slownikowo_words = load_slownikowo_words()
    else:
        slownikowo_words = prepare_slownikowo_words(slownikowo_words_override)
    slownikowo_word_set = set(slownikowo_words)
    slownikowo_word_to_index = {word: index for index, word in enumerate(slownikowo_words)}
    slownikowo_games: dict[str, SlownikowoGameState] = {}

    # Return a minimal dictionary entry shape when database metadata is unavailable.
    def _fallback_entry(word: str) -> dict[str, Any]:
        return {
            "word": word,
            "meaning": None,
            "image_url": None,
            "puzzle_number": None,
        }

    # Load searchable word entries and total dictionary size for the words listing page.
    def _fetch_words(query: str) -> tuple[list[dict[str, Any]], int]:
        query = normalize_word(query)
        if words_from_database:
            with get_connection(resolved_db_path) as connection:
                total_available = connection.execute(
                    "SELECT COUNT(*) FROM word_entries"
                ).fetchone()[0]
                if query:
                    pattern = f"%{query}%"
                    rows = connection.execute(
                        """
                        SELECT word, meaning, image_url, puzzle_number
                        FROM word_entries
                        WHERE word LIKE ? OR COALESCE(meaning, '') LIKE ?
                        ORDER BY word
                        """,
                        (pattern, pattern),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT word, meaning, image_url, puzzle_number
                        FROM word_entries
                        ORDER BY word
                        """
                    ).fetchall()
            return [dict(row) for row in rows], total_available

        entries = [_fallback_entry(word) for word in sorted(words)]
        if not query:
            return entries, len(entries)
        filtered = [
            entry
            for entry in entries
            if query in entry["word"] or (entry["meaning"] and query in entry["meaning"].lower())
        ]
        return filtered, len(entries)

    # Resolve one dictionary entry either from the database or from the in-memory fallback list.
    def _fetch_word(word: str) -> dict[str, Any] | None:
        normalized = normalize_word(word)
        if words_from_database:
            with get_connection(resolved_db_path) as connection:
                row = connection.execute(
                    """
                    SELECT word, meaning, image_url, puzzle_number
                    FROM word_entries
                    WHERE word = ?
                    """,
                    (normalized,),
                ).fetchone()
            if row:
                return dict(row)

        if normalized in word_set:
            return _fallback_entry(normalized)
        return None

    # Extract required game request payload fields or return an API error response tuple.
    def _extract_game_payload(payload: dict[str, Any]) -> tuple[str, str, tuple[Any, int] | None]:
        game_id = payload.get("game_id")
        raw_guess = payload.get("guess")

        if not isinstance(game_id, str) or not game_id:
            return "", "", (jsonify({"message": "Brak poprawnego game_id."}), 400)
        if not isinstance(raw_guess, str):
            return "", "", (jsonify({"message": "Brak poprawnego slowa."}), 400)
        return game_id, raw_guess, None

    # Return a standardized API response for an already finished Wordle game.
    def _build_finished_wordle_response(game: GameState) -> tuple[Any, int]:
        target_entry = _fetch_word(game.target_word)
        target_meaning = target_entry["meaning"] if target_entry else None
        finished: dict[str, Any] = {
            "message": "Gra jest juz zakonczona.",
            "game_status": game.status,
            "mode": game.mode,
            "target_word": game.target_word,
            "target_meaning": target_meaning,
        }
        return jsonify(finished), 409

    # Return a standardized API response for an already finished Slownikowo game.
    def _build_finished_slownikowo_response(game: SlownikowoGameState) -> tuple[Any, int]:
        finished: dict[str, Any] = {
            "message": "Gra jest juz zakonczona.",
            "game_status": game.status,
        }
        if game.status in {"won", "lost"}:
            finished["target_word"] = game.target_word
        return jsonify(finished), 409

    # Render the main game page with board dimensions from backend constants.
    @app.get("/")
    def index() -> str:
        return render_template("index.html", max_rows=MAX_ATTEMPTS, word_length=WORD_LENGTH)

    # Render the searchable dictionary page with either all or filtered entries.
    @app.get("/words")
    def words_index() -> str:
        query = request.args.get("q", "")
        entries, total_available = _fetch_words(query)
        return render_template(
            "words.html",
            entries=entries,
            query=query,
            total_available=total_available,
            filtered_count=len(entries),
        )

    # Render details for a single normalized dictionary word or return 404 when missing.
    @app.get("/words/<word>")
    def word_detail(word: str) -> str:
        normalized = normalize_word(word)
        if not is_valid_word_shape(normalized):
            abort(404)
        entry = _fetch_word(normalized)
        if entry is None:
            abort(404)
        return render_template("word_detail.html", entry=entry)

    # Render the Slownikowo page where players guess one random dictionary word.
    @app.get("/slownikowo")
    def slownikowo() -> str:
        return render_template("slownikowo.html", max_attempts=SLOWNIKOWO_MAX_ATTEMPTS)

    # Start a new game session in requested mode and return public game metadata.
    @app.post("/api/new-game")
    def new_game() -> tuple[Any, int] | Any:
        payload = request.get_json(silent=True) or {}
        raw_mode = payload.get("mode", "normal")
        if not isinstance(raw_mode, str):
            return jsonify({"message": "Niepoprawny tryb gry."}), 400
        game_mode = normalize_word(raw_mode)
        if game_mode not in {"normal", "easy"}:
            return jsonify({"message": "Niepoprawny tryb gry."}), 400

        target_pool = easy_words if game_mode == "easy" else words
        game_id = str(uuid.uuid4())
        games[game_id] = GameState(target_word=random.choice(target_pool), mode=game_mode)
        return jsonify(
            {
                "game_id": game_id,
                "max_rows": MAX_ATTEMPTS,
                "word_length": WORD_LENGTH,
                "mode": game_mode,
            }
        )

    # Validate and score a guess, then update game state and return current result.
    @app.post("/api/guess")
    def guess() -> tuple[Any, int] | Any:
        payload = request.get_json(silent=True) or {}
        game_id, raw_guess, payload_error = _extract_game_payload(payload)
        if payload_error is not None:
            return payload_error

        game = games.get(game_id)
        if game is None:
            return jsonify({"message": "Nie znaleziono gry."}), 404

        if game.status != "in_progress":
            return _build_finished_wordle_response(game)

        guess_word = normalize_word(raw_guess)
        if game.mode == "easy":
            validation_error = validate_guess_easy(guess_word, easy_word_set)
        else:
            validation_error = validate_guess(guess_word, word_set)
        if validation_error:
            return jsonify({"message": validation_error}), 400

        row_result = score_guess(guess_word, game.target_word)
        game.guesses.append(guess_word)

        if guess_word == game.target_word:
            game.status = "won"
            message = "Brawo! Odgadles slowo."
        elif len(game.guesses) >= MAX_ATTEMPTS:
            game.status = "lost"
            message = f"Koniec gry. Szukane slowo to: {game.target_word.upper()}."
        else:
            message = "Proba zapisana."

        response: dict[str, Any] = {
            "row_result": row_result,
            "attempt": len(game.guesses),
            "game_status": game.status,
            "message": message,
            "mode": game.mode,
        }
        if game.status in {"won", "lost"}:
            target_entry = _fetch_word(game.target_word)
            response["target_word"] = game.target_word
            response["target_meaning"] = target_entry["meaning"] if target_entry else None

        return jsonify(response)

    # Start a Slownikowo session with a freshly randomized dictionary target word.
    @app.post("/api/slownikowo/new-game")
    def new_slownikowo_game() -> Any:
        target_index = random.randrange(len(slownikowo_words))
        target_word = slownikowo_words[target_index]
        game_id = str(uuid.uuid4())
        slownikowo_games[game_id] = SlownikowoGameState(
            target_word=target_word,
            target_index=target_index,
        )
        return jsonify(
            {
                "game_id": game_id,
                "max_attempts": SLOWNIKOWO_MAX_ATTEMPTS,
                "pool_size": len(slownikowo_words),
            }
        )

    # Validate Slownikowo guess and return direction relative to current random target.
    @app.post("/api/slownikowo/guess")
    def slownikowo_guess() -> tuple[Any, int] | Any:
        payload = request.get_json(silent=True) or {}
        game_id, raw_guess, payload_error = _extract_game_payload(payload)
        if payload_error is not None:
            return payload_error

        game = slownikowo_games.get(game_id)
        if game is None:
            return jsonify({"message": "Nie znaleziono gry."}), 404

        if game.status != "in_progress":
            return _build_finished_slownikowo_response(game)

        guess_word = normalize_slownikowo_word(raw_guess)
        validation_error = validate_slownikowo_guess(guess_word, slownikowo_word_set)
        if validation_error:
            return jsonify({"message": validation_error}), 400

        guess_index = slownikowo_word_to_index[guess_word]
        direction = compare_word_positions(guess_index, game.target_index)
        game.guesses.append(guess_word)
        max_distance = max(1, len(slownikowo_words) - 1)
        distance = abs(guess_index - game.target_index)
        distance_ratio = distance / max_distance

        if direction == "correct":
            game.status = "won"
            message = "Brawo! Odgadles haslo."
        elif len(game.guesses) >= SLOWNIKOWO_MAX_ATTEMPTS:
            game.status = "lost"
            message = f"Koniec gry. Szukane haslo to: {game.target_word.upper()}."
        elif direction == "up":
            message = "To slowo jest wczesniej w slowniku niz haslo."
        else:
            message = "To slowo jest pozniej w slowniku niz haslo."

        response: dict[str, Any] = {
            "guess": guess_word,
            "guess_index": guess_index,
            "distance": distance,
            "distance_ratio": distance_ratio,
            "direction": direction,
            "attempt": len(game.guesses),
            "remaining_attempts": SLOWNIKOWO_MAX_ATTEMPTS - len(game.guesses),
            "game_status": game.status,
            "message": message,
        }
        if game.status in {"won", "lost"}:
            response["target_word"] = game.target_word

        return jsonify(response)

    return app


app = create_app()
