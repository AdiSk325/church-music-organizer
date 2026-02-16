# OMR Improvement Plan — Analiza błędów i plan poprawy

## 1. Porównanie: wynik OMR vs oczekiwany MusicXML

### Oczekiwany wynik (Alleluja_-_werset_sw_Anna.musicxml)

| Cecha | Wartość |
|-------|---------|
| **Tytuł** | "Alleluja - werset" |
| **Części (parts)** | 3: **P1** = S/A (Sopran+Alt), **P2** = T/B (Tenor+Bas), **P3** = Organo |
| **Instrumenty** | Women (voice.female), Men (voice.male), Organo (keyboard.organ) |
| **Klucze** | P1: klucz wiolinowy (G2), P2: klucz basowy (F4), P3: 2 pięciolinie (G2+F4) |
| **Tonacja** | C-dur (fifths=0) |
| **Metrum** | 4/4 (ukryte: print-object="no") |
| **Tempo** | ♩=80 (Alleluja), ♩=100 (Wstęp organowy) |
| **Głosy w P1** | voice 1 (Sopran ↑) + voice 2 (Alt ↓) |
| **Głosy w P2** | voice 1 (Tenor ↑) + voice 2 (Bas ↓) |
| **Głosy w P3** | voice 1+2 na staff 1, voice 5+6 na staff 2 |
| **Takty** | 0 (anacrusis) + 1 (z kreską końcową) + 2-5 (organo wstęp) |
| **Tekst** | Lyrics na voice 2 w P1 (recytowany tekst): "Jawicie się jako źródła…" |
| **Układ** | Bracket łączący P1+P2, Organo osobno |
| **Pismo rektalne** | Notehead "normal" z stem "none" na nutach recytowanych (♩ recto tono) |

### Wynik OMR (Alleluja_-_werset_sw_Anna_page_1.musicxml)

| Cecha | Wartość |
|-------|---------|
| **Tytuł** | "arafiasw Jozefa" (błędny! — OCR text misread) |
| **Części** | 1: Piano (zamiast 3 partii!) |
| **Klucze** | Tylko G2 (brak F4) |
| **Tonacja** | C-dur (poprawna) |
| **Metrum** | Brak jawnego time signature |
| **Tempo** | Brak |
| **Głosy** | voice 1 + voice 2 — ale wszystko w jednym part |
| **Takty** | 6 (bez anacrusis) — zamiast 6 taktów (0-5) |
| **Tekst** | Błędnie przydzielony: "A", "T", "B", "Org.", "czy", "a", "Duch"… (to nazwy partii i inne teksty!) |
| **Staves** | homr wykrył 4 staffs ale merged je do 1 connected staff [1,1] |

---

## 2. Analiza błędów — od najpoważniejszych

### BŁĄD 1: Jedna partia zamiast trzech (KRYTYCZNY)
- **Problem**: homr widzi 4 pięciolinie ale łączy je w 1 "connected staff" `[1,1]`
- **Oczekiwane**: 3 parts: SA (treble), TB (bass), Organ (grand staff)
- **Przyczyna**: homr nie rozpoznaje grup pięcioliniowych z bracket/brace
- **Skutek**: Nuty z wszystkich partii zrzucone do jednego part. Nuty basowe (B2, A2, G2, F2) traktowane jako treble.

### BŁĄD 2: Nuty ze wszystkich pięciolinii zmiksowane (KRYTYCZNY)
- **Problem**: Measure 1 w OMR ma 7 beats (3 za dużo) — bo nuty z 2 pięciolinii SA i TB są razem
- **Measure 2-6**: 12-14 beats zamiast 8 (4/4) — miksuje nuty z 3-4 pięciolinii
- **Oczekiwane**: Każdy part/staff powinien mieć osobne nuty w granicach metrum 4/4

