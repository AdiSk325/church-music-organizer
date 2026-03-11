# Optical Music Recognition — Proces, Architektura i Metodologia

> Dokument referencyjny opisujący dziedzinę OMR, jej architekturę, etapy pipeline'u,
> metody walidacji, metryki sukcesu oraz zagrożenia.
> Stanowi merytoryczny i metodologiczny kontekst dla prac nad projektem
> Church Music Organizer.
>
> Ostatnia aktualizacja: 2026-02-16

---

## 1. Definicja i zakres problemu

**Optical Music Recognition (OMR)** to dziedzina badawcza zajmująca się
komputerowym odczytywaniem notacji muzycznej z dokumentów obrazowych
(Pacha, 2019; Calvo-Zaragoza, Hajič Jr. & Pacha, 2020). Celem OMR jest
przekształcenie graficznej reprezentacji partytury w maszynowo-czytelną postać
semantyczną — najczęściej w formacie MusicXML (dla layoutu i edycji) lub MIDI
(dla odtwarzania).

### 1.1 OMR a OCR — fundamentalne różnice

OMR bywa mylnie porównywane z Optical Character Recognition (OCR), jednak
między nimi istnieją zasadnicze różnice (Bainbridge & Bell, 2001;
Byrd & Simonsen, 2015):

| Aspekt | OCR | OMR |
|--------|-----|-----|
| **Typ pisma** | Fonetyczne/logograficzne — gotowe symbole | Featuralne (cechowe) — semantyka wynika z konfiguracji prymitywów |
| **Wymiarowość** | Zasadniczo jednowymiarowe (strumień tekstu po ustaleniu baseline) | Dwuwymiarowe relacje przestrzenne — pozycja pionowa = wysokość dźwięku |
| **Głębia semantyczna** | OCR rozpoznaje litery i słowa | OMR musi odtworzyć semantykę muzyczną: pitch, duration, voices, harmony |
| **Rozmiar symboli** | Stosunkowo jednolity | Od kropki (staccato) po klamrę obejmującą całą stronę |
| **Analogia** | Odczytanie tekstu ze zdjęcia | Odtworzenie kodu HTML ze screenshota strony internetowej |

> „Recovering the music from an image of a music sheet can be as challenging
> as recovering the HTML source code from the screenshot of a website."
> — Calvo-Zaragoza, Hajič Jr. & Pacha (2020)

### 1.2 Złożoność notacji muzycznej

Donald Byrd i Jakob Simonsen (2015) argumentują, że OMR jest trudne, ponieważ
współczesna notacja muzyczna jest **ekstremalnie złożona**. Byrd udokumentował
setki przykładów niekonwencjonalnej notacji, od skomplikowanych oznaczeń
artykulacyjnych po przypadki łamiące standardowe reguły zapisu.

W kontekście **muzyki kościelnej** (domenowa specyfika tego projektu) dochodzą
dodatkowe wyzwania:
- **Recto tono** — nuty psalmodyczne bez lasek (stem=none), recytowane na jednej
  wysokości
- **Partytury SATB + Organo** — wielogłosowość na ograniczonej przestrzeni
  (sopran+alt na jednej pięciolinii, tenor+bas na drugiej)
- **Tekst polski** — sylabizacja w języku polskim pod nutami
- **Oznaczenia liturgiczne** — np. „Uroczystość św. Anny", „Adwent III"
- **Grand staff organowy** — dwie pięciolinie z klamrą dla partii organowej

### 1.3 Taksonomia wyjść systemu OMR

Zgodnie z systematyką Calvo-Zaragozy et al. (2020), systemy OMR można
klasyfikować według typu wyjścia:

| Typ wyjścia | Cel | Format | Poziom kompletności |
|-------------|-----|--------|---------------------|
| **Replayability** | Odtworzenie audio | MIDI | Niski — bez informacji wizualnych |
| **Reprintability** | Wierne odtworzenie zapisu | MusicXML, MEI | Wysoki — pełna rekonstrukcja layoutu |
| **Searchability** | Wyszukiwanie wzorców | Dowolny strukturalny | Średni — wystarczy semantyka bez layoutu |

W projekcie Church Music Organizer docelowym formatem jest **MusicXML**
(reprintability) — musi on zawierać pełną informację o partiach, głosach,
tekście, klawiszach, grupowaniu pięciolinii.

---

## 2. Ramy teoretyczne — ewolucja architektury OMR

### 2.1 Framework Bainbridge'a i Bella (2001)

Pierwszy systematyczny framework OMR zaproponowany przez Davida Bainbridge'a
i Tima Bella (2001) w pracy „The Challenge of Optical Music Recognition"
definiuje cztery etapy:

1. **Staff detection & removal** — wykrywanie i usuwanie pięciolinii
2. **Musical object detection** — detekcja symboli muzycznych
3. **Musical notation reconstruction** — odtworzenie struktury muzycznej
4. **Final representation construction** — generowanie formatu wyjściowego

Framework ten kładł nacisk na detekcję wizualną obiektów, ale często pomijał
rekonstrukcję semantyki muzycznej jako krok opisywany w publikacjach.

### 2.2 Framework Rebelo et al. (2012)

Ana Rebelo et al. (2012) w jednej z najczęściej cytowanych prac o OMR
(>400 cytowań) zaproponowali udoskonalony pipeline składający się z czterech
etapów:

1. **Preprocessing** — poprawa jakości obrazu
2. **Music symbols recognition** — rozpoznawanie symboli
3. **Musical notation reconstruction** — odtworzenie zapisu muzycznego
4. **Final representation construction** — budowanie wyjścia

Ten framework stał się de facto standardem i jest stosowany do dzisiaj
(z drobnymi wariacjami terminologicznymi).

### 2.3 Podejście Calvo-Zaragozy, Hajič Jr. i Pachy (2020)

Najbardziej kompleksowa systematyka OMR pochodzi z pracy „Understanding Optical
Music Recognition" (Calvo-Zaragoza, Hajič Jr. & Pacha, 2020; ACM Computing
Surveys, >250 cytowań). Autorzy proponują **pięcioetapowy framework**:

```
┌────────────────────────────────────────────────────────────────────┐
│  A. Document-level Processing                                      │
│     Segmentacja stron, identyfikacja regionów z muzyką             │
├────────────────────────────────────────────────────────────────────┤
│  B. Music Object Detection                                         │
│     Lokalizacja prymitywów: główki nut, laski, belki, klucze...    │
├────────────────────────────────────────────────────────────────────┤
│  C. Notation Assembly (Notation Graph Construction)                │
│     Łączenie prymitywów w obiekty wyższego poziomu: nuty, akordy  │
├────────────────────────────────────────────────────────────────────┤
│  D. Recover Musical Semantics                                      │
│     Przypisanie pitch, duration, voice, measure — kontekst muzyczny│
├────────────────────────────────────────────────────────────────────┤
│  E. Encoding / Output                                              │
│     Generowanie MusicXML, MEI, MIDI                                │
└────────────────────────────────────────────────────────────────────┘
```

Kluczowa obserwacja autorów: **błędy propagują się kaskadowo** — jeśli
detekcja pięciolinii (etap A) zawiedzie, wszystkie kolejne etapy na tym tracą.
Stąd wynika konieczność walidacji po każdym etapie (sekcja 5 tego dokumentu).

### 2.4 Podejścia end-to-end (od 2016)

