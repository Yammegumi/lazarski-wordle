# Lazarski Wordle (Wordle PL)

Aplikacja webowa w Flasku, ktora implementuje polska wersje gry Wordle wraz z trybem latwym bez polskich znakow.

## Funkcje

- Rozgrywka Wordle 5x6 (5 liter, maksymalnie 6 prob).
- Dwa tryby gry:
  - `normal` (pelny polski alfabet z diakrytykami),
  - `easy` (litery bez polskich znakow).
- Ekranowa klawiatura + obsluga klawiatury fizycznej.
- Widok slownika (`/words`) i widok szczegolow slowa (`/words/<word>`).
- Integracja z baza SQLite oraz fallback do pliku `words.txt`.
- Skrypt do synchronizacji slownika z archiwum Wordle.

## Stos technologiczny

- Python 3.13
- Flask
- SQLite
- Vanilla JavaScript + HTML + CSS
- Pytest

## Struktura projektu

```text
lazarski-wordle/
├─ app.py                      # Flask app factory i endpointy HTTP/API
├─ main.py                     # Punkt startowy do uruchomienia serwera
├─ wordle_logic.py             # Walidacja slow i scoring zgadniec
├─ word_database.py            # Schemat, migracje i dostep do SQLite
├─ words.txt                   # Fallbackowy slownik tekstowy
├─ data/
│  └─ wordle_pl.sqlite3        # Lokalna baza slow
├─ scripts/
│  └─ sync_wordle_archive.py   # Import/synchronizacja danych z archiwum
├─ static/
│  ├─ app.js                   # Logika klienta i interakcje UI
│  ├─ style.css                # Style aplikacji
│  └─ images/logo_pl.svg       # Logo do modala "About"
├─ templates/
│  ├─ index.html               # Widok gry
│  ├─ words.html               # Lista slow
│  └─ word_detail.html         # Szczegoly pojedynczego slowa
└─ tests/
   ├─ test_api.py
   ├─ test_database_schema.py
   └─ test_wordle_logic.py
```

## Uruchomienie lokalne

1. Zainstaluj zaleznosci:
   ```bash
   python -m pip install -r requirements.txt
   ```
2. Uruchom aplikacje:
   ```bash
   python main.py
   ```
3. Otworz przegladarke:
   - `http://127.0.0.1:5000/`

## Testy

Uruchomienie calego zestawu:

```bash
python -m pytest -q
```

## API (skrot)

- `POST /api/new-game`
  - body: `{"mode": "normal"}` lub `{"mode": "easy"}`
  - response: `game_id`, `max_rows`, `word_length`, `mode`

- `POST /api/guess`
  - body: `{"game_id": "...", "guess": "kotek"}`
  - response: wynik wiersza, numer proby, status gry i komunikat

## Synchronizacja slownika

Skrypt pobiera wpisy z archiwum i aktualizuje baze SQLite:

```bash
python scripts/sync_wordle_archive.py --db data/wordle_pl.sqlite3
```

Opcjonalnie pobieranie miniatur:

```bash
python scripts/sync_wordle_archive.py --fetch-images
```

## Uwagi utrzymaniowe

- Logika slow i scoring jest wydzielona do `wordle_logic.py`.
- Operacje na bazie i migracje sa w `word_database.py`.
- `app.py` korzysta z fabryki aplikacji (`create_app`), co ulatwia testowanie.