### BŁĄD 3: Brak rozpoznania struktury partytury (KRYTYCZNY)
- **Problem**: Brak informacji o bracket między SA i TB, brak rozpoznania Organo jako grand staff
- **Oczekiwane**: `<part-group>` z bracket dla chóru, osobna partia organowa z 2 staffami
- **Przyczyna**: Pipeline nie analizuje wizualnego układu partytury przed OMR

### BŁĄD 4: Błędny tytuł — "arafiasw Jozefa" (POWAŻNY)
- **Problem**: homr czyta tekst z partytury jako tytuł — "arafiasw Jozefa" to zepsute "Parafii św. Józefa"
- **Oczekiwane**: "Alleluja - werset"
- **Przyczyna**: homr próbuje OCR tekstu ale nie jest do tego zoptymalizowany. Prawdziwy tytuł powinien być extractowany z warstwy tekstowej PDF.

### BŁĄD 5: Lyrics błędnie przypisane (POWAŻNY)
- **Problem**: Syllables "A", "T", "B", "Org.", "czy", "a", "Duch", "spo", "nich." — to fragmenty nazw partii i przypadkowe słowa z PDF, NIE tekst pieśni
- **Oczekiwane**: "Jawicie się jako źródła światła w świecie, Trzymając się mocno Słowa Życia."
- **Przyczyna**: PDFTextExtractor wyciąga wszystkie teksty bez rozróżnienia na: tytuł, nazwy partii, oznaczenia, tekst pieśni, copyright

### BŁĄD 6: Brak anacrusis (takt 0) (WAŻNY)
- **Problem**: Pierwszy takt numerowany jako 1, bez `implicit="yes"`
- **Oczekiwane**: Measure 0 z atrybutem implicit="yes" (przedtakt)
- **Przyczyna**: homr nie rozpoznaje przedtaktów

### BŁĄD 7: Brak metrum i tempa (WAŻNY)
- **Problem**: Brak `<time>`, brak `<sound tempo="80"/>`
- **Oczekiwane**: 4/4 (print-object="no"), tempo ♩=80
- **Przyczyna**: homr rozpoznaje metrum ale nie zawsze je emituje w XML

### BŁĄD 8: Brak rozpoznania "recto tono" (MNIEJSZY)
- **Problem**: Nuty recytowane (na jednej wysokości) powinny mieć `<stem>none</stem>` i `<notehead>normal</notehead>`
- **Oczekiwane**: Specjalne formatowanie nut psalmodycznych
- **Przyczyna**: homr nie obsługuje tej konwencji muzyki sakralnej

### BŁĄD 9: Brak tie/slur (MNIEJSZY)
- **Problem**: W OMR brak ligatur (tie) które są w oryginale
- **Oczekiwane**: Tie w partiach wokalnych (np. C5 tie w m.1 SA)
- **Przyczyna**: homr czasem je rozpoznaje (widać tieStart/tieStop w logach) ale nie poprawnie

---

## 3. Plan poprawy — podejście "od ogółu do szczegółu"

### Faza 0: Pre-OMR — Analiza wizualnej struktury PDF

**Cel**: Zanim uruchomimy OMR, wyciągnijmy z PDF/obrazu wszystkie metadane i informacje strukturalne.

#### 0.1 Ekstrakcja metadanych z warstwy tekstowej PDF
```
Wejście:  PDF
Wyjście:  {title, composer, part_names[], tempo[], 
           lyrics_text, instrument_labels, 
           copyright, other_annotations}
```
- Użyć PyMuPDF do ekstrakcji WSZYSTKICH tekstów z pozycjami (x, y, fontsize)
- **Klasyfikacja tekstu po pozycji**: tytuł (góra strony, duża czcionka), kompozytor (pod tytułem), nazwy partii (lewa strona, przy pięciolinii), tempo (nad pięciolinią, kursywa), tekst pieśni (pod nutami, między pięcioliniami), copyright (dół strony)
- **Klucz**: nie wrzucać nazw partii (S, A, T, B, Org.) do lyrics!

