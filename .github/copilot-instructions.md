# Church Music Organizer — Copilot Instructions

> Dokument referencyjny dla agentów AI kontynuujących pracę nad projektem.
> Ostatnia aktualizacja: 2026-02-17

### Related Documents

| Document | Purpose |
|----------|---------|
| `.github/copilot-instructions.md` | **THIS FILE** — project overview, architecture, known issues |
| `.github/process-instruction.md` | OMR domain knowledge, pipeline theory, per-step metrics definitions |
| `.github/development-process.md` | **Development methodology** — TDD workflow, test case structure, metrics framework, refactoring plan |

### Critical Rules for Agents

1. **Read `development-process.md` before any implementation work** — it defines the TDD workflow, test case schema, and Definition of Done.
2. **Use Poetry** for all dependency management: `poetry add <pkg>`, `poetry install`, `poetry run pytest`.
3. **Each pipeline step must save inspectable artifacts** to `data/processed/runs/`.
4. **Write failing tests first** (TDD) in `tests/pipeline/test_step_NN_*.py`.
5. **No module may exceed 400 lines** — split before adding features.
6. **Check metrics regression** before committing — no priority-1 test case may regress on critical metrics.
7. **Terminal**: Use Git Bash as the default shell on Windows.

---

## 1. Cel projektu

Aplikacja do **archiwizacji i przetwarzania nut kościelnych** — konwersja PDF/skanów partytur chóralnych na edytowalne pliki MusicXML (MuseScore).

### Główne cele

| # | Cel | Status |
|---|-----|--------|
| 1 | Baza danych utworów z metadanymi (tytuł, kompozytor, tonacja, czas liturgiczny) | ✅ Gotowe |
| 2 | Interfejs webowy (Streamlit) do przeglądania i dodawania utworów | ✅ Gotowe |
| 3 | **OMR Pipeline** — konwersja PDF → MusicXML z poprawnymi partiami, głosami, tekstem | 🔄 W trakcie |
| 4 | Tagowanie i wyszukiwanie utworów | ✅ Gotowe |

### Kontekst muzyczny

Typowe partytury: **SATB + Organo** (Sopran/Alt na jednej pięciolinii, Tenor/Bas na drugiej, Organy na grand staff). Format polski — teksty w języku polskim, oznaczenia liturgiczne (np. "Uroczystość św. Anny"), nazwy partii: S, A, T, B, Org.

---

## 2. Stack technologiczny

| Warstwa | Technologia | Wersja |
|---------|-------------|--------|
| Język | Python | 3.11.1 |
| Zarządzanie zależnościami | Poetry | — |
| OMR Engine | **homr** | 0.6.1 |
| Analiza muzyczna | music21 | 9.9.1 |
| Ekstrakcja tekstu z PDF | PyMuPDF (fitz) | 1.27+ |
| Przetwarzanie obrazu | OpenCV | 4.8+ |
| Baza danych | SQLAlchemy + SQLite | 2.0+ |
| Frontend | Streamlit | 1.28+ |
| Konteneryzacja | Docker | — |

### Środowisko deweloperskie

```
Virtualenv:  .venv/
Aktywacja:   .venv\Scripts\activate   (Windows)
Uruchomienie pipeline:
  python convert_pdf_to_musicxml.py data/uploads/<plik>.pdf
Uruchomienie aplikacji:
  streamlit run src/app/main.py
Testy:
  pytest tests/
```

---

## 3. Struktura projektu