Równolegle do podejścia pipeline'owego rozwijane są **modele end-to-end**,
które bezpośrednio mapują obraz na sekwencję symboli muzycznych:

- **Sequence-to-sequence** — van der Wel & Ullrich (2017): CNN encoder +
  RNN decoder, obraz → uproszczone kodowanie muzyczne
- **CTC-based** — Calvo-Zaragoza & Rizo (2018): CNN + BLSTM + CTC, obraz
  jednej pięciolinii → kodowanie semantyczne (ograniczone do monofonii)
- **Transformer-based** — Polyphonic-TrOMR (homr): Vision Transformer
  encoder → dekoder sekwencyjny, obsługa polifonii
- **Baró et al. (2019)** — rozszerzenie na nuty ręczne, CRNN

| Podejście | Zalety | Wady |
|-----------|--------|------|
| Pipeline (multi-stage) | Kontrola nad etapami, debugowalność, walidacja pośrednia | Kaskadowa propagacja błędów |
| End-to-end | Brak kaskady, uczenie się reprezentacji | Mniej kontroli, wymaga dużo danych, trudne debugowanie |
| **Hybrydowe** (stosowane w tym projekcie) | Łączy zalety obu podejść | Złożoność integracji |

Nasz projekt stosuje podejście **hybrydowe**: silnik OMR (homr — end-to-end
per staff) osadzony w pipeline'ie wieloetapowym z pre- i post-processingiem.

---

## 3. Architektura pipeline'u OMR w projekcie

Poniższy pipeline łączy ramy teoretyczne Rebelo et al. (2012) i Calvo-Zaragozy
et al. (2020) z praktycznymi wymaganiami projektu Church Music Organizer.

```
PDF/IMG ──┬──── [ETAP 1: Ingestion]
          │        PDF → page images (300 DPI)
          │
          ├──── [ETAP 2: Preprocessing]
          │        Binaryzacja, deskew, denoising, normalizacja
          │
          ├──── [ETAP 3: Text Extraction & Classification]  ← równoległy
          │        PyMuPDF: tytuł, kompozytor, nazwy partii, lyrics, tempo
          │
          ├──── [ETAP 4: Staff Detection & Layout Analysis]
          │        Horizontal projection, clustering → pięciolinie, systemy, grupy
          │
          ├──── [ETAP 5: Staff Splitting]
          │        Wycinanie obrazów per pięciolinia/grand staff
          │
          ├──── [ETAP 6: Music Object Detection & Recognition] ← OMR engine
          │        homr/Audiveris per staff image → OMRResult per staff
          │
          ├──── [ETAP 7: Score Assembly]
          │        Mapowanie OMR results → parts, voices, MusicXML structure
          │
          ├──── [ETAP 8: Lyrics Alignment]
          │        Przypisanie sylab do nut wokalnych
          │
          ├──── [ETAP 9: Semantic Validation & Post-processing]
          │        Kontrola taktów, ambitusu, tonacji, auto-korekta
          │
          └──── [ETAP 10: Output & Human-in-the-Loop]
                   Export MusicXML, wizualna weryfikacja w MuseScore
```

Główna zasada architektoniczna: **każdy etap produkuje zdefiniowane wyjście
i jest walidowany przed przekazaniem danych do kolejnego etapu**.

---

## 4. Szczegółowy opis etapów pipeline'u

### 4.1 Etap 1 — Ingestion (pozyskanie danych wejściowych)

#### Cel
Konwersja dokumentów wejściowych (PDF, PNG, JPEG, TIFF, zdjęcia z telefonu)
do zunifikowanego formatu obrazów stronami o kontrolowanej jakości.

#### Wejścia i wyjścia

| Element | Opis |
|---------|------|
| **Wejście** | PDF, PNG, JPEG, TIFF — pliki partytur muzycznych |
| **Wyjście** | Lista obrazów PNG: `page_images[]`, jeden obraz na stronę, min. 300 DPI |
| **Metadane** | Rozdzielczość źródłowa, liczba stron, informacja o warstwie tekstowej (embedded text vs. skan) |

#### Metody implementacji

- **PDF z warstwą tekstową** — PyMuPDF (fitz): renderowanie strony do pixmap
  z zadanym DPI. Jednocześnie ekstrakcja metadanych tekstowych (Etap 3).
- **PDF-skan (bez warstwy tekstowej)** — jak wyżej, ale metadane tekstowe
  niedostępne; konieczny OCR tekstu.
- **Obrazy (PNG/JPEG/TIFF)** — bezpośredni odczyt, standaryzacja rozdzielczości.
- **Zdjęcia z telefonu** — dodatkowa korekta perspektywy, wykrywanie krawędzi
  dokumentu (Canny edge detection → Hough lines → homografia).

#### Kluczowe parametry

| Parametr | Wartość | Uzasadnienie |
|----------|---------|-------------|
| Minimalne DPI | 300 | Poniżej 300 DPI drobne symbole (kropki, flagi) stają się nieczytelne |
| Docelowe DPI | 300 | Kompromis jakość/wydajność — modele DL zwykle trenowane na 300 DPI |
| Format wyjściowy | PNG (lossless) | JPEG wprowadza artefakty kompresji wokół cienkich linii |
| Przestrzeń kolorów | Grayscale lub RGB | Zachować RGB, jeśli kolor niesie informację (np. anotacje) |

#### Walidacja etapu 1

| Kryterium | Metoda weryfikacji | Próg akceptacji |
|-----------|-------------------|-----------------|
| Rozdzielczość | Odczyt DPI z metadanych obrazu | ≥ 300 DPI |
| Kompletność stron | Porównanie liczby stron z metadanymi PDF | 100% stron zrenderowanych |
| Czytelność | Wariancja jasności (Laplacian variance) | > 100 (obraz nie jest rozmyty) |
| Orientacja | Wykrycie poziomych linii pięciolinii | Linie bliskie horyzontalnej (±5°) |

#### Zagrożenia

| Zagrożenie | Prawdopodobieństwo | Wpływ | Mitygacja |
|------------|-------------------|-------|-----------|
| Skan o niskiej rozdzielczości (< 200 DPI) | Średnie | Wysoki — utrata detali | Super-resolution lub odrzucenie z komunikatem |
| PDF zabezpieczony hasłem | Niskie | Krytyczny | Informacja dla użytkownika, brak automatycznego obejścia |
| Zdjęcie pod kątem / z perspektywą | Średnie | Wysoki | Homografia (4-point transform) |
| Wielostronicowe partytury | Wysokie | Średni | Multi-page assembly (Etap 7) |

---

### 4.2 Etap 2 — Preprocessing (przetwarzanie wstępne obrazu)

#### Cel
Poprawa jakości obrazu w celu ułatwienia pracy kolejnym etapom.
Preprocessing jest krytycznym etapem — jakość tego kroku bezpośrednio
wpływa na accuracy detekcji symboli (Rebelo et al., 2012).

#### Operacje i ich kolejność

```
Obraz wejściowy
  → [1] Konwersja do grayscale
  → [2] Normalizacja kontrastu (CLAHE)
  → [3] Deskew (korekcja pochylenia)
  → [4] Binaryzacja (Otsu lub Sauvola)
  → [5] Denoising (usuwanie szumu)
  → [6] Morphological cleanup (opcjonalnie)
  → Obraz wyjściowy (binarny, wyrównany)
```

#### Szczegóły operacji