#### 0.2 Detekcja układu pięciolinii (Staff Layout Detection)
```
Wejście:  Obraz strony (PNG)
Wyjście:  {staves: [{y_top, y_bottom, x_left, x_right, clef_type}],
           staff_groups: [{type: bracket/brace, staff_indices: [0,1]}],
           systems: [{staff_indices: [0,1,2,3]}]}
```
- Użyć OpenCV do wykrywania linii poziomych (pięciolinii)
- Grupować 5 linii w staff, staffs w systemy
- Wykrywać bracket/brace po lewej stronie (łączenie partii)
- Określić klucz na podstawie pozycji (wiolinowy/basowy)
- **To daje nam**: liczbę partii, liczbę głosów, grand staffs vs. osobne

#### 0.3 Detekcja kresek taktowych i metrum
```
Wejście:  Obraz strony
Wyjście:  {barlines: [{x_position, type, spans_staves}],
           time_signature: "4/4",
           measure_count: N}
```
- Wykrywać pionowe kreski (barlines) przechodzące przez jeden lub wiele staffs
- Policzyć takty
- Szukać oznaczeń metrum (4/4, 3/4, etc.)
- Rozpoznać double barline, final barline

### Faza 1: Inteligentny OMR — na każdą pięciolinię osobno

#### 1.1 Wycinanie poszczególnych pięciolinii/systemów
```
Wejście:  Obraz strony + staff_layout z Fazy 0.2
Wyjście:  [staff_image_1.png, staff_image_2.png, ...]
```
- Wycinać każką pięciolinię osobno (z marginesem)
- Lub wycinać grand staff (2 pięciolinie z klamrą) razem
- **Podać homr/oemer** nie cały obraz, ale poszczególne staff image

#### 1.2 OMR per staff/staff-group
```
Wejście:  staff_image_N.png
Wyjście:  OMRResult per staff
```
- Każdy staff → osobny OMR run
- Dzięki temu homr nie zmiesza nut z różnych partii
- Wynik: lista OMRResult[] — jeden per staff

#### 1.3 Mapowanie OMR results → Parts
```
Wejście:  OMRResult[], staff_layout, text_metadata
Wyjście:  {P1: {name: "S/A", staves: [result_0]},
           P2: {name: "T/B", staves: [result_1]}, 
           P3: {name: "Organo", staves: [result_2, result_3]}}
```
- Używając staff_groups z Fazy 0.2, mapować staffy do partii
- Nazwy partii z text_metadata (z Fazy 0.1)

### Faza 2: Budowanie MusicXML — składanie wyniku

#### 2.1 Tworzenie struktury part-list
```xml
<part-list>
  <part-group type="start" number="1">
    <group-symbol>bracket</group-symbol>
  </part-group>
  <score-part id="P1"><part-name>S\nA</part-name>...</score-part>
  <score-part id="P2"><part-name>T\nB</part-name>...</score-part>
  <part-group type="stop" number="1"/>
  <score-part id="P3"><part-name>Organo</part-name>...</score-part>
</part-list>
```
- Na podstawie staff_groups i part_names

#### 2.2 Wypełnianie partii nutami z OMR
- Każdy OMR result → odpowiedni `<part>`
- Dla grand staff (Organo): dwa staves w jednym part, voice 1-2 + voice 5-6
- Dla SA/TB: voice 1 (górny głos) + voice 2 (dolny głos)

#### 2.3 Dodawanie metadanych
- `<work-title>` z text_metadata.title
- `<creator type="composer">` z text_metadata.composer
- `<time>` z detected time signature
- `<sound tempo="...">` z text_metadata.tempo
- `<key>` — weryfikacja z analizy nut

#### 2.4 Detekcja anacrusis
- Jeśli pierwszy takt ma mniej niż pełne metrum → `implicit="yes"` i `number="0"`
- Policzyć beats w pierwszym takcie vs metrum

### Faza 3: Post-processing — lyrics, recto tono, walidacja