```
church-music-organizer/
├── .github/
│   └── copilot-instructions.md     ← TEN PLIK
│
├── src/
│   ├── app/
│   │   └── main.py                 # Streamlit UI (✅ stabilny)
│   │
│   ├── database/
│   │   ├── models.py               # SQLAlchemy models (✅ stabilny)
│   │   └── database.py             # DB init, session (✅ stabilny)
│   │
│   └── ocr/                        # ========= RDZEŃ OMR =========
│       ├── __init__.py             # Eksporty publiczne
│       │
│       │  ── NOWY PIPELINE (v2) ──────────────────────
│       ├── text_classifier.py      # ✅ Klasyfikacja tekstu PDF (tytuł, części, lyrics)
│       ├── staff_detector.py       # ✅ Detekcja pięciolinii (OpenCV horizontal projection)
│       ├── staff_splitter.py       # ✅ Wycinanie obrazów per pięciolinia/grand staff
│       ├── score_builder.py        # 🔄 Budowanie MusicXML z wyników OMR per staff
│       │
│       │  ── SILNIKI OMR ─────────────────────────────
│       ├── omr_engine.py           # Abstrakcja silnika OMR (✅ stabilny)
│       ├── engines/
│       │   ├── homr_engine.py      # ✅ Adapter homr (główny silnik)
│       │   ├── oemer_engine.py     # ⚠️ Adapter oemer (eksperymentalny)
│       │   └── audiveris_engine.py # ⚠️ Adapter Audiveris (stub)
│       │
│       │  ── POST-PROCESSING ─────────────────────────
│       ├── lyrics_aligner.py       # ✅ Przypisanie tekstu do nut wokalnych
│       ├── musicxml_validator.py   # ✅ Walidacja miar, ambitusu, tonacji
│       ├── preprocessing.py        # ✅ PDF→PNG, binaryzacja, korekcja
│       │
│       │  ── LEGACY (v1, do refaktoringu) ────────────
│       ├── pdf_text_extractor.py   # ⚠️ Stary ekstraktor (zastąpiony text_classifier)
│       ├── score_analyzer.py       # ⚠️ Stary analizator (zastąpiony score_builder)
│       ├── voice_detector.py       # ⚠️ Stary detektor głosów (do scalenia)
│       ├── sheet_music_ocr.py      # ⚠️ Legacy OCR wrapper
│       └── musicxml_converter.py   # ⚠️ Legacy konwerter
│
├── convert_pdf_to_musicxml.py      # 🔄 Główny skrypt pipeline (CLI)
│
├── tests/
│   ├── test_database.py            # ✅ Testy bazy danych
│   ├── pipeline/                   # 🔄 Per-step unit tests (TDD)
│   │   ├── test_step_01_ingestion.py
│   │   ├── test_step_02_preprocessing.py
│   │   ├── ...
│   │   └── test_step_10_integration.py
│   ├── metrics/                    # 🔄 Metrics computation & regression
│   └── fixtures/                   # Test data (ground truth per test case)
│       ├── manifest.yaml           # Master list of all test cases
│       ├── Alleluja_werset_sw_Anna/
│       │   ├── case.yaml           # Expected values per step
│       │   ├── input.pdf
│       │   └── expected_final.musicxml
│       └── Boze_moj/
│           ├── case.yaml
│           ├── input.png
│           └── expected_final.musicxml
│
├── data/
│   ├── uploads/                    # Pliki wejściowe (użytkowe, nie testowe)
│   │   ├── Alleluja_-_werset_sw_Anna.pdf       # Test: SATB + Org
│   │   ├── Alleluja_-_werset_sw_Anna.musicxml  # Ground truth
│   │   └── 1/Panis.pdf                         # Test: 4 strony
│   └── processed/                  # Wyniki pipeline (generowane)
│
├── debug_parts.py                  # 🗑️ Skrypt debugowy (do usunięcia)
├── debug_text_positions.py         # 🗑️ Skrypt debugowy (do usunięcia)
│
├── OMR_IMPROVEMENT_PLAN.md         # Plan poprawy OMR (analiza błędów)
├── OMR_IMPLEMENTATION_PLAN.md      # Plan implementacji
├── pyproject.toml                  # Konfiguracja Poetry
├── Dockerfile / docker-compose.yml # Konteneryzacja
└── README.md                       # Dokumentacja użytkownika
```

### Legenda statusów

- ✅ — moduł stabilny, przetestowany, działa zgodnie z oczekiwaniami
- 🔄 — moduł w trakcie rozwoju, wymaga dalszej pracy
- ⚠️ — moduł legacy lub eksperymentalny, kandydat do refaktoringu/usunięcia
- 🗑️ — pliki tymczasowe, do usunięcia

---