**Deskew (korekcja pochylenia):**
- Metoda: wykrywanie linii pięciolinii za pomocą Hough Transform lub
  horizontal projection → obliczenie kąta nachylenia → obrót affiniczny.
- Dokładność: ±0.1° jest wystarczająca.
- Uwaga: nadmierna korekta może pogorszyć wynik, jeśli oryginał był prosty.

**Binaryzacja:**
- **Otsu** — globalna binaryzacja, dobra dla jednolitego oświetlenia
  (skany drukarskie).
- **Sauvola** — lokalna adaptacyjna binaryzacja, lepsza dla zdjęć
  z nierównomiernym oświetleniem.
- Parametr okna Sauvoli: typowo 15–31 pikseli, k=0.2–0.5.

**Denoising:**
- Morphological opening z małym kernelem (1×1 lub 2×2) — usuwa
  drobne artefakty skanera.
- Uwaga: zbyt agresywny denoising usuwa kropki (staccato, augmentation dots)
  i cienkie linie (flagi nut ósemkowych).

#### Metryki sukcesu etapu 2

| Metryka | Definicja | Cel |
|---------|-----------|-----|
| Kąt deskew | Zmierzona różnica kąta pięciolinii od horyzontalnej | < 0.5° po korekcji |
| Kontrast binarny | Stosunek pikseli czarnych do białych w regionie pięciolinii | Pięciolinie widoczne jako ciągłe linie |
| Zachowanie detali | Obecność znanych małych symboli (dots) po preprocessingu | Brak utraty augmentation dots |
| Czystość tła | Procent artefaktów szumowych poza regionami muzycznymi | < 0.1% pikseli szumowych |

#### Zagrożenia

| Zagrożenie | Wpływ | Mitygacja |
|------------|-------|-----------|
| Utrata cienkich symboli (flagi, kropki) przez agresywny denoising | Krytyczny | Konserwatywne parametry morphological operations |
| Zbyt mocna binaryzacja → utrata gradientów (dynamics pp, ff) | Średni | Zachowanie obrazu grayscale jako alternatywy |
| Deskew błędnie obracający obraz (np. gdy brak pięciolinii) | Średni | Warunek: wykonuj deskew tylko jeśli wykryto pięciolinie |
| Artefakty JPEG (block artifacts) | Średni | Filtr bilateralny przed binaryzacją |

---

### 4.3 Etap 3 — Text Extraction & Classification (ekstrakcja i klasyfikacja tekstu)

#### Cel
Wyekstrahowanie z dokumentu wszelkich informacji tekstowych i ich
sklasyfikowanie według funkcji semantycznej (tytuł, kompozytor, nazwy partii,
tekst pieśni, oznaczenia tempowe, copyright).

Ten etap jest **równoległy** do etapów 4–6 (przetwarzanie wizualne) i dostarcza
kontekst semantyczny wykorzystywany w etapach 7–9 (assembly i walidacja).

#### Metoda klasyfikacji tekstu

Klasyfikacja oparta na heurystykach pozycyjnych (pozycja na stronie, rozmiar
fontu, styl fontu):

| Kategoria tekstu | Heurystyki pozycyjne | Heurystyki fontowe |
|------------------|---------------------|-------------------|
| **Tytuł** | rel_y < 0.08, wycentrowany (rel_x ≈ 0.5) | font_size > 12pt, bold |
| **Kompozytor / Aranżer** | rel_y < 0.12, wyrównany do prawej | font_size 9-12pt, italic |
| **Nazwy partii** | rel_x < 0.08, przy pięcioliniach | font_size 8-10pt |
| **Lyrics (tekst pieśni)** | Między pięcioliniami, pod nutami | font_size 8-10pt, regularny |
| **Tempo** | Nad pierwszą pięciolinią, na lewo | italic, zawiera ♩= lub słowa tempowe |
| **Copyright** | rel_y > 0.95, na dole strony | font_size < 8pt |
| **Fonty muzyczne** | — | Font name: Leland, Bravura, Opus → ignorowane |

**Kluczowa reguła**: nazwy partii (S, A, T, B, Org.) **nigdy** nie trafiają
do lyrics — to najczęstszy błąd naiwnych ekstraktorów.

#### Wejścia i wyjścia

```
Wejście:  Plik PDF (z warstwą tekstową)
Wyjście:  ClassifiedText {
            title: str,
            composer: str,
            arranger: str,
            part_names: List[str],   # np. ["S", "A", "T", "B", "Org."]
            lyrics_syllables: List[str],
            tempo: str,              # np. "Allegro ♩=120"
            copyright: str
          }
```

#### Metryki sukcesu etapu 3

| Metryka | Definicja | Próg akceptacji |
|---------|-----------|-----------------|
| Poprawność tytułu | Czy wyekstrahowany tytuł odpowiada rzeczywistemu | 100% (manualna weryfikacja na zbiorze testowym) |
| Poprawność nazw partii | Wykryte nazwy partii vs. rzeczywiste | 100% — błąd tu propaguje się do etapu 7 |
| Czystość lyrics | % tekstu lyrics niezanieczyszczonego nazwami partii / copyright | 100% |
| Recall lyrics | % sylab lyrics prawidłowo wyekstrahowanych | > 95% |

#### Zagrożenia

| Zagrożenie | Wpływ | Mitygacja |
|------------|-------|-----------|
| PDF-skan bez warstwy tekstowej (obraz flat) | Krytyczny — brak tekstu | Fallback: OCR (Tesseract) na regionach tekstowych |
| Fonty muzyczne zinterpretowane jako tekst | Wysoki — śmieciowe dane | Blacklista fontów muzycznych (Leland, Bravura, Opus, Maestro) |
| Nazwy partii wmieszane do lyrics | Wysoki | Filtrowanie po pozycji rel_x < 0.08 |
| Tekst w nietypowym layoucie (np. tytuł na dole) | Niski | Heurystyki z fallbackiem — oznaczenie jako „unclassified" |

---

### 4.4 Etap 4 — Staff Detection & Layout Analysis (detekcja pięciolinii i analiza layoutu)

#### Cel
Wykrycie pozycji pięciolinii na obrazie, pogrupowanie ich w systemy
i zidentyfikowanie grup partyjnych (bracket, brace). To jeden z
**najważniejszych etapów** — determinuje liczbę partii i strukturę partytury.

#### Podstawy teoretyczne

Detekcja pięciolinii jest jednym z najstarszych i najlepiej zbadanych
problemów OMR. Główne podejścia (Rebelo et al., 2012; Gallego &
Calvo-Zaragoza, 2017):

**a) Horizontal Projection Profile:**
- Sumowanie wartości pikseli w każdym wierszu → profile z wyraźnymi pikami
  w miejscach linii pięciolinii.
- Prosta, szybka, skuteczna dla drukowanych partytur.
- Stosowana w tym projekcie (StaffDetector).

**b) Hough Transform:**
- Wykrywanie prostych linii w przestrzeni parametrów (ρ, θ).
- Odporna na przerwy w liniach, ale wolniejsza.

**c) Morphological Operations:**
- Erozja z kernelem horyzontalnym → zachowanie tylko długich linii poziomych.
- Uzupełnienie horizontal projection.

**d) Deep Learning (segmentation):**
- U-Net lub selectional auto-encoders (Gallego & Calvo-Zaragoza, 2017;
  Castellanos et al., 2018) — segmentacja semantyczna: piksel → {staff_line,
  symbol, background}.