#### 3.1 Inteligentne przypisanie lyrics
- Tekst pieśni (z Fazy 0.1, sklasyfikowany poprawnie) → przypisać do partii wokalnych
- Reguły:
  - Lyrics idą zawsze pod nutami recytowanymi lub pod linią melodyczną
  - Nie przypisywać nazw partii, oznaczeń temp, copyrightów!
  - Syllabiki: `begin`/`middle`/`end`/`single` na podstawie łączników `-`
  - Jeśli tekst pod nutą recytowaną (recto tono) — całe zdanie pod jedną nutę

#### 3.2 Detekcja recto tono
- Jeśli seria nut na tej samej wysokości (np. E4, E4, E4, E4) z tekstem → recto tono
- Ustawić `<stem>none</stem>`, `<notehead>normal</notehead>`
- Typowe dla psalmów, alleluja, wersetów

#### 3.3 Walidacja finalna
- Sprawdzić: beats per measure == time signature
- Sprawdzić: ambitus per voice (SA: C4-C6, TB: C2-C4, Organ: C2-C6)
- Sprawdzić: key signature zgodna z nutami
- Naprawić: brakujące rests, nieprawidłowe durations

---

## 4. Priorytety implementacji

### Priorytet 1 — Krytyczne (bez tego wynik jest bezużyteczny)
1. **Staff Layout Detection** — rozpoznawanie ile jest partii/pięciolinii
2. **OMR per staff** — rozbicie OMR na osobne pięciolinie  
3. **Part assembly** — budowanie wieloczęściowego MusicXML
4. **Text classification** — rozróżnienie title/composer/part_names/lyrics/tempo

### Priorytet 2 — Ważne (poprawia jakość)
5. **Anacrusis detection** — rozpoznawanie przedtaktów
6. **Time signature detection** — wykrywanie metrum
7. **Intelligent lyrics alignment** — poprawne przypisanie tekstu
8. **Voice separation** — voice 1 (górny) vs voice 2 (dolny) w ramach staff

### Priorytet 3 — Ulepszenia (dopracowanie)
9. **Recto tono detection** — nuty psalmodyczne
10. **Tempo/expression detection** — oznaczenia tempowe
11. **Tie/slur correction** — poprawność ligatur
12. **Grand staff assembly** — organo z voice 5-6

---

## 5. Konkretne zmiany w kodzie

### Nowe moduły do stworzenia:
1. `src/ocr/text_classifier.py` — klasyfikacja tekstu z PDF (title, composer, parts, lyrics, tempo, annotations)
2. `src/ocr/staff_detector.py` — wizualna detekcja pięciolinii, kresek taktowych, klamer, kluczy
3. `src/ocr/staff_splitter.py` — wycinanie poszczególnych pięciolinii do osobnych obrazów
4. `src/ocr/score_builder.py` — budowanie wieloczęściowego MusicXML z wyników OMR per staff

### Moduły do poprawy:
5. `src/ocr/pdf_text_extractor.py` — dodać pozycje tekstu (x, y), rozmiar czcionki, klasyfikację
6. `src/ocr/lyrics_aligner.py` — nie wrzucać nazw partii/tempa do lyrics
7. `src/ocr/voice_detector.py` — rozpoznawanie na podstawie layout, nie tylko pitch range
8. `convert_pdf_to_musicxml.py` — nowy pipeline: layout detection → per-staff OMR → assembly

### Diagram nowego pipeline:

```
PDF ──┬── [TextClassifier] ──── {title, composer, parts, lyrics, tempo}
      │                                          │
      └── [StaffDetector]  ──── {staves[], groups[], systems[]}
              │                           │
              └── [StaffSplitter] ── [staff_1.png, staff_2.png, ...]
                        │
                  [OMR per staff] ── [OMRResult_1, OMRResult_2, ...]
                        │
                  [ScoreBuilder] ──── Complete MusicXML
                        ↑                    │
                  parts, groups,        [LyricsAligner]
                  metadata                   │
                                        [Validator]
                                             │
                                        Final .musicxml
```