## 4. Pipeline OMR (v2) — architektura

```
PDF ──┬── [1. TextClassifier]  ──── ClassifiedText
      │         (PyMuPDF)            {title, composer, part_names[], 
      │                               lyrics_syllables[], tempo, arranger}
      │
      └── [2. Preprocessing]   ──── page_images[] (PNG 300 DPI)
              (PyMuPDF + OpenCV)
                    │
            [3. StaffDetector] ──── StaffLayout
              (horizontal projection)  {staves[], groups[], systems[]}
                    │
            [4. StaffSplitter] ──── staff_images[] 
              (crop per staff/brace)   {path, staff_indices, group_type}
                    │
            [5. OMR per staff] ──── OMRResult per staff image
              (homr engine)            {musicxml_path, measures, staves}
                    │
            [6. ScoreBuilder]  ──── Complete MusicXML
              (ElementTree XML)        {parts, voices, backup, metadata}
                    │
            [7. LyricsAligner] ──── MusicXML + lyrics
              (music21)                {syllables on vocal notes}
                    │
            [8. Validator]     ──── Final validated .musicxml
              (music21)                {beat check, range check, fixes}
```

### Kluczowe decyzje architektoniczne

1. **ElementTree zamiast music21 do budowania XML** — daje precyzyjną kontrolę nad `<backup>`, `<forward>`, `<voice>`, `<staff>` elementami. music21 automatycznie zmienia strukturę (np. dzieli grand staff organu na 2 PartStaff), co powodowało błędy.

2. **DIVISIONS = 4** — stała w `ScoreBuilder`. Wszystkie duracje w MusicXML przeliczane przez `_ql_to_div()`. DIVISIONS=1 powodowało utratę precyzji dla nut krótszych niż ćwierćnuta.

3. **Voice separation per staff z backup** — w organowym grand staff: staff 1 → voice 1,2,3; staff 2 → voice 5,6,7. Między nimi `<backup>` do początku taktu.

4. **Greedy interval scheduling** dla separacji głosów — metoda `_separate_into_voices()` przydziela nakładające się nuty do osobnych głosów.

---

## 5. Co działa dobrze (mocne strony)

| Moduł | Opis |
|-------|------|
| `TextClassifier` | Ekstrakcja tytułu, kompozytora, aranżera, nazw partii, tekstu, tempa — działa bezbłędnie na testowanych PDF-ach |
| `StaffDetector` | Poprawna detekcja 4 pięciolinii, rozpoznanie brace (organy) — OpenCV horizontal projection + klastrowanie |
| `StaffSplitter` | Wycinanie per-pięciolinia z odpowiednim marginesem, zachowanie brace jako jednego obrazu |
| `ScoreBuilder` — struktura | Poprawny 3-partyjny MusicXML: SA (bracket), TB (bracket), Organo (brace/grand staff) |
| `ScoreBuilder` — grand staff | Poprawne `<backup>` + wielogłosowe voice separation na organowym grand staff |
| `MusicXMLValidator` | Offset-based beat counting (nie sumuje naiwnie głosów), auto-fill brakujących pauz |
| `LyricsAligner` | Dynamiczne wykrywanie partii wokalnych z PartDefinition.is_vocal |

---

## 6. Słabe strony i znane problemy

### 🔴 Krytyczne

| Problem | Moduł | Opis |
|---------|-------|------|
| **Vocal OMR barline detection** | `homr_engine` | homr źle rozpoznaje kreski taktowe na wyciętych obrazach pojedynczych pięciolinii — SA ma 2 takty zamiast 6, TB też 2 |
| **SA Measure 1: 11 beats** | `homr_engine` | homr wrzuca 4-beatowy rest + 4-beatową nutę + 3 nuty = 11 zamiast 4.0 |
| **TB Time Signature 5/4** | `homr_engine` | homr błędnie rozpoznaje 5/4 zamiast 4/4 na basetowym kluczu |

### 🟡 Ważne