- Najlepsza jakość, ale wymaga danych treningowych.

#### Wejścia i wyjścia

```
Wejście:  Obraz strony (po preprocessingu)
Wyjście:  StaffLayout {
            staves: List[Staff],       # pozycje Y, grubość linii
            staff_groups: List[Group], # {type: bracket|brace, staff_indices}
            systems: List[System]      # grupowanie w systemy
          }
```

#### Algorytm grupowania (stosowany w projekcie)

1. **Horizontal projection** → znalezienie pików → klastrowanie 5 linii = 1 staff
2. **Odstępy między staffami** → jeśli < próg → ten sam system
3. **Bracket detection** → analiza lewego marginesu na obecność pionowej linii
   łączącej staffy (bracket chóralny: SA + TB)
4. **Brace detection** → klamra (łuk) w lewym marginesie łącząca dwie
   pięciolinie → grand staff (organy)

#### Metryki sukcesu etapu 4

| Metryka | Definicja | Próg akceptacji |
|---------|-----------|-----------------|
| Staff detection recall | % wykrytych pięciolinii vs. rzeczywista liczba | 100% — brak tolerancji na pominięcie |
| Staff detection precision | % poprawnych detekcji vs. wszystkie detekcje | 100% |
| Grupowanie bracket/brace | Poprawność identyfikacji grup | 100% — błąd daje złą strukturę partii |
| Poprawność systemu | Wszystkie staffy w systemie poprawnie zgrupowane | 100% |

#### Zagrożenia

| Zagrożenie | Wpływ | Mitygacja |
|------------|-------|-----------|
| Przerywane linie pięciolinii (częściowo usunięte przez preprocessing) | Wysoki | Łączenie fragmentów bliskiej pozycji Y |
| Bracket/brace niewidoczne lub zniszczone skanem | Wysoki | Heurystyki: zakładaj bracket jeśli 2 staffy w tym samym systemie mają ten sam klucz |
| Ozdobne elementy (ramki, grafiki) fałszywie wykryte jako pięciolinie | Średni | Filtrowanie: pięciolinia musi mieć min. 80% szerokości strony |
| Partytury z niestandardową liczbą linii (np. perkusja — 1 linia) | Niski | Konfigurowalny parametr: oczekiwana liczba linii na staff |

---

### 4.5 Etap 5 — Staff Splitting (wycinanie per pięciolinia)

#### Cel
Wycięcie z pełnego obrazu strony osobnych obrazów dla każdej pięciolinii
(lub grupy pięciolinii — grand staff), aby przekazać je osobno do silnika OMR.

To kluczowa decyzja architektoniczna: **OMR per staff zamiast OMR per page**
— zapobiega mieszaniu nut z różnych partii.

#### Uzasadnienie naukowe

Silniki OMR (szczególnie end-to-end jak homr/TrOMR) osiągają lepsze wyniki
na wyciętych fragmentach niż na pełnych stronach partytur orkiestrowych
(Calvo-Zaragoza et al., 2020). Modele trenowane na danych PrIMuS czy
DeepScores z reguły widzą pojedynczą pięciolinię, nie pełną stronę.

#### Strategia wycinania

| Typ partii | Strategia | Uzasadnienie |
|------------|-----------|-------------|
| Partia jednopięcioliniowa (SA, TB) | Wycinaj jedną pięciolinię + margines | Jedno wyjście OMR |
| Grand staff (Organo) | Wycinaj obie pięciolinie z klamrą razem | Zachowanie kontekstu harmonicznego |
| System wielostronicowy | Wycinaj cały system, ale przetwarzaj staffy osobno | Kontekst kresek taktowych |

#### Parametry wycinania

| Parametr | Wartość | Uzasadnienie |
|----------|---------|-------------|
| Margines górny | 50% interstaff distance | Miejsce na nuty powyżej pięciolinii |
| Margines dolny | 50% interstaff distance | Miejsce na nuty poniżej + lyrics |
| Margines boczny | 20px | Uniknięcie obcięcia bracket/clef |
| Overlap detection | Sprawdź, czy margines nie nakłada się na sąsiednią pięciolinię | Uniknięcie duplikowania nut |

#### Metryki sukcesu etapu 5

| Metryka | Definicja | Próg |
|---------|-----------|------|
| Kompletność wycinki | Wszystkie nuty i symbole danej pięciolinii widoczne w wycinku | 100% |
| Brak kontaminacji | Brak nut z sąsiedniej pięciolinii | 100% |
| Zachowanie kresek taktowych | Barlines widoczne na obu krańcach wycinki | > 95% |

#### Zagrożenia

| Zagrożenie | Wpływ | Mitygacja |
|------------|-------|-----------|
| Nuty o ekstremalnie wysokim/niskim pitchu wykraczające poza margines | Wysoki | Dynamiczny margines na podstawie skrajnych pozycji nut |
| Lyrics między pięcioliniami — przypisanie do właściwej | Średni | Analiza pozycji Y tekstu vs. pozycji staffu |
| Klamra (brace) obcięta przez wycinanie | Niski | Wycinaj grand staff razem |

---

### 4.6 Etap 6 — Music Object Detection & Recognition (silnik OMR)

#### Cel
Rozpoznanie symboli muzycznych na wyciętym obrazie pięciolinii i
przekształcenie ich w surową reprezentację muzyczną.

To jest rdzeń systemu OMR — etap, w którym obraz staje się muzyką.

#### Taksonomia podejść

Zgodnie z przeglądem Castellanos, Gallego & Fujinaga (2025, „Deep Learning
for Optical Music Recognition: A Review"):

**a) Podejście klasyczne (template matching + heurystyki):**
- Dopasowywanie wzorców symboli do regionów obrazu.
- Przykład: wczesny Audiveris, Gamera.
- Zalety: interpretowalność, brak potrzeby danych treningowych.
- Wady: kruchość na wariacje wizualne, wolna adaptacja.

**b) Podejście z detekcją obiektów (Object Detection):**
- Modele obiektowe: YOLO, Faster R-CNN, Detectron2.
- Dane treningowe: MUSCIMA++ (>90 000 anotacji, 23 352 nuty;
  Hajič Jr. & Pecina, 2017), DeepScores V2 (151M instancji, 135 klas;
  Tuggener et al., 2020), DoReMi (6 432 obrazów, ~1M obiektów;
  Shatri & Fazekas, 2021).
- Zalety: rozpoznawanie w jednym przebiegu, obsługa wielu symboli.
- Wady: wymagane duże dane treningowe, nie rozwiązuje semantyki muzycznej.

**c) Podejście end-to-end (Sequence-to-Sequence):**
- Model bezpośrednio mapuje obraz na sekwencję tokenów muzycznych.
- Przykłady: TrOMR (Transformer OMR) w homr, Camera-PrIMuS.
- Dane: PrIMuS (87 678 incipitów; Calvo-Zaragoza & Rizo, 2018).
- Zalety: brak potrzeby jawnej detekcji, obsługa kontekstu.
- Wady: trudne debugowanie, ograniczenie do monofonii (PrIMuS) lub
  prostej polifonii.

**d) Podejście hybrydowe (stosowane w tym projekcie):**
- Segmentacja semantyczna (U-Net) + detekcja (oemer) + transformer
  (Polyphonic-TrOMR) → cross-validation.
- homr łączy oemer's segmentation models z TrOMR transformer.

