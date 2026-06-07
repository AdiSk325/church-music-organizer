# QuickStart — Church Music Organizer

Przewodnik po aktualnej wersji projektu (v2.0 — czerwiec 2026).

---

## Uruchomienie lokalne

### Wymagania systemowe

```bash
# Ubuntu/Debian
sudo apt-get install -y tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng \
  poppler-utils libmagic1

# macOS
brew install tesseract tesseract-lang poppler libmagic
```

### Instalacja i start

```bash
git clone https://github.com/AdiSk325/church-music-organizer.git
cd church-music-organizer
pip install -r requirements.txt
streamlit run src/app/main.py       # http://localhost:8501
```

### Docker (zalecane — bez instalacji zależności systemowych)

```bash
docker-compose up -d                # http://localhost:8501
```

---

## Co umie aktualna wersja

### Music Collection (zakładka 1)
- **Dodawanie pieśni** — formularz z 23 polami: tytuł, kompozytor, autorzy, tonacja, metrum, okazja liturgiczna, tagi itp.
- **Wyszukiwanie** — pasek szuka po tytule, kompozytorze i autorze słów (ILIKE, case-insensitive)
- **Filtry** — Okazja (Wielkanoc, Boże Narodzenie…) i Okres liturgiczny (Adwent, Wielki Post…)
- **Paginacja** — 20 wyników na stronę
- **Edycja inline** — szybka zmiana kluczowych pól bez wchodzenia w szczegóły
- **Usuwanie** — usuwa utwór wraz z plikami i historią wykonań (cascade)

### Song Details (zakładka 2)
- **Pełne metadane** — wszystkie 23 pola, tagi, tekst słów, link MuseScore
- **Upload plików** — PDF, skany (JPG/PNG/TIFF), pliki MuseScore (.mscz), MusicXML (.xml)
- **OCR na żądanie** — przycisk "🔍 OCR" przy każdym pliku PDF/skanie:
  - uruchamia Tesseract (PL + EN) z preprocessingiem OpenCV
  - wykrywa obecność notacji muzycznej (Hough transform)
  - zapisuje wyekstrahowany tekst i ocenę pewności (0-100%) do bazy
  - wynik widoczny od razu w rozwijalnym panelu tekstowym
- **Historia wykonań** — kiedy i gdzie utwór był wykonany

---

## Komendy deweloperskie

```bash
# Testy
python3 -m pytest tests/unit/ -v              # 51 testów jednostkowych
python3 -m pytest tests/unit/ -q              # szybki przebieg
python3 -m pytest tests/unit/ -k "ocr"        # tylko testy OCR
python3 -m pytest tests/functional/ -v        # testy OCR na prawdziwych plikach
                                               # (pomijane gdy brak fixtures)
# Pokrycie
python3 -m pytest tests/unit/ --cov=src --cov-report=term-missing

# Formatowanie
black src/ tests/
isort src/ tests/

# Migracje bazy
alembic upgrade head                           # zastosuj wszystkie migracje
alembic revision --autogenerate -m "opis"      # nowa migracja po zmianie modelu
alembic downgrade -1                           # cofnij ostatnią migrację
```

---

## Praca z agentami AI

Projekt ma 7 wyspecjalizowanych agentów Claude w `.claude/agents/`. Wywołaj je przez `/nazwa-agenta` w Claude Code CLI lub deleguj im zadanie w tej sesji.

| Agent | Kiedy używać |
|-------|-------------|
| `/product-owner` | Planowanie, priorytety, rozmowa o domenowych decyzjach |
| `/backend-engineer` | Nowe modele, migracje, warstwa serwisowa |
| `/ocr-engineer` | Pipeline OCR, preprocessing obrazów, music21 |
| `/ui-engineer` | Nowe widoki Streamlit, formularze, UX |
| `/qa-engineer` | Pisanie testów, analiza pokrycia, fixtures |
| `/devops-engineer` | CI/CD, Docker, konfiguracja środowiska |
| `/code-reviewer` | Przegląd kodu przed merge |

---

## Testy funkcjonalne OCR

Gdy masz skany nut do przetestowania — wrzuć je do repozytorium:

```
tests/functional/fixtures/
├── scans/
│   ├── koleda_boze_narodzenie.jpg    ← wrzuć skan tutaj
│   └── psalm23.pdf                   ← lub PDF
└── expected/
    └── koleda_boze_narodzenie.json   ← oczekiwany wynik
```

Format pliku `expected/*.json`:
```json
{
  "contains_text": ["Bóg się rodzi", "kolęda"],
  "has_music_notation": true,
  "min_confidence": 60
}
```

CI automatycznie uruchamia testy funkcjonalne gdy fixtures są obecne.

---

## Architektura

```
src/
├── app/main.py              ← Streamlit UI (793 linie)
├── services/
│   ├── music_piece_service.py   ← CRUD, filtrowanie, paginacja
│   ├── file_service.py          ← upload, sanityzacja ścieżki, zapis OCR
│   └── ocr_service.py           ← orkiestracja OCR (SheetMusicOCR → FileService)
├── database/
│   ├── models.py            ← MusicPiece (23 pola), MusicFile, Tag, UsageHistory
│   └── database.py          ← engine, get_db_session() (context manager)
└── ocr/
    ├── sheet_music_ocr.py       ← Tesseract wrapper, preprocessing OpenCV
    └── musicxml_converter.py    ← music21, konwersja MusicXML ← niezintegrowany
```

**Zasada sesji:** zawsze używaj `get_db_session()` jako context managera do zapisu. Serwisy robią `db.flush()` — commit należy do callera.

---

## Zmienne środowiskowe

Skopiuj `.env.example` do `.env`:

```env
DATABASE_URL=sqlite:///church_music.db   # ścieżka do bazy SQLite
UPLOAD_DIR=data/uploads                   # katalog uploadowanych plików
PROCESSED_DIR=data/processed              # katalog wyników OCR
```

---

## Znane ograniczenia (v2.0)

| Ograniczenie | Wpływ |
|---|---|
| SQLite + jeden użytkownik | Tylko do użytku lokalnego lub na zamkniętym serwerze |
| OCR wymaga Tesseract | Bez instalacji systemowej przycisk OCR zwróci błąd |
| Brak walidacji MIME | Typ pliku ustalany tylko po rozszerzeniu |
| Selectbox pieśni ładuje max 500 rekordów | Może być wolny przy bardzo dużej kolekcji |
| `init_db()` przy starcie | Przy istniejącej bazie nie zastosuje migracji Alembic — uruchom `alembic upgrade head` ręcznie po zmianie modeli |