| Problem | Moduł | Opis |
|---------|-------|------|
| **Brak multi-page assembly** | `convert_pdf_to_musicxml.py` | Takty ze stron 2+ nie są łączone z taktami ze strony 1 (każda strona tworzy osobny zbiór miar) |
| **Brak voice separation w SATB** | `score_builder.py` | SA staff powinien mieć voice 1 (S) + voice 2 (A), ale homr daje jedną linię melodyczną |
| **Legacy code pollution** | `src/ocr/` | 5 modułów legacy (pdf_text_extractor, score_analyzer, voice_detector, sheet_music_ocr, musicxml_converter) nie są używane ale wciąż eksportowane w `__init__.py` |
| **Brak unit testów OMR** | `tests/` | Brak testów dla nowych modułów (text_classifier, staff_detector, staff_splitter, score_builder) |
| **Debug scripts w repozytorium** | root | `debug_parts.py`, `debug_text_positions.py` — do usunięcia |

### 🟢 Mniejsze

| Problem | Moduł | Opis |
|---------|-------|------|
| **Brak anacrusis** | `score_builder.py` | Wykrywanie przedtaktów działa ale homr nie zawsze daje poprawne dane |
| **Brak recto tono** | — | Nuty psalmodyczne (stem=none) nie są rozpoznawane |
| **Brak tie/slur** | `homr_engine` | homr czasem wykrywa ligaturę ale nie propaguje do XML |
| **Part name "Org." vs "Organo"** | `score_builder.py` | Skrót zamiast pełnej nazwy (kosmetyczne) |
| **Lint warnings** | `score_builder.py` | ~40 warningów flake8 (line too long, unused imports) |

---

## 7. Kierunki rozwoju (Roadmap)

### Priorytet 1 — Poprawa jakości OMR

1. **Alternatywny silnik OMR** — przetestować Audiveris (Java) lub MuseScore OMR jako zamiennik/uzupełnienie homr. homr źle radzi sobie z wyciętymi pojedynczymi pięcioliniami.
2. **Kontekstowa korekta barlines** — po OMR, porównywać pozycje kresek taktowych wykrytych przez OpenCV z tymi z OMR i korygować.
3. **Multi-page assembly** — łączenie taktów z wielu stron w jedną partyturę (wykrywanie kontynuacji systemu).
4. **Voice separation w partiach wokalnych** — rozdzielenie SA na voice 1 (sopran, stem up) + voice 2 (alt, stem down) na podstawie kierunku lasek nut.

### Priorytet 2 — Refaktoring i testy

5. **Usunąć legacy modules** — `pdf_text_extractor.py`, `score_analyzer.py`, `voice_detector.py`, `sheet_music_ocr.py`, `musicxml_converter.py` — wyczyścić `__init__.py`.
6. **Unit testy** — pokrycie nowych modułów (TextClassifier, StaffDetector, StaffSplitter, ScoreBuilder). Test z ground truth MusicXML.
7. **Integracja z Streamlit UI** — dodać przycisk "Convert PDF→MusicXML" w interfejsie.
8. **Lint cleanup** — naprawa warningów flake8/pylint w `score_builder.py`.

### Priorytet 3 — Nowe funkcjonalności

9. **Batch processing** — konwersja wielu PDF jednocześnie.
10. **Recto tono** — wykrywanie i oznaczanie nut psalmodycznych.
11. **Ground truth evaluation** — automatyczne porównanie wyników OMR z referencyjnym MusicXML (note-by-note diff).
12. **Export to MuseScore** — bezpośrednie otwieranie .musicxml w MuseScore.

---

## 8. Role agentów AI

Projekt nadaje się do podziału między wyspecjalizowanych agentów:

### Agent 1: **OMR Quality Engineer**
- **Odpowiedzialność**: Poprawa jakości rozpoznawania nut
- **Zadania**:
  - Testowanie alternatywnych silników OMR (Audiveris, MuseScore)
  - Implementacja contextual barline correction (OpenCV barlines vs OMR barlines)
  - Voice separation w partiach SATB (pitch + stem direction analysis)
  - Budowanie zbioru testów z ground truth MusicXML
- **Pliki**: `src/ocr/engines/`, `src/ocr/staff_detector.py`, `src/ocr/score_builder.py`
- **Potrzebna wiedza**: MusicXML spec, OpenCV, music21 API, homr/Audiveris internals