#### Silniki OMR dostępne w projekcie

| Silnik | Implementacja | Obsługa polifonii | Staff handling | Aktualność |
|--------|---------------|-------------------|----------------|------------|
| **homr** (główny) | Python, pip | Tak (TrOMR) | Grand staff → dobrze; single staff → barline issues | Aktywny (2026) |
| **Audiveris** (zapasowy) | Java, CLI | Pełna (multi-voice) | Cała strona | Aktywny (v5.9+) |
| **oemer** (fallback) | Python, pip | Ograniczona (2 tracks) | Single/piano staff | Ograniczona |

#### Wejścia i wyjścia

```
Wejście:  staff_image.png (wycięty obraz jednej pięciolinii / grand staff)
Wyjście:  OMRResult {
            musicxml_path: str,       # ścieżka do wygenerowanego MusicXML
            measures_detected: int,   # liczba wykrytych taktów
            staves_detected: int,     # pięciolinie w tym fragmencie
            clefs: List[str],         # wykryte klucze
            time_signature: str,      # wykryte metrum
            key_signature: str,       # wykryta tonacja
            voices: int,              # wykryte głosy
            confidence: float,        # pewność wyniku
            warnings: List[str]       # wykryte problemy
          }
```

#### Metryki sukcesu etapu 6

| Metryka | Definicja | Źródło | Próg akceptacji |
|---------|-----------|--------|-----------------|
| **Symbol Recognition Rate (SRR)** | % poprawnie rozpoznanych symboli | Byrd & Simonsen (2015) | > 95% |
| **Note Accuracy** | % nut z poprawnym pitch AND duration | Standard OMR | > 90% |
| **Measure Count Accuracy** | Wykryta liczba taktów vs. ground truth | — | 100% (krytyczne) |
| **Clef Accuracy** | Poprawność wykrytego klucza | — | 100% |
| **Time Signature Accuracy** | Poprawność metrum | — | 100% (wpływa na cały utwór) |
| **Barline Detection** | Poprawność pozycji kresek taktowych | — | 100% (krytyczne) |

**Znane problemy z homr w tym projekcie:**
- Źle rozpoznaje barlines na wyciętych pojedynczych pięcioliniach
  (SA: 2 takty zamiast 6, TB: 2 zamiast 6)
- Błędne time signature na kluczu basowym (5/4 zamiast 4/4)
- Brak voice separation w partiach wokalnych

#### Zagrożenia

| Zagrożenie | Prawdopodobieństwo | Wpływ | Mitygacja |
|------------|-------------------|-------|-----------|
| Błędna detekcja barlines → zła liczba taktów | Wysokie (znany problem) | Krytyczny | Kontekstowa korekta: porównanie barlines OMR z OpenCV-detected barlines |
| Pomylenie klucza (G2 vs. F4) | Niskie | Krytyczny | Cross-check z pozycjami nut — jeśli nuty B0-D3 → prawdopodobny klucz basowy |
| Brakujące nuty (pominięcie) | Średnie | Wysoki | Porównanie czasu trwania taktów vs. metrum → wykrywanie luk |
| Fałszywe nuty (halucynacja) | Niskie | Wysoki | Sprawdzanie ambitusu per instrument |
| Błędne duracje nut | Średnie | Wysoki | Walidacja beatów w takcie |

---

### 4.7 Etap 7 — Score Assembly (budowanie partytury)

#### Cel
Złożenie wyników OMR z poszczególnych pięciolinii w kompletny, wieloczęściowy
dokument MusicXML z poprawnymi partiami, głosami, metadanymi i grupowaniem.

To jest **najtrudniejszy etap implementacyjny** — wymaga złączenia danych
z etapów 3, 4 i 6 w spójną reprezentację muzyczną (odpowiednik etapu D
w frameworku Calvo-Zaragozy et al.: „Recover Musical Semantics").

#### Kluczowe decyzje architektoniczne

1. **ElementTree zamiast music21 do budowania XML** — music21 automatycznie
   reorganizuje strukturę (np. dzieli grand staff na dwa PartStaff), co
   uniemożliwia precyzyjną kontrolę nad `<backup>`, `<forward>`, `<voice>`,
   `<staff>`. ElementTree daje pełną kontrolę.

2. **DIVISIONS = 4** — stała definiująca jednostki duracji na ćwierćnutę
   w MusicXML. Wartość 1 powoduje utratę precyzji dla nut krótszych
   niż ćwierćnuta. Wartość 4 pozwala na szesnastkę.

3. **Voice numbering convention:**
   - Partia SA: voice 1 (Sopran), voice 2 (Alt)
   - Partia TB: voice 1 (Tenor), voice 2 (Bas)
   - Organo staff 1 (treble): voice 1, 2, 3
   - Organo staff 2 (bass): voice 5, 6, 7

4. **Backup mechanism** — w organowym grand staff, po zapisaniu nut
   staff 1, `<backup>` wraca do początku taktu, następnie nuty staff 2.

#### Wejścia i wyjścia

```
Wejścia:
  - OMRResult[] z etapu 6 (per staff)
  - StaffLayout z etapu 4 (grupy, systemy)
  - ClassifiedText z etapu 3 (metadane)

Wyjście:
  - Kompletny plik MusicXML z:
    - <part-list> z grupowaniem (bracket, brace)
    - <part> per partia z miarami, głosami, nutami
    - Metadane: tytuł, kompozytor, tonacja, metrum, tempo
```

#### Algorytm assembly

```
1. Wyznacz partie (PartDefinition[]) z StaffLayout.groups + ClassifiedText.part_names
2. Zbuduj <part-list> z grupowaniem bracket/brace
3. Dla każdej partii:
   a. Pobierz odpowiedni OMRResult
   b. Parsuj MusicXML silnika OMR
   c. Ekstrahuj nuty, pauzy, duracje
   d. Dla grand staff: dodaj <backup> między staffami
   e. Voice separation: greedy interval scheduling
4. Dodaj metadane globalne (tytuł, tonacja, metrum, tempo)
5. Detekcja anacrusis: jeśli m.1 < pełne metrum → numer = 0, implicit = yes
6. Multi-page assembly: łącz takty z kolejnych stron
```

#### Metryki sukcesu etapu 7

| Metryka | Definicja | Próg |
|---------|-----------|------|
| Poprawność struktury partii | Liczba i nazwy partii vs. ground truth | 100% |
| Poprawność grupowania | Bracket/brace zgodne z ground truth | 100% |
| Poprawność voice assignment | Głosy poprawnie przypisane | > 95% |
| Beat count per measure | Suma duracji w takcie = time signature | 100% (walidowane w etapie 9) |
| Multi-page continuity | Takty z kolejnych stron poprawnie połączone | 100% |

#### Zagrożenia

| Zagrożenie | Wpływ | Mitygacja |
|------------|-------|-----------|
| OMR zwraca różną liczbę taktów per staff | Krytyczny | Wyrównanie na podstawie barline positions |
| Brak rozpoznania voice separation (SA → single voice) | Wysoki | Post-hoc separation: pitch + stem direction |
| Niezgodna tonacja/metrum między partami | Średni | Ujednolicenie na podstawie majority vote |
| Grand staff z niesymetrycznymi taktami | Wysoki | Wyrównanie duracji z backup/forward |

---

### 4.8 Etap 8 — Lyrics Alignment (przypisanie tekstu)

#### Cel
Przypisanie wyekstrahowanych sylab tekstu pieśni do odpowiednich nut
w partiach wokalnych.

#### Zasady alignmentu sylab

Zgodnie ze standardem MusicXML (W3C Music Notation Community Group):

```xml
<lyric number="1">
  <syllabic>begin</syllabic>    <!-- początek słowa -->
  <text>Al</text>
</lyric>
```

| Typ sylaby | Wartość `<syllabic>` | Przykład |
|------------|---------------------|---------|
| Jednosylabowe słowo | `single` | „i", „z", „na" |
| Początek słowa | `begin` | „Al-" (z Alleluja) |
| Środek słowa | `middle` | „-le-" |
| Koniec słowa | `end` | „-ja" |

#### Strategia alignmentu

1. Wykryj partie wokalne (PartDefinition.is_vocal = True)
2. Usuń z lyrics wszelkie niebędące tekstem pieśni elementy
   (nazwy partii, copyright, oznaczenia)
3. Podziel tekst na sylaby (na podstawie łączników `-`)
4. Iteruj po nutach wokalnych w kolejności czasowej
5. Przypisz syllabę do każdej nuty (pauzy pomijane)
6. Specjalny przypadek: recto tono — cały tekst pod jedną nutę recytowaną

#### Metryki sukcesu etapu 8

| Metryka | Definicja | Próg |
|---------|-----------|------|
| Poprawność syllabic | Właściwy typ begin/middle/end/single | > 98% |
| Kompletność | Wszystkie sylaby przypisane | 100% |
| Poprawność alignmentu | Sylaba pod właściwą nutą | > 90% |

---

### 4.9 Etap 9 — Semantic Validation & Post-processing (walidacja i korekta)

#### Cel
Weryfikacja poprawności muzycznej wygenerowanego MusicXML i automatyczna
korekta wykrytych błędów.

#### Reguły walidacji

**a) Beat count validation (offset-based):**
- Dla każdego taktu: suma duracji nut i pauz w każdym głosie = wartość metrum.
- Metoda: śledzenie offsetów per voice (nie naiwna suma, bo to daje
  podwójne liczenie w wielogłosie).
