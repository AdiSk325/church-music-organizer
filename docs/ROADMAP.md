# Roadmapa i strategia produktu — Church Music Organizer

> Dokument strategiczny. Łączy wizję produktu, szczerą ocenę rynku, fazową roadmapę
> rozwoju i wartość biznesową. Aktualizowany 2026-06-15.

---

## 1. Wizja

**Docelowo: kompleksowe narzędzie dla dyrygenta chóralnego** — od pozyskania i uporządkowania
materiału nutowego, przez pracę edytorską nad partyturą, po codzienność prób i wykonań z chórem.

Nie budujemy „kolejnego OMR". Budujemy środowisko pracy dyrygenta/edytora muzyki chóralnej
(ze szczególnym uwzględnieniem **polskiej i łacińskiej muzyki kościelnej**), w którym
transkrypcja AI jest jednym z silników, a nie produktem samym w sobie.

Kolejność rozwoju (decyzja właściciela, 2026-06-15):
1. **(P-now) AI edytor partytur** — jakość transkrypcji i analizy. *Tu jest dziś nacisk.*
2. **Biblioteka repertuaru + liturgia** — organizacja, kalendarz, planowanie.
3. **Narzędzie prób/wykonań** — odtwarzanie głosów, ścieżki do nauki, transpozycje, adnotacje.

---

## 2. Szczera ocena rynku i różnicowanie

### 2.1. Czego NIE warto budować

Sam łańcuch **skan → MusicXML** jest rynkiem zatłoczonym i dojrzałym. Konkurujemy tam ze
specjalistami, którzy mają lata przewagi:

| Narzędzie | Czym jest | Dlaczego trudno wygrać |
|-----------|-----------|------------------------|
| **PhotoScore / NotateMe (Neuratron)** | komercyjny OMR, integracja z Sibelius | wieloletni, dokładny silnik |
| **SmartScore (Musitek)** | komercyjny OMR | dojrzały, sprzedaż per-licencja |
| **Audiveris** | open-source OMR (już go używamy!) | darmowy; my jesteśmy jego *nakładką* |
| **Soundslice / ScanScore / PlayScore** | skan + odtwarzanie | mobilne, dopracowane UX |
| **MuseScore import / Finale / Dorico** | import MusicXML + grawerka | standard rynkowy edycji |

**Wniosek:** generyczny „wgraj skan, dostań nuty" nie wnosi nowej wartości i stawia nas w roli
gorszego klona Audiverisa. Eval (`data/processed/eval/REPORT.md`) to potwierdza: na czystych
cyfrowych PDF-ach surowy Audiveris ma recall ~1.0 — krok korekty LLM dokłada tam *prawie nic*.

### 2.2. Gdzie jest realny „moat" (przewaga obronna)

Wartość rodzi się na styku **domeny + workflow chóralnego + AI**, którego nie ma żadne narzędzie
OMR ani edytor ogólnego przeznaczenia:

1. **Domena: polska/łacińska muzyka kościelna.** Repertuar liturgiczny, typowe frazy, dwujęzyczność
   (łacina/polski), metadane liturgiczne. Globalni gracze tego nie obsługują.
2. **Wielogłosowy podkład tekstu (SATB).** Nasz krok 5 podkłada tekst *per głos* — to realny ból
   edytorski (PhotoScore/OMR gubią tekst, a ręczne podłożenie 4 głosów to godziny pracy).
3. **Biblioteka repertuaru zorientowana liturgicznie.** Model już ma `occasion`,
   `liturgical_season`, `UsageHistory` — szkielet organizera, którego OMR-y nie mają w ogóle.
4. **Analiza pod kątem chóru, nie maszyny.** Ocena trudności dla zespołu amatorskiego, zakresy
   głosów, prowadzenie głosów, sugestie transpozycji pod możliwości chóru.

### 2.3. Pozycjonowanie jednym zdaniem

> „Asystent dyrygenta chóralnego: zamienia skany i PDF-y w uporządkowaną, przeszukiwalną,
> gotową do próby bibliotekę repertuaru — z poprawnym tekstem pod nutami i analizą pod możliwości
> Twojego zespołu."

---

## 3. Faza wykonawcza (TERAZ) — jakość AI

Nacisk: zanim dołożymy funkcje, **transkrypcja i analiza muszą być wiarygodne dla muzyka**.
Bieżący PR (branch `feature/omr-engine-wiring`) realizuje fundamenty:

- ✅ **Odporność backendu LLM.** Gemini główny + naprawiony fallback `claude` CLI (chudy start
  `--strict-mcp-config`, model per-krok, timeouty per-krok, `TimeoutExpired`→błąd przejściowy).
  Rozwiązuje zgłaszany `TimeoutExpired`.
- ✅ **Wersjonowanie plików + timestampy.** `MusicFile.version` + nazwa
  `corrected_v2_<data>_<stem>.musicxml`; UI grupuje pliki wg rodzaju, pokazuje wersję, czas
  utworzenia, pochodzenie (krok) i oznacza „aktualną".
- ✅ **Ekstrakcja metadanych (autorzy/tytuł).** Nowy agent `metadata_extractor` czyta nagłówek
  z OCR i uzupełnia *tylko puste* pola utworu (nie nadpisuje wpisów użytkownika).

Kolejne kroki tej fazy (priorytety):

- **A1. Chunking partytury dla kroku 4** (`score_corrector.py`) — całość w prompcie ucina się na
  SATB. Dzielić po taktach/systemach, jak już zrobiono dla underlay (krok 5).
- **A2. Warunkowa korekta (krok 4).** Uruchamiać tylko gdy `note_recall < 0.95` lub takty
  przepełnione — oszczędza budżet, bo na czystym OMR korekta nic nie wnosi (dowód: eval).
- **A3. Pogłębiona analiza chóralna.** Rozszerzyć `score_analyzer`/`score_descriptor`: zakresy
  i tessitura głosów, ocena trudności dla chóru amatorskiego, wykrycie divisi, sugestie
  transpozycji. To jest „detailed AI analysis", o którą prosi właściciel.
- **A4. Zestaw ground-truth z realnych skanów** (nie tylko czystych PDF). Obecny eval mierzy
  sufit best-case; realna wartość to brudne skany parafialne. Zob. [[no-internet-access]].