### Agent 2: **Score Builder Architect**
- **Odpowiedzialność**: Składanie i walidacja MusicXML
- **Zadania**:
  - Multi-page assembly (łączenie stron)
  - Naprawa beat counting w partiach wokalnych po OMR
  - Recto tono detection
  - Anacrusis refinement
  - Refaktoring `score_builder.py` (1186 linii — podzielić na klasy)
- **Pliki**: `src/ocr/score_builder.py`, `src/ocr/musicxml_validator.py`, `src/ocr/lyrics_aligner.py`
- **Potrzebna wiedza**: MusicXML 4.0 spec (backup, forward, voice, staff), ElementTree XML

### Agent 3: **Code Quality & DevOps**
- **Odpowiedzialność**: Jakość kodu, testy, CI/CD
- **Zadania**:
  - Usunięcie legacy modules
  - Napisanie unit/integration testów
  - Lint cleanup (flake8, black, isort)
  - Usunięcie debug scripts
  - Aktualizacja README i dokumentacji
  - Konfiguracja CI/CD (GitHub Actions)
  - Docker optimization
- **Pliki**: `tests/`, `pyproject.toml`, `.github/`, `README.md`, `Dockerfile`
- **Potrzebna wiedza**: pytest, GitHub Actions, Docker, Python packaging

### Agent 4: **UI/UX & Integration**
- **Odpowiedzialność**: Interfejs użytkownika i spójność aplikacji
- **Zadania**:
  - Integracja pipeline OMR z Streamlit UI (przycisk konwersji, postęp)
  - Podgląd MusicXML w przeglądarce (embed MuseScore Web Player?)
  - Batch upload i konwersja
  - Poprawa UX przeglądania kolekcji
- **Pliki**: `src/app/main.py`, `convert_pdf_to_musicxml.py`
- **Potrzebna wiedza**: Streamlit API, frontend basics

---

## 9. Gitflow

### Konwencja branchy

```
main                          ← produkcja, stabilna
├── feature/omr-barline-fix   ← nowe funkcjonalności
├── feature/multi-page        
├── refactor/remove-legacy    ← refactoring
├── fix/vocal-beat-count      ← bugfixy
├── test/omr-unit-tests       ← testy
└── docs/update-readme        ← dokumentacja
```

### Konwencja commitów

```
feat: add multi-page assembly to ScoreBuilder
fix: correct beat counting for SATB vocal parts
refactor: remove legacy pdf_text_extractor module
test: add unit tests for TextClassifier
docs: update project architecture in README
chore: clean up debug scripts
```

### Workflow

1. Utwórz branch z `main`: `git checkout -b feature/nazwa`
2. Commituj zmiany z konwencją powyżej
3. Uruchom testy: `pytest tests/`
4. Uruchom pipeline testowy: `python convert_pdf_to_musicxml.py data/uploads/Alleluja_-_werset_sw_Anna.pdf`
5. Porównaj wynik z ground truth: `data/uploads/Alleluja_-_werset_sw_Anna.musicxml`
6. Pull request do `main`

---

## 10. Pliki testowe i ground truth

| Plik | Opis | Strony | Partie |
|------|------|--------|--------|
| `data/uploads/Alleluja_-_werset_sw_Anna.pdf` | Alleluja z wersetem, SATB + Org | 1 | 3 (SA, TB, Org) |
| `data/uploads/Alleluja_-_werset_sw_Anna.musicxml` | **Ground truth** — ręcznie stworzony poprawny MusicXML | — | 3 |
| `data/uploads/1/Panis.pdf` | Panis angelicus, 4 strony | 4 | ? |

### Jak testować pipeline