- Korekta: jeśli brakuje beatów → dodaj resty; jeśli nadmiar → oznacz
  jako warning.

**b) Ambitus validation:**
- Sprawdź zakres wysokości dźwięków per partia.
- Typowe zakresy:

| Partia | Zakres | MIDI range |
|--------|--------|------------|
| Sopran | C4 – C6 | 60 – 84 |
| Alt | F3 – F5 | 53 – 77 |
| Tenor | C3 – C5 | 48 – 72 |
| Bas | E2 – E4 | 40 – 64 |
| Organo (treble) | C3 – C6 | 48 – 84 |
| Organo (bass) | C2 – C4 | 36 – 60 |

- Nuty poza zakresem → warning (nie auto-korekta, bo mogą być celowe).

**c) Key signature validation:**
- Analiza częstotliwości nut → porównanie z zadeklarowaną tonacją.
- Metoda: algorytm Krumhansla-Schmucklera (implementacja music21).

**d) Consistency validation:**
- Wszystkie partie mają tę samą liczbę taktów.
- Metrum zgodne we wszystkich partiach.
- Key signature spójna.

#### Potencjał zastosowania LLM

W przyszłych iteracjach walidację semantyczną można wzmocnić modelem
językowym (LLM), np. Claude Opus lub GPT-4, do:

- Wykrywania błędów rytmicznych w kontekście frazy muzycznej
- Korekty tonacji na podstawie kontekstu harmonicznego
- Uzupełniania brakujących elementów (np. brakująca nuta w symetrycznej frazie)
- Weryfikacji prawidłowości prowadzenia głosów

Podejście LLM wymaga przemyślanego promptingu z kontekstem muzycznym.
LLM nie zastąpi walidacji regułowej, ale może uzupełniać semantykę.

#### Metryki sukcesu etapu 9

| Metryka | Definicja | Próg |
|---------|-----------|------|
| Beat count errors | Takty z niepoprawną liczbą beatów po auto-korekcie | 0 |
| Ambitus violations | Nuty poza tolerowanym zakresem | < 5% (raportowane jako warnings) |
| Key consistency | Nuty poza tonacją / łączna liczba nut | < 15% (muzyka kościelna jest w dużej mierze diatoniczna) |
| Part length consistency | Różnica w liczbie taktów między partiami | 0 |

#### Zagrożenia

| Zagrożenie | Wpływ | Mitygacja |
|------------|-------|-----------|
| Auto-korekta „naprawia" poprawne nuty | Średni | Minimalizuj interwencje — tylko dodawaj resty, nie usuwaj nut |
| LLM halucynuje nuty | Wysoki | LLM tylko do diagnostyki, nie do modyfikacji XML |
| Brak ground truth do walidacji | Średni | Budowa zbioru testowego (ground truth MusicXML) |

---

### 4.10 Etap 10 — Output & Human-in-the-Loop

#### Cel
Eksport finalnego pliku MusicXML oraz umożliwienie użytkownikowi manualnej
korekty wyników OMR.

#### Uzasadnienie

OMR **nie osiąga 100% accuracy** — nawet najlepsze systemy komercyjne
przyznają się do potrzeby ręcznej weryfikacji (Calvo-Zaragoza et al., 2020).
W kontekście muzyki kościelnej z recto tono, nieliniowym layoutem i polskim
tekstem, potrzeba korekty ludzkiej jest jeszcze większa.

#### Workflow korekty

```
1. Pipeline generuje MusicXML → data/processed/<nazwa>_final.musicxml
2. Użytkownik otwiera plik w MuseScore
3. Wizualna weryfikacja: porównanie z oryginałem PDF
4. Korekta w MuseScore: nuty, duracje, tekst, klucze
5. Zapis poprawionego pliku jako ground truth
6. (Przyszłość) System uczy się z korekt → active learning
```

#### Narzędzia do korekty

| Narzędzie | Typ | Zastosowanie |
|-----------|-----|-------------|
| **MuseScore** (desktop) | Edytor | Pełna korekta wizualna i muzyczna |
| **Streamlit UI** (web) | Przeglądarka | Podgląd metadanych, upload, trigger pipeline |
| **VexFlow** (web, przyszłość) | Renderer | Wyświetlanie MusicXML w przeglądarce |

---

## 5. Walidacja end-to-end — porównanie z ground truth

### 5.1 Filozofia walidacji

Każdy etap pipeline'u powinien mieć **walidację wewnętrzną** (sprawdzenie
poprawności wyjścia etapu) oraz **walidację end-to-end** (porównanie finalnego
wyniku z referencyjnym MusicXML).

### 5.2 Metryki end-to-end

Zgodnie z propozycjami Byrda & Simonsena (2015) „Towards a Standard Testbed
for Optical Music Recognition" oraz praktyką stosowaną w literaturze:

| Metryka | Definicja | Granularność | Interpretacja |
|---------|-----------|-------------|---------------|
| **Pitch Accuracy** | % nut z poprawną wysokością dźwięku | Nuta | Fundamentalna — błąd pitch = zła muzyka |
| **Duration Accuracy** | % nut z poprawną wartością rytmiczną | Nuta | Krytyczna — błąd duracji = zły rytm |
| **Note Accuracy** | % nut z poprawnym pitch AND duration AND voice | Nuta | Złożona — łączy powyższe |
| **Measure Accuracy** | % taktów identycznych z ground truth | Takt | Wysoki poziom — cały takt poprawny |
| **Part Accuracy** | Poprawna liczba i nazwy partii | Dokument | Strukturalna |
| **Symbol Error Rate (SER)** | Edit distance na poziomie symboli | Dokument | Analogiczna do WER w speech recognition |
| **MusicXML Edit Distance** | Levenshtein distance na tokenizacji MusicXML | Dokument | Ilość potrzebnych korekt |

### 5.3 Procedura ewaluacji

```python
# Pseudokod porównania wynik OMR vs. ground truth
import music21

expected = music21.converter.parse('ground_truth.musicxml')
actual = music21.converter.parse('omr_output.musicxml')

# Porównanie strukturalne
assert len(expected.parts) == len(actual.parts), "Part count mismatch"

for i, (e_part, a_part) in enumerate(zip(expected.parts, actual.parts)):
    e_measures = list(e_part.getElementsByClass('Measure'))
    a_measures = list(a_part.getElementsByClass('Measure'))
    assert len(e_measures) == len(a_measures), f"Measure count mismatch in part {i}"
    
    for j, (e_meas, a_meas) in enumerate(zip(e_measures, a_measures)):
        e_notes = list(e_meas.notes)
        a_notes = list(a_meas.notes)
        # Porównanie pitch, duration, voice per note
```

### 5.4 Zbiór testowy (ground truth)

| Plik testowy | Opis | Partie | Trudność |
|-------------|------|--------|----------|
| `Alleluja_-_werset_sw_Anna` | SATB + Organo, recto tono, 1 strona | 3 (SA, TB, Org) | Średnia |
| `do Jana Kantego` | SATB + Organo, 2 strony | 3+ | Wysoka (multi-page) |
| `psalm_adwent` | Psalm, format psalmodyczny | Zmienny | Wysoka (recto tono) |

---

## 6. Datasety referencyjne OMR

Dla celów ewaluacji, trenowania modeli i benchmarkingu — przegląd
kluczowych datasetów w dziedzinie OMR (wg Pacha, OMR-Datasets):

| Dataset | Typ | Rozmiar | Formaty | Zastosowanie |
|---------|-----|---------|---------|-------------|
| **MUSCIMA++** | Ręczne | 91 255 symboli | Obrazy, MuNG | Detekcja obiektów, klasyfikacja symboli |
| **DeepScores V2** | Drukowane | 255 385 obrazów, 151M instancji | Obrazy, XML | Detekcja, segmentacja, klasyfikacja |
| **DoReMi** | Drukowane | 6 432 obrazów, ~1M obiektów | Obrazy, MusicXML, XML | Pełny pipeline OMR |
| **PrIMuS** | Drukowane | 87 678 incipitów | Obrazy, MEI, agnostic | End-to-end monophonic OMR |
| **CVC-MUSCIMA** | Ręczne | 1 000 obrazów | Obrazy | Staff removal, writer ID |
| **OpenScore Lieder** | Drukowane | 1 356 plików | MuseScore | Ewaluacja, ground truth |
| **HOMUS** | Ręczne (online) | 15 200 symboli | Strokes | Klasyfikacja symboli |
| **Rebelo Dataset** | Drukowane | 15 000 symboli | Obrazy | Klasyfikacja symboli |
| **Byrd Dataset** | Drukowane | 34 obrazy | Obrazy | Benchmark trudności |

---

## 7. Zagrożenia systemowe i mitygacje

### 7.1 Zagrożenia architektoniczne

| Zagrożenie | Opis | Prawdop. | Wpływ | Mitygacja |
|------------|------|----------|-------|-----------|
| **Kaskadowa propagacja błędów** | Błąd w etapie N niszczy wyniki etapów N+1...K | Wysokie | Krytyczny | Walidacja po każdym etapie, early stopping |
| **Vendor lock-in na silnik OMR** | homr przestaje być rozwijany lub wprowadza breaking changes | Średnie | Wysoki | Abstrakcja OMREngine, zapasowy Audiveris |
| **Overfitting na test cases** | Pipeline zoptymalizowany pod kilka plików testowych | Wysokie | Wysoki | Dywersyfikacja zbioru testowego, cross-validation |
| **Złożoność debugowania** | Pipeline wieloetapowy utrudnia izolację błędów | Wysokie | Średni | Logowanie per etap, generowanie raportów pośrednich |

### 7.2 Zagrożenia jakościowe

| Zagrożenie | Opis | Mitygacja |
|------------|------|-----------|
| **Niska jakość skanów** | Stare, pożółkłe, słabo czytelne partytury | Preprocessing adaptacyjny, fallback na ręczne wprowadzanie |
| **Nuty ręcznie pisane** | Zupełnie inna domena niż druk | Poza zakresem MVP — przyszły rozwój z MUSCIMA++ |
| **Niestandardowa notacja** | Recto tono, neuma, notacja mensuralna | Specyficzne heurystyki dla muzyki kościelnej |
| **Wielojęzyczność tekstu** | Łacina + polski w tym samym utworze | Konfiguracja języka per utwór |
| **Wielostronicowe partytury** | Assembly taktów między stronami | Multi-page assembly z wyrównaniem barlines |

### 7.3 Zagrożenia technologiczne

| Zagrożenie | Opis | Mitygacja |
|------------|------|-----------|
| **Zależność od GPU** | Modele DL (homr) wymagają GPU | CPU fallback w homr, Audiveris (Java) nie wymaga GPU |
| **Kompatybilność MusicXML** | Różne silniki produkują różne dialekty MusicXML | Normalizacja przez music21 |
| **Rozmiar modeli DL** | Modele homr/oemer > 500 MB | Docker image z pre-loaded models |

---

## 8. Stack technologiczny

| Warstwa | Technologia | Rola w pipeline |
|---------|-------------|-----------------|
| **Ingestion** | PyMuPDF (fitz) | PDF → images, text extraction |
| **Preprocessing** | OpenCV, scikit-image | Binaryzacja, deskew, denoising |
| **Staff Detection** | OpenCV (horizontal projection) | Detekcja pięciolinii |
| **OMR Primary** | homr (Polyphonic-TrOMR) | End-to-end per-staff recognition |
| **OMR Secondary** | Audiveris (Java CLI) | Zapasowy silnik OMR |
| **Score Assembly** | ElementTree (lxml) | Budowanie MusicXML XML |
| **Validation** | music21 | Analiza muzyczna, walidacja beat count |
| **Lyrics** | music21 | Alignment sylab do nut |
| **UI** | Streamlit | Frontend webowy |
| **Baza danych** | SQLAlchemy + SQLite | Katalog utworów z metadanymi |
| **Konteneryzacja** | Docker | Powtarzalne środowisko |

---

## 9. Roadmap implementacji

### Faza 1 — Poprawa jakości OMR (priorytet krytyczny)

| # | Zadanie | Etap pipeline | Status |
|---|---------|--------------|--------|
| 1.1 | Alternatywny silnik OMR (Audiveris) | Etap 6 | Planowane |
| 1.2 | Kontekstowa korekta barlines (OpenCV vs. OMR) | Etap 6/9 | Planowane |
| 1.3 | Multi-page assembly | Etap 7 | Planowane |
| 1.4 | Voice separation w partiach SATB | Etap 7 | Planowane |

