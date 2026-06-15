# Roadmapa i strategia produktu — Church Music Organizer

> Dokument strategiczny. Łączy wizję produktu, szczerą ocenę rynku, flagowe wyróżniki,
> fazową roadmapę i wartość biznesową. Aktualizowany 2026-06-15.

---

## 1. Wizja

**Docelowo: inteligentny asystent dyrygenta chóralnego i kompozytora** — środowisko pracy, które
prowadzi materiał muzyczny od skanu/PDF/szkicu, przez wiarygodną transkrypcję i edycję, po
gotowe do próby i wykonania głosy, tłumaczenia i analizy.

Nie budujemy „kolejnego OMR". Transkrypcja AI jest **silnikiem zasilającym**, a nie produktem.
Produktem jest **praca z muzyką**: poprawny wielogłosowy tekst, śpiewalne tłumaczenia, analiza
pod możliwości konkretnego zespołu i uporządkowana, przeszukiwalna biblioteka repertuaru.

Trzy zasady przewodnie:
1. **Człowiek w pętli, nie czarna skrzynka.** AI proponuje i oznacza niepewność; decyduje muzyk.
   (Lekcja z PhotoScore — sekcja 4.)
2. **Wielojęzyczność, nie tylko PL/łacina.** Repertuar chóralny jest globalny (niem., ang.,
   franc., cerkiewno-słowiański, hiszp.). Domena sakralna to punkt startu i głębia, nie klatka.
3. **Wartość per zespół.** Wszystko (trudność, zakresy, transpozycja, tłumaczenie) liczone pod
   *ten* chór, nie pod abstrakcyjną maszynę.

Kolejność rozwoju (decyzja właściciela, 2026-06-15):
**(P-now) AI edytor — jakość transkrypcji/analizy** → biblioteka repertuaru + liturgia →
próby/wykonania (głosy, transpozycje, nagrania).

---

## 2. Szczera ocena rynku i różnicowanie

### 2.1. Czego NIE warto budować
Sam łańcuch **skan → MusicXML** to rynek dojrzały i zatłoczony:

| Narzędzie | Czym jest | Dlaczego trudno wygrać |
|-----------|-----------|------------------------|
| **PhotoScore / NotateMe (Neuratron)** | komercyjny OMR + edytor korekty | wieloletni silnik, świetna pętla korekty |
| **SmartScore (Musitek)** | komercyjny OMR | dojrzały |
| **Audiveris** | open-source OMR (używamy go!) | darmowy; jesteśmy jego *nakładką* |
| **Soundslice / ScanScore / PlayScore** | skan + odtwarzanie | dopracowane mobilne UX |
| **MuseScore / Dorico / Finale / Sibelius** | edycja i grawerka | standard rynkowy |

**Wniosek:** generyczny „wgraj skan → dostań nuty" stawia nas w roli gorszego Audiverisa. Eval
(`data/processed/eval/REPORT.md`) potwierdza: na czystych PDF surowy Audiveris ma recall ~1.0,
a korekta LLM dokłada tam *prawie nic*. Wartości trzeba szukać **wyżej w łańcuchu**.

### 2.2. Czego realnie brakuje na rynku (luki = nasza szansa)
Po przeglądzie narzędzi — to są bóle, których **nikt nie rozwiązuje dobrze** dla chórów:

1. **Śpiewalne tłumaczenie pod melodię.** Tłumacze maszynowi dają prozę; programy nutowe nie
   tłumaczą wcale. Chór śpiewający łaciński motet po polsku/angielsku albo niemiecki utwór po
   polsku musi to robić ręcznie, godzinami. **Tu nie ma konkurencji.** (Sekcja 3.1 — flagowiec.)
2. **Zaufanie do OMR.** OMR traktowany jako „auto-magia" zawodzi na realnych skanach; brakuje
   *szybkiej pętli korekty z mapą pewności*. PhotoScore to ma — większość darmowych nie. (3.2)
3. **Wielogłosowy podkład tekstu (SATB).** OMR-y gubią tekst; ręczne podłożenie 4 głosów to
   godziny. Mamy to już w kroku 5 (per-głos). (3.3)
4. **Analiza pod realny zespół.** Zakresy/tessitura głosów, ocena trudności dla amatorów,
   divisi, sugestia transpozycji „pod nasz chór". Edytory tego nie liczą domenowo. (3.4)
5. **Biblioteka zorientowana liturgicznie/repertuarowo.** Planowanie pod rok kościelny, okazję,
   historię wykonań. OMR-y nie mają biblioteki w ogóle. (3.5)