- **A5. Akceptacja metadanych w UI** — podgląd wyciągniętych pól z „Zastosuj/Edytuj" przed zapisem
  (dziś auto-wypełnia puste; warto dać kontrolę i oznaczać pola „uzupełnione przez AI").

---

## 4. Roadmapa fazowa

### Faza 1 — AI edytor partytur (TERAZ → najbliższe iteracje)
Cel: zaufanie do wyniku. Transkrypcja + tekst + metadane + analiza na poziomie użytecznym dla
dyrygenta. Zakres: sekcja 3 (A1–A5). Kryteria wyjścia: na zestawie realnych skanów —
`note_recall ≥ 0.85`, tekst pod nutami we wszystkich głosach, poprawne metadane w ≥80% plików,
otwieralność w MuseScore 100%.

### Faza 2 — Biblioteka repertuaru + liturgia
Cel: z „przetwarzarki plików" w **bibliotekę zespołu**.
- Kalendarz liturgiczny (rok kościelny) + automatyczne sugestie repertuaru na okazję/okres.
- Planer zestawów na nabożeństwo/koncert; eksport listy (PDF/print).
- Bogatsza historia wykonań i statystyki (co, kiedy, jak często, „dawno nieśpiewane").
- Wyszukiwanie i filtry domenowe (okazja, język, obsada, trudność, tonacja).
- Współdzielenie biblioteki w obrębie zespołu (wielu użytkowników, role).

### Faza 3 — Próby i wykonania
Cel: codzienna praca z chórem.
- Odtwarzanie pojedynczych głosów (MIDI z MusicXML) jako ścieżki do nauki.
- Transpozycja pod możliwości zespołu (jeden klik, eksport części).
- Generowanie kart głosowych (S/A/T/B) i materiałów do druku.
- Adnotacje dyrygenckie na partyturze (oddechy, dynamika, wejścia).

---

## 5. Wartość biznesowa

### 5.1. Segmenty klientów
- **Dyrygenci chórów kościelnych/parafialnych** (główny) — często amatorzy-zapaleńcy, materiał
  rozproszony w skanach/ksero, brak narzędzia łączącego porządkowanie + przygotowanie.
- **Scholae, zespoły oazowe, chóry amatorskie** — podobne potrzeby, mniejszy budżet.
- **Dyrygenci chórów szkolnych/akademickich** — repertuar świecki + sakralny.
- **Wydawcy/redaktorzy nut sakralnych** (niszowy, premium) — masowa digitalizacja + redakcja.

### 5.2. Propozycja wartości
- Oszczędność czasu: koniec z ręcznym podkładaniem tekstu pod 4 głosy i przepisywaniem skanów.
- Porządek: jedna przeszukiwalna biblioteka zamiast teczki ksero i plików na dysku.
- Dopasowanie: analiza i transpozycja pod realne możliwości *tego* chóru.
- Domena: rozumie liturgię i polski/łaciński repertuar — nie trzeba „tłumaczyć" narzędziu kontekstu.

### 5.3. Modele monetyzacji (do walidacji)
- **Subskrypcja per dyrygent** (Free: N utworów / Pro: bez limitu + transpozycje + ścieżki).
- **Plan zespołowy/parafialny** — współdzielona biblioteka, wielu użytkowników.
- **Koszt AI jako zmienna** — drogie kroki (LLM) limitowane w planie Free; stąd backend
  z fallbackiem i warunkowym uruchamianiem kroków (sekcja 3) ma też sens kosztowy.

### 5.4. Ryzyka
- **Koszt/limit LLM** — darmowy Gemini ma 20 req/dobę; produkcyjnie potrzebny billing lub model
  lokalny. Mitygacja: warunkowe kroki, fallback CLI, cache wyników.
- **Jakość na realnych skanach** — dziś dowód tylko na czystych PDF (A4 wyżej).
- **Prawa autorskie** — repertuar współczesny bywa pod ochroną; biblioteka musi rozróżniać
  public domain (CPDL/IMSLP) od materiału licencjonowanego.
- **Wąski rynek** — nisza jest mała; przewaga = głęboka domena, nie skala.

---

## 6. Przegląd obecnego stanu (agenci + struktura)

### 6.1. Struktura `src/` — ocena
Warstwowa, czytelna, dobrze rozdzielona (DB ↔ services ↔ UI ↔ engines). Atut realny.
- **Keep:** `src/database` (modele + auto-migracja SQLite), `src/services` (warstwa serwisowa
  jako jedyne miejsce zapisu — bardzo dobre), `src/llm` (agenci + walidacja music21), `src/ocr`,
  `src/analysis`, `src/evaluation` (harness jakości — wyróżnik!).
- **Change:** `src/app/main.py` to ~1640 linii w jednym pliku — rozbić na komponenty/strony
  (ui-engineer) zanim dojdą funkcje Fazy 2/3. Dziś to największy dług techniczny UI.
- **Watch:** dwoistość backendu LLM (Gemini + CLI) jest OK, ale wymaga utrzymania dwóch ścieżek
  strukturalnego wyjścia — trzymać kontrakt `complete_text`/`parse` wąsko.

### 6.2. Agenci `.claude/agents/` — ocena
Zestaw (`product-owner`, `backend/ocr/ui/qa/devops-engineer`, `code-reviewer`) jest sensowny i
pokrywa role projektu. Wartość = szybkie, kontekstowe delegowanie.
- **Keep:** `product-owner` (strategia/domena), `ocr-engineer` (rdzeń wartości), `ui-engineer`
  (czeka go refactor main.py), `code-reviewer` (jakość przed merge).
- **Rozważyć:** dedykowany **`llm-engineer`/`music-ai`** — dziś prace nad agentami LLM
  (kroki 2/4/5, analiza) wpadają między `ocr-engineer` a `backend-engineer`; to staje się rdzeniem
  produktu (Faza 1), więc zasługuje na własny profil.
- **Niższy priorytet teraz:** `devops-engineer` (CI/Docker) — wartościowy, ale przed komercją.

### 6.3. Werdykt
Projekt **wnosi wartość dodaną pod warunkiem trzymania kursu na domenę + workflow chóralny**.
Jako generyczny OMR — nie. Jako asystent dyrygenta z polską muzyką kościelną w centrum — tak,
bo łączy rzeczy, których nikt nie łączy: poprawny wielogłosowy tekst, analizę pod chór i
liturgiczną bibliotekę repertuaru.

---

## Załącznik: stan techniczny (skrót)
- Pipeline 5-krokowy: OCR → (metadane) → czyszczenie tekstu → OMR → korekta → podkład tekstu.
- OMR: Audiveris (`D:\Audiveris\Audiveris.exe`). LLM: Gemini główny + `claude` CLI fallback.
- Output kanoniczny: walidowany, otwieralny `.musicxml` (+ `.mxl`); `.mscz` jako add-on.
- Testy: 236 zielonych (2026-06-15). Eval: `data/processed/eval/REPORT.md`.
- Szczegóły stanu: zob. notatki pamięci `llm-pipeline-state`, `omr-engine-state`.