### Faza 2 — Refaktoring i testy (priorytet ważny)

| # | Zadanie | Etap pipeline | Status |
|---|---------|--------------|--------|
| 2.1 | Usunięcie legacy modules | Cały projekt | Planowane |
| 2.2 | Unit testy nowych modułów | Walidacja | Planowane |
| 2.3 | Ground truth evaluation framework | Walidacja | Planowane |
| 2.4 | Lint cleanup | Jakość kodu | Planowane |

### Faza 3 — Nowe funkcjonalności

| # | Zadanie | Etap pipeline | Status |
|---|---------|--------------|--------|
| 3.1 | Integracja pipeline z Streamlit UI | Etap 10 | Planowane |
| 3.2 | Batch processing | Etap 1 | Planowane |
| 3.3 | Recto tono detection | Etap 9 | Planowane |
| 3.4 | LLM semantic validation | Etap 9 | Eksperymentalne |

---

## 10. Bibliografia

Prace cytowane w tym dokumencie, uporządkowane chronologicznie:

1. **Bainbridge, D.; Bell, T.** (2001). „The Challenge of Optical Music
   Recognition." *Computers and the Humanities*, 35(2), 95–121.
   DOI: 10.1023/A:1002485918032

2. **Bellini, P.; Bruno, I.; Nesi, P.** (2008). „Optical Music Recognition:
   Architecture and Algorithms." *Interactive Multimedia Music Technologies*,
   IGI Global.

3. **Rebelo, A.; Fujinaga, I.; Paszkiewicz, F.; Marçal, A.R.S.; Guedes, C.;
   Cardoso, J.S.** (2012). „Optical Music Recognition: State-of-the-Art and
   Open Issues." *International Journal of Multimedia Information Retrieval*,
   1(3), 173–190. DOI: 10.1007/s13735-012-0004-6

4. **Byrd, D.; Simonsen, J.G.** (2015). „Towards a Standard Testbed for
   Optical Music Recognition: Definitions, Metrics, and Page Images."
   *Journal of New Music Research*, 44(3), 169–195.
   DOI: 10.1080/09298215.2015.1045424

5. **Novotný, J.; Pokorný, J.** (2015). „Introduction to Optical Music
   Recognition: Overview and Practical Challenges." *DATESO*, CEUR-WS.

6. **Gallego, A.J.; Calvo-Zaragoza, J.** (2017). „Staff-Line Removal with
   Selectional Auto-Encoders." *Expert Systems with Applications*, 89, 138–148.
   DOI: 10.1016/j.eswa.2017.07.002

7. **van der Wel, E.; Ullrich, K.** (2017). „Optical Music Recognition with
   Convolutional Sequence-to-Sequence Models." *ISMIR 2017*, Suzhou, China.

8. **Hajič Jr., J.; Pecina, P.** (2017). „The MUSCIMA++ Dataset for
   Handwritten Optical Music Recognition." *ICDAR 2017*, Kyoto, 39–46.
   DOI: 10.1109/ICDAR.2017.16

9. **Calvo-Zaragoza, J.; Rizo, D.** (2018). „End-to-End Neural Optical Music
   Recognition of Monophonic Scores." *Applied Sciences*, 8(4), 606.
   DOI: 10.3390/app8040606

10. **Castellanos, F.J.; Calvo-Zaragoza, J.; Vigliensoni, G.; Fujinaga, I.**
    (2018). „Document Analysis of Music Score Images with Selectional
    Auto-Encoders." *ISMIR 2018*, Paris, 256–263.

11. **Tuggener, L.; Elezi, I.; Schmidhuber, J.; Stadelmann, T.** (2018).
    „Deep Watershed Detector for Music Object Recognition." *ISMIR 2018*,
    Paris, 271–278.

12. **Pacha, A.; Calvo-Zaragoza, J.; Hajič Jr., J.** (2019). „Learning
    Notation Graph Construction for Full-Pipeline Optical Music Recognition."
    *ISMIR 2019*.

13. **Baró, A.; Riba, P.; Calvo-Zaragoza, J.; Fornés, A.** (2019). „From
    Optical Music Recognition to Handwritten Music Recognition: A Baseline."
    *Pattern Recognition Letters*, 123, 1–8.
    DOI: 10.1016/j.patrec.2019.02.029

14. **Pacha, A.** (2019). *Self-Learning Optical Music Recognition* (PhD
    thesis). TU Wien. DOI: 10.13140/RG.2.2.18467.40484

15. **Calvo-Zaragoza, J.; Hajič Jr., J.; Pacha, A.** (2020). „Understanding
    Optical Music Recognition." *ACM Computing Surveys*, 53(4), 1–35.
    arXiv: 1908.03608. DOI: 10.1145/3397499

16. **Shatri, E.; Fazekas, G.** (2020). „Optical Music Recognition: State of
    the Art and Major Challenges." *arXiv preprint arXiv:2006.07885*.

17. **Tuggener, L.; Satyawan, Y.P.; Pacha, A.; Schmidhuber, J.; Stadelmann,
    T.** (2020). „The DeepScoresV2 Dataset and Benchmark for Music Object
    Detection." *ICPR 2020*, Milan.

18. **Shatri, E.; Fazekas, G.** (2021). „DoReMi: First Glance at a Universal
    OMR Dataset." *WoRMS 2021*. arXiv: 2107.07786.

19. **Ríos-Vila, A.** (2021). „Development of a Complete Optical Music
    Recognition Workflow." Master thesis, University of Alicante.

20. **Calvo-Zaragoza, J.; Martinez-Sevilla, J.C.** (2023). „Optical Music
    Recognition: Recent Advances, Current Challenges, and Future Directions."
    *Graphics Recognition (GREC 2023)*, Springer LNCS.

21. **Castellanos, F.J.; Gallego, A.J.; Fujinaga, I.** (2025). „Deep Learning
    for Optical Music Recognition: A Review." *Authorea Preprints*.

### Datasety — publikacje

22. **Fornés, A.; Dutta, A.; Gordo, A.; Lladós, J.** (2012). „CVC-MUSCIMA:
    A Ground-Truth of Handwritten Music Score Images." *IJDAR*, 15(3), 243–251.

23. **Calvo-Zaragoza, J.; Oncina, J.** (2014). „Recognition of Pen-Based
    Music Notation: The HOMUS Dataset." *ICPR 2014*, 3038–3043.

24. **Pacha, A.; Eidenberger, H.** (2017). „Towards a Universal Music Symbol
    Classifier." *ICDAR 2017*, Kyoto, 35–36.

25. **Tuggener, L.; Elezi, I.; Schmidhuber, J.; Pelillo, M.; Stadelmann, T.**
    (2018). „DeepScores – A Dataset for Segmentation, Detection and
    Classification of Tiny Objects." *ICPR 2018*, Beijing.

### Zasoby online

26. **Pacha, A.** OMR Datasets — https://apacha.github.io/OMR-Datasets/
27. **OMR Research Bibliography** — https://omr-research.github.io/
28. **MusicXML Specification** — https://www.w3.org/2021/06/musicxml40/
29. **Audiveris** — https://github.com/Audiveris/audiveris
30. **homr** — https://github.com/BreezeWhite/oemer (oemer/homr ecosystem)

---

*Dokument opracowany na podstawie przeglądu literatury naukowej OMR
oraz doświadczeń z implementacji pipeline'u w projekcie Church Music Organizer.*