6. **Diction/wymowa** (IPA, łacina kościelna vs klasyczna, transliteracje) — chóry tracą czas
   prób na dykcję; nikt nie generuje ściąg wymowy z partytury. (faza dalsza)

### 2.3. Pozycjonowanie jednym zdaniem
> „Asystent dyrygenta i kompozytora: zamienia skany w uporządkowaną, przeszukiwalną bibliotekę
> z poprawnym tekstem pod nutami, **śpiewalnym tłumaczeniem** i analizą pod możliwości Twojego
> zespołu — z człowiekiem decydującym na każdym kroku."

---

## 3. Flagowe wyróżniki (gdzie budujemy przewagę)

### 3.1. Silnik śpiewalnego tłumaczenia (FLAGOWIEC) 🎯
Najmocniejszy, najtrudniejszy do skopiowania wyróżnik. Dziś `translator.py` daje tłumaczenie
prozą (PL). Cel: **tłumaczenie, które da się ZAŚPIEWAĆ pod istniejącą linią melodyczną** —
i to między dowolnymi językami, nie tylko na polski.

Na czym polega trudność (i dlaczego to wartość):
- **Liczba sylab = liczba nut** w danej frazie (z poszanowaniem melizmatów — jedna sylaba na
  wiele nut). Mamy już dokładnie te dane: krok 5 (`lyric_underlayer`) liczy onsety i melizmaty
  per głos — silnik tłumaczenia może je współdzielić.
- **Akcent prozodyczny** musi padać na mocne części taktu / dłuższe nuty (stres-mapping).
- **Sens + rejestr** (sakralny, liturgiczny) zachowany; opcjonalnie **rym** i zachowanie
  kluczowych słów (np. „Alleluja", „Sanctus" zostają).
- **Wielojęzyczność**: źródło i cel dowolne (la→pl, de→pl, la→en, en→pl…). Język wykrywany
  automatycznie (mamy detekcję w kroku 2).

Architektura (iteracyjnie):
- v1: tłumaczenie z **twardym ograniczeniem liczby sylab per fraza** + raport rozbieżności
  (gdzie nie dało się zmieścić — do ręcznej decyzji). Wynik wpinany jako druga warstwa `<lyric>`
  (number=2) obok oryginału — chór widzi oba.
- v2: dopasowanie akcentów do metrum (wykorzystać analizę metryczną z `score_analyzer`).
- v3: warianty (dosłowny / śpiewalny / rymowany) do wyboru; pętla korekty z człowiekiem.
- Reużycie: onsety/melizmaty z kroku 5, detekcja języka z kroku 2, walidacja music21.

### 3.2. Korekta z człowiekiem w pętli + mapa pewności
Pozycjonujemy OMR/LLM jako **draft + asystenta oznaczającego niepewność**, nie jako automat.
(Szczegóły i lekcje z PhotoScore — sekcja 4.)

### 3.3. Wielogłosowy podkład tekstu (SATB) — JEST
Krok 5 podkłada tekst per głos. Do dopracowania: jakość dopasowania na realnym repertuarze,
melizmaty, powtórzenia strof, divisi.

### 3.4. Analiza pod chór — do pogłębienia
Rozszerzyć `score_analyzer`/`score_descriptor`: zakresy i tessitura per głos, ocena trudności
dla amatorów, wykrycie divisi, **rekomendacja transpozycji** pod zadeklarowane możliwości zespołu.

### 3.5. Biblioteka liturgiczno-repertuarowa — szkielet JEST
Model ma `occasion`, `liturgical_season`, `UsageHistory`. Do zbudowania: kalendarz roku
kościelnego, planer zestawów, statystyki, wyszukiwanie domenowe.

---

## 4. Lekcje z PhotoScore — od czarnej skrzynki do edytora z człowiekiem w pętli

PhotoScore jest dojrzały nie dlatego, że jego OMR jest „magiczny", lecz dlatego, że **dobrze
prowadzi człowieka przez korektę**. To rozwiązuje nasz obecny problem (Audiveris pada na
złożonych skanach, LLM nie jest godzien ślepego zaufania). Co adaptujemy:

1. **Mapa pewności.** Oznaczać kolorem nuty/takty/sylaby o niskiej pewności (confidence z OCR/OMR
   i „niepewność" z agentów LLM) — kierować wzrok korektora tam, gdzie trzeba. Mamy już
   `ocr_confidence` i raporty kroków; trzeba je wyeksponować w UI.
2. **Widok źródło ↔ wynik obok siebie**, zsynchronizowany (skan vs. wyrenderowana partytura),
   żeby weryfikacja była szybka.
3. **Szybka, klawiaturowa pętla korekty** — poprawki w kilku kliknięciach, nie przez edycję XML.
4. **OMR jako draft, nie finał.** Komunikat produktu: „przygotujemy 90%, Ty zatwierdzasz" —
   zarządza oczekiwaniami i buduje zaufanie. Krok 4 (LLM) ma *proponować i oznaczać*, a nie po
   cichu nadpisywać (spójne z naszą zasadą „tylko puste pola" w metadanych).
5. **Solidny preprocessing realnych skanów.** PhotoScore radzi sobie z brudnymi skanami; my mamy
   usuwanie pięciolinii — dołożyć deskew/despeckle/normalizację (`sheet_music_ocr.py`), bo realne
   skany parafialne to nasz docelowy materiał, nie czyste PDF.
6. **Uczenie się z korekt** (dalej): zapamiętywać częste poprawki użytkownika i sugerować je.

> Skrót strategii: **nie ścigamy PhotoScore na dokładności silnika OMR** — przejmujemy jego
> *filozofię pętli korekty* i wygrywamy wyżej (tłumaczenie, analiza, biblioteka, domena).

---

## 5. Roadmapa fazowa

### Faza 1 — AI edytor partytur (TERAZ → najbliższe iteracje)
Cel: **zaufanie do wyniku**. Zakres:
- **A1. Chunking kroku 4** (`score_corrector.py`) — całość w prompcie ucina się na SATB; dzielić
  po taktach/systemach (jak w kroku 5).
- **A2. Warunkowa korekta** — krok 4 tylko gdy `note_recall < 0.95` / takty przepełnione
  (oszczędność budżetu; dowód: eval).
- **A3. Pętla korekty + mapa pewności w UI** (sekcja 4, pkt 1–4) — największy skok zaufania.
- **A4. Preprocessing realnych skanów** + zestaw ground-truth z brudnych skanów (nie tylko PDF).
- **A5. Pogłębiona analiza chóralna** (sekcja 3.4).
- **A6. Akceptacja/edycja metadanych w UI** (dziś auto-wypełnia tylko puste pola).
Kryteria wyjścia: na realnych skanach `note_recall ≥ 0.85`, tekst we wszystkich głosach,
otwieralność w MuseScore 100%, metadane poprawne w ≥80% plików.

### Faza 1.5 — Silnik śpiewalnego tłumaczenia (równolegle, flagowiec)
Sekcja 3.1, v1→v2. To różnicowanie rynkowe — uruchomić wcześnie jako „wow", nawet w wersji v1
(twardy limit sylab + raport rozbieżności). Wielojęzyczność od początku.

### Faza 2 — Biblioteka repertuaru + liturgia
- Kalendarz roku kościelnego + sugestie repertuaru na okazję/okres.
- Planer zestawów na nabożeństwo/koncert; eksport listy (PDF/druk).
- Historia wykonań + statystyki („dawno nieśpiewane").
- Wyszukiwanie domenowe (okazja, język, obsada, trudność, tonacja, incipit tekstu).
- Współdzielenie biblioteki w zespole (wielu użytkowników, role).

### Faza 3 — Próby i wykonania
- Odtwarzanie pojedynczych głosów (MIDI z MusicXML) — ścieżki do nauki.
- Transpozycja pod możliwości zespołu (1 klik) + eksport kart głosowych S/A/T/B.
- Ściągi wymowy/IPA (sekcja 2.2 pkt 6).
- Adnotacje dyrygenckie na partyturze (oddechy, dynamika, wejścia).

### Dla kompozytora (przekrojowo, dłuższy horyzont)
- szkic → asysta grawerska; ostrzeżenia o zakresach głosów pod docelowy zespół; kontrola
  prowadzenia głosów; natychmiastowe re-voicing/transpozycja.

---

## 6. Wartość biznesowa

### 6.1. Segmenty
- **Dyrygenci chórów kościelnych/parafialnych** (główny) — materiał rozproszony, brak narzędzia.
- **Scholae, zespoły oazowe, chóry amatorskie** — podobne potrzeby, mniejszy budżet.
- **Chóry szkolne/akademickie** — repertuar świecki + sakralny, dużo tłumaczeń.
- **Kompozytorzy/aranżerzy muzyki chóralnej** — analiza, zakresy, re-voicing.
- **Wydawcy/redaktorzy nut** (niszowy premium) — masowa digitalizacja + redakcja + tłumaczenia.

### 6.2. Propozycja wartości
- Oszczędność godzin: koniec z ręcznym podkładem tekstu i **ręcznym śpiewalnym tłumaczeniem**.
- Porządek: jedna przeszukiwalna biblioteka zamiast teczki ksero.
- Dopasowanie: analiza i transpozycja pod *ten* chór.
- Zaufanie: pętla korekty z mapą pewności (nie czarna skrzynka).
- Domena + wielojęzyczność: rozumie liturgię i obcojęzyczny repertuar.

### 6.3. Monetyzacja (do walidacji)
- **Subskrypcja per dyrygent** (Free: N utworów; Pro: bez limitu + **tłumaczenie śpiewalne** +
  transpozycje + ścieżki głosów). Tłumaczenie/analiza = naturalne funkcje premium (i koszt LLM).
- **Plan zespołowy/parafialny** — współdzielona biblioteka.
- Koszt AI jako zmienna → drogie kroki limitowane w Free; fallback CLI + warunkowe kroki mają
  sens także kosztowy.

### 6.4. Ryzyka
- **Koszt/limit LLM** (Gemini free = 20 req/dobę) → billing lub model lokalny; mitygacja:
  warunkowe kroki, fallback CLI, cache.
- **Jakość na realnych skanach** — dziś dowód tylko na czystych PDF (Faza 1, A3–A4).
- **Jakość tłumaczeń śpiewalnych** — trudny problem; zaczynamy od v1 z raportem rozbieżności i
  człowiekiem w pętli, nie obiecujemy automatu.
- **Prawa autorskie** — biblioteka musi rozróżniać public domain (CPDL/IMSLP) od materiału
  licencjonowanego; tłumaczenia tekstów chronionych = ostrożnie.
- **Wąski rynek** — przewaga = głęboka domena + funkcje, których nie ma nikt, nie skala.

---

## 7. Przegląd obecnego stanu (agenci + struktura)

### 7.1. Struktura `src/`
Warstwowa, czytelna (DB ↔ services ↔ UI ↔ engines) — realny atut.
- **Keep:** `src/database` (modele + auto-migracja), `src/services` (serwis jako jedyne miejsce
  zapisu — bardzo dobre), `src/llm` (agenci + walidacja music21), `src/ocr`, `src/analysis`,
  `src/evaluation` (harness jakości — wyróżnik).
- **Change:** `src/app/main.py` ~1640 linii w jednym pliku → rozbić na komponenty/strony zanim
  dojdą funkcje Faz 2/3 (i zanim dołożymy widok korekty z mapą pewności). Największy dług UI.
- **Watch:** dwoistość backendu LLM (Gemini + CLI) — trzymać wąski kontrakt `complete_text`/`parse`.

### 7.2. Agenci `.claude/agents/`
Zestaw ról sensowny. 
- **Keep:** `product-owner`, `ocr-engineer` (rdzeń), `ui-engineer` (czeka refactor main.py +
  widok korekty), `code-reviewer`.
- **Rozważyć nowy `llm-engineer` / `music-ai`** — prace nad agentami LLM (kroki 2/4/5, analiza,
  **silnik tłumaczenia**) stają się rdzeniem produktu i zasługują na własny profil.
- **Niższy priorytet teraz:** `devops-engineer` (przed komercją).

### 7.3. Werdykt
Projekt **wnosi unikalną wartość pod warunkiem trzymania kursu na: tłumaczenie śpiewalne +
analizę pod chór + bibliotekę liturgiczną + pętlę korekty z człowiekiem** — i to wielojęzycznie.
Jako generyczny OMR — nie. Łączymy rzeczy, których nikt nie łączy.

---

## Załącznik: stan techniczny (skrót)
- Pipeline: OCR → (metadane) → czyszczenie tekstu → OMR → korekta → podkład tekstu.
- OMR: Audiveris (`D:\Audiveris\Audiveris.exe`). LLM: Gemini główny + `claude` CLI fallback.
- Output kanoniczny: walidowany, otwieralny `.musicxml` (+ `.mxl`); `.mscz` jako add-on.
- Testy: 236 zielonych (2026-06-15). Eval: `data/processed/eval/REPORT.md`.
- Notatki stanu: `llm-pipeline-state`, `omr-engine-state`, `product-roadmap`.
