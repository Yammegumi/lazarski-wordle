# Lazarski Wordle (Wordle PL)

A Flask web application that implements two Polish word games: classic Wordle and a random dictionary-order mode called Slownikowo.

## Features

- Classic 5x6 Wordle gameplay (5 letters, up to 6 attempts).
- Two Wordle modes:
  - `normal` (full Polish alphabet with diacritics),
  - `easy` (letters without Polish diacritics).
- A separate `Słownikowo` mode (`/slownikowo`) with:
  - one random target word on each entry/new game,
  - up to 15 attempts,
  - directional hints (`up`/`down`) based on dictionary order.
- On-screen keyboard and physical keyboard support.
- Dictionary list page (`/words`) and single-word details page (`/words/<word>`).
- SQLite-backed word source with fallback to `words.txt`.
- Import script for syncing words from the Wordle archive.

## Tech Stack

- Python 3.13
- Flask
- SQLite
- Vanilla JavaScript, HTML, CSS
- Pytest

## Project Structure

```text
lazarski-wordle/
|-- app.py                      # Flask app factory and HTTP/API endpoints
|-- main.py                     # Server entry point
|-- slownikowo_logic.py         # Slownikowo dictionary filtering and random-word logic
|-- wordle_logic.py             # Word validation and guess scoring
|-- word_database.py            # SQLite schema, migrations, and DB access
|-- words.txt                   # Text dictionary fallback
|-- data/
|   |-- slownikowo_words.txt    # Cached Slownikowo dictionary word list
|   `-- wordle_pl.sqlite3       # Local dictionary database
|-- scripts/
|   `-- sync_wordle_archive.py  # Archive importer/synchronizer
|-- static/
|   |-- app.js                  # Client-side game logic
|   |-- slownikowo.js           # Slownikowo client-side logic
|   |-- style.css               # Application styles
|   `-- images/logo_pl.svg      # About modal logo
|-- templates/
|   |-- index.html              # Game view
|   |-- slownikowo.html         # Slownikowo view
|   |-- words.html              # Dictionary list view
|   `-- word_detail.html        # Single word details view
`-- tests/
    |-- test_api.py
    |-- test_database_schema.py
    |-- test_slownikowo.py
    `-- test_wordle_logic.py
```

## Local Run

1. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
2. Start the app:
   ```bash
   python main.py
   ```
3. Open:
   - `http://127.0.0.1:5000/`

## Tests

Run the full test suite:

```bash
python -m pytest -q
```

## API (Short)

- `POST /api/new-game`
  - body: `{"mode": "normal"}` or `{"mode": "easy"}`
  - response: `game_id`, `max_rows`, `word_length`, `mode`

- `POST /api/guess`
  - body: `{"game_id": "...", "guess": "kotek"}`
  - response: row score, attempt number, game status, and message

- `POST /api/slownikowo/new-game`
  - body: `{}`
  - response: `game_id`, `max_attempts`, `pool_size`

- `POST /api/slownikowo/guess`
  - body: `{"game_id": "...", "guess": "przyjemnosc"}`
  - response: direction (`up`, `down`, `correct`), dictionary index metadata, attempts metadata, and game status

## Dictionary Sync

Sync archive records into SQLite:

```bash
python scripts/sync_wordle_archive.py --db data/wordle_pl.sqlite3
```

Optionally fetch thumbnail URLs:

```bash
python scripts/sync_wordle_archive.py --fetch-images
```

## Maintenance Notes

- Core word rules and scoring live in `wordle_logic.py`.
- Slownikowo uses words derived from:
  - `https://raw.githubusercontent.com/ostr00000/jezyk-polski-slowniki/refs/heads/master/class_a.txt`
- Slownikowo automatically slims this source with a frequency-based filter and keeps shorter everyday words.
- Database operations and migrations live in `word_database.py`.
- `app.py` uses an app factory (`create_app`) to simplify testing.