```bash
# Uruchom konwersję
python convert_pdf_to_musicxml.py data/uploads/Alleluja_-_werset_sw_Anna.pdf

# Wynik: data/processed/Alleluja_-_werset_sw_Anna_final.musicxml

# Otwórz w MuseScore aby wizualnie porównać
# Lub porównaj programowo:
python -c "
import music21
exp = music21.converter.parse('data/uploads/Alleluja_-_werset_sw_Anna.musicxml')
act = music21.converter.parse('data/processed/Alleluja_-_werset_sw_Anna_final.musicxml')
print(f'Expected parts: {len(exp.parts)}, Actual: {len(act.parts)}')
for i in range(min(len(exp.parts), len(act.parts))):
    e, a = exp.parts[i], act.parts[i]
    print(f'Part {i}: {e.partName} vs {a.partName}, '
          f'measures {len(list(e.getElementsByClass(\"Measure\")))} vs '
          f'{len(list(a.getElementsByClass(\"Measure\")))}')
"
```

### Aktualne wyniki porównania (2026-02-16)

| Metryka | Ground Truth | Pipeline | Uwagi |
|---------|-------------|----------|-------|
| Części (parts) | 3 (SA, TB, Org) | 3 (SA, TB, Org) | ✅ Poprawne |
| Nazwy partii | S A, T B, Organo | S A, T B, Org. | ⚠️ Skrót zamiast pełnej formy |
| Pitch range SA | 60-72 | 62-72 | ⚠️ Zbliżone |
| Pitch range TB | 48-60 | 48-60 | ✅ Identyczne |
| Pitch range Org treble | 60-72 | 60-72 | ✅ Identyczne |
| Pitch range Org bass | 41-57 | 41-57 | ✅ Identyczne |
| Takty SA | 6 | 2 | 🔴 homr barline detection |
| Takty TB | 6 | 2 | 🔴 homr barline detection |
| Takty Org | 6 | 4 | 🟡 Bliżej, ale wciąż brakuje |
| Organ beat count | 4.0/measure | 4.0/measure | ✅ Poprawne (po backup fix) |
| Bracket group | SA+TB | SA+TB | ✅ Poprawne |
| Metadane (tytuł) | ✅ | ✅ | Poprawnie z TextClassifier |

---

## 11. Szczegóły kluczowych modułów

### `score_builder.py` — **wymaga refaktoringu**

Największy i najważniejszy moduł (1186 linii). **Powinien być podzielony** na:

- `part_definition.py` — `PartDefinition` dataclass, `_determine_parts()`, `_find_part_name()`, `_assign_instrument()`
- `xml_writer.py` — `_build_musicxml()`, `_fill_part_from_omr()`, `_write_voice_notes()`, `_write_grand_staff_measure()`
- `score_builder.py` — orkiestrator: `build()`, `build_from_single_omr()`

Kluczowe stałe:
- `DIVISIONS = 4` — jednostki duracji na ćwierćnutę
- `INSTRUMENT_MAP` — mapowanie nazw partii na instrumenty

### `text_classifier.py` — **stabilny, dobrze zaprojektowany**

Klasyfikuje tekst z PDF na podstawie pozycji (rel_x, rel_y), fontu, rozmiaru. Kluczowe heurystyki:
- Tytuł: `rel_y < 0.08`, `font_size > 12`, wycentrowany
- Nazwy partii: `rel_x < 0.08`, zawiera S/A/T/B/Org.
- Lyrics: `rel_y < 0.15`, po prawej od nazw partii
- Fonty muzyczne (Leland, Bravura) → ignorowane

### `staff_detector.py` — **solidny, ale prosty**

Horizontal projection + clustering. Ograniczenia:
- Nie wykrywa kresek taktowych (potential improvement)
- Bracket detection opiera się na spacing heuristic (nie wizualne)
- Brace detection działa dobrze (vertical connector w lewym marginesie)

---

## 12. Konwencje kodowania

- **Python 3.10+**, type hints wszędzie
- **Docstrings** w formacie Google (Args, Returns, Raises)
- **Logging** przez `logging.getLogger(__name__)`, nie `print()`
- **Ścieżki** przez `pathlib.Path`, nie stringi
- **Testy** w `tests/`, nazewnictwo `test_<module>.py`
- **Formatowanie**: black (line-length=100), isort (profile=black)
- **Język kodu**: angielski (nazwy, docstrings), polski (komentarze, dokumentacja, commity opcjonalnie)
