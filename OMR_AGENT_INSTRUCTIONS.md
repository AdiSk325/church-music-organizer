# OMR Quality Engineer — Instrukcje na podstawie testu "Boże mój"

> Wygenerowano: 2026-02-16
> Plik testowy: `tests/OMR/test_input/Boże_mój.png` (344×868 px, 2 pięciolinie)
> Ground truth: `tests/OMR/expected_output/Boże_mój.musicxml` (MuseScore 4.6.5)

---

## 1. Opis testu

Partytura **"Boże mój"** (m.: J. Sykulski, t.: Ps 22,2) — prosty utwór SATB bez organów:

| Cecha | Expected |
|-------|----------|
| Części | 2: SA (treble clef), TB (bass clef) |
| Tonacja | F-dur (1 bemol) |
| Metrum | 4/4 |
| Takty | 4 (z repetycją) |
| Głosy | 2 per pięciolinię (voice 1 = S/T stem up, voice 2 = A/B stem down) |
| Bracket | SA + TB połączone bracketem |
| Repeat | forward (heavy-light) na początku, backward (light-heavy) na końcu |
| Lyrics | Tekst na voice 1 (sopran): "Bo-że mój, Bo-że mój, cze-muś mnie o-puś-cił?" |

---

## 2. Wyniki OMR — podsumowanie

### Co pipeline zrobił dobrze ✅

| Element | Opis |
|---------|------|
| **Detekcja pięciolinii** | 2 pięciolinie poprawnie wykryte (y=145-175, y=278-308) |
| **Liczba taktów** | 4 takty per staff — **POPRAWNIE** (to duży postęp vs Alleluja!) |
| **Klucze** | G2 (treble) i F4 (bass) — oba poprawne |
| **Tonacja SA** | -1 flat (F-dur) — **poprawnie** |
| **Podział na części** | 2 staves → 2 parts — poprawnie |
| **Bracket group** | Dodany automatycznie — poprawnie |
| **DIVISIONS** | Poprawne skalowanie z divisions=2 na divisions=4 |
| **Staff splitting** | 2 poprawne obrazy wyciętych pięciolinii |

### Co poszło źle 🔴

| # | Problem | Priorytet | Moduł |
|---|---------|-----------|-------|
| 1 | **Tonacja TB: +2 sharps** zamiast -1 flat | 🔴 Krytyczny | homr_engine |
| 2 | **Metrum: 2/2** zamiast 4/4 (oba staffy) | 🟡 Ważny | homr_engine |
| 3 | **Pitch errors SA** — M1: F4+B3 zamiast A4, D4 | 🔴 Krytyczny | homr_engine |
| 4 | **Pitch errors TB** — F#3, C#3 (nie istnieją w F-dur!) | 🔴 Krytyczny | homr_engine |
| 5 | **Voice separation** — S+A jako chordy zamiast 2 voices | 🔴 Krytyczny | homr_engine |
| 6 | **Phantom rests** — homr wstawia rest(whole) w M2, rest(half) w M3 | 🟡 Ważny | homr_engine |
| 7 | **Beat count errors** — M2:P1 = 7 beats, M2:P2 = 9 beats | 🟡 Ważny | homr → score_builder |
| 8 | **Repeat barlines** — brak detekcji forward/backward | 🟡 Ważny | homr_engine |
| 9 | **Part names: "Part 1/2"** — brak nazw S A / T B | 🟢 Mniejszy | score_builder |
| 10 | **Unicode: "BoĹĽe mĂłj"** w XML zamiast "Boże mój" | 🟢 Mniejszy | score_builder |
| 11 | **Unicode path: cv2.imread** nie czyta polskich znaków | 🟢 Mniejszy | staff_detector |

---

## 3. Szczegółowa analiza note-by-note

### Part 1 (SA, treble clef)

#### M1 — Tonacja poprawna, pitch-e BŁĘDNE

```
Expected (voice 1 - Sopran):  A4(q)  F4(q)  E4(h)
Expected (voice 2 - Alt):     D4(q)  D4(q)  A3(h)

Actual (homr, single voice):  F4+B3(chord q)  D4+Bb3(chord q)  C4(h)
```

**Analiza**: homr nie rozdzielił głosów. Zamiast S=A4 + A=D4 dał chord F4+B3.
Pitch shift: A4→F4 (tercja w dół), D4→B3 (tercja w dół). Konsystentny błąd!
E4→C4 (też tercja w dół). **Hipoteza**: homr czyta nuty 1 tercję za nisko.

#### M2 — Phantom rest + beat overflow

```
Expected: S: A4(q) D5(q) C5(h) | A: D4(q) F4(q) E4(h)      = 8 beats (4+4)
Actual:   F4(8th) rest(whole) D4+Bb4(8th chord) C4+A4(h chord) = 7 beats
```

**Analiza**: homr zamienił ćwierćnuty na ósemki i wstawił „phantom whole rest".
Phantom rest to artefakt — homr wykrywa coś czego nie ma.

#### M3 — Phantom rests

```
Expected: S: C5 G4 Bb4 A4 (4×q) | A: C4 C4 D4 D4 (4×q)        = 8 beats
Actual:   A4(q) rest(h) E4(q) G4(q) rest(h) F4(q)              = 8 beats ✅ count
```

**Analiza**: pitch shift nadal tercja w dół. C5→A4, G4→E4, Bb4→G4, A4→F4.
Phantom half-rests wstawione między nuty.

#### M4 — Zbliżone do expected

```
Expected: S: A4(8) G4(8) D4(q) E4(h) | A: C4.(dotted q) Bb3(8) A3(h)
Actual:   F4(8) rest(h) E4(8) Bb3(q) C4(h)                     = 4 beats
```

Tercja w dół nadal: A4→F4, G4→E4.

### Part 2 (TB, bass clef)

#### GŁÓWNY PROBLEM: Tonacja +2 sharps (D-dur) zamiast -1 flat (F-dur)

To powoduje, że **każde F staje się F#, każde C staje się C#**. 
Wszystkie pitch-e z TB staff są zafałszowane przez błędną tonację.

```
Expected M1 (T): A3(q) A3(h) A3(q)     | (B): D3(q) D3(q) A2+E3(h chord)
Actual M1 (raw): D3+A3(8th chord) B2(8th) F#3(h) F#2+C#3(h chord) F#3(8th)
```

**Analiza**: F#3, C#3, F#2 — to artefakty złej tonacji.  Gdyby klucz był -1 flat: F3 zamiast F#3, C3 zamiast C#3.
Ale nawet po korekcie tonacji, pitch-e byłyby F3, C3, F2 — nadal nie pasują do expected A3, D3, A2+E3.

#### M3 — Jedyny takt zbliżony do oczekiwanego

```
Expected (T): G3 G3 G3 G3 | (B): C3 C3 G2 D3      = 8 beats
Actual:   E3+A2(q chord) E3+A2(q chord) E3+E2(q chord) E3+B2(q chord) = 4 beats
```

Pitch shift: G3→E3 (tercja w dół), C3→A2 (tercja w dół).

---

## 4. Wnioski — wzorzec błędów

### A) Konsystentny pitch shift o tercję w dół

Na obu pięcioliniach homr czyta nuty **~3 półtony za nisko**:
- A4 → F4 (SA M1)
- E4 → C4 (SA M1)
- C5 → A4 (SA M3)
- G3 → E3 (TB M3)
- C3 → A2 (TB M3)

**Przyczyna**: Prawdopodobnie problem z kalibracją pozycji nut względem linii pięciolinii.
Homr może źle wykrywać pozycję referencyjna (środkowa linia = B4 na kluczu G, D3 na kluczu F).

### B) Brak voice separation (S vs A, T vs B)

Zamiast 2 głosów (stem up + stem down) homr tworzy akordy.
To znany problem — homr nie rozróżnia kierunku lasek nut (stem direction).

### C) Phantom rests

Homr wstawia `rest_2` (half rest) i `rest_1` (whole rest) tam, gdzie w partyturze
ich nie ma. Prawdopodobny powód: artefakty wizualne (kurz, plamy) interpretowane jako pauzy.

### D) Błędna tonacja na kluczu basowym

Homr wykrywa +2 sharps zamiast -1 flat na pięciolinii z kluczem F.
Prawdopodobnie myli bemole z krzyżykami gdy symbole są na niższych liniach.

---

## 5. Plan naprawczy — co robić NASTĘPNE

### Priorytet 1: Post-processing korekta pitch (NOWY MODUŁ)

**Cel**: `pitch_corrector.py` — korekta systematycznego przesunięcia pitch-ów po OMR.

Algorytm:
1. Pobierz tonację z OMR (key signature)
2. Sprawdź, czy pitch-e mieszczą się w tej tonacji
3. Jeśli >50% nut jest poza tonacją, spróbuj korekcji o ±1, ±2, ±3 półtony
4. Wybierz przesunięcie, które daje najwięcej nut w tonacji

Dodatkowa heurystyka:
- Jeśli oba staves mają ten sam PDF, wymuś tę samą tonację na obu
- Porównaj pitch range z oczekiwanym (SA: ~C4-D5, TB: ~A2-A3)

### Priorytet 2: Voice separation post-processing (NOWY MODUŁ)

**Cel**: `voice_separator.py` — rozdzielenie akordów na 2 głosy.

Algorytm dla każdego taktu:
1. Znajdź wszystkie akordy (notes z <chord/>)
2. Dla akordów 2-nutowych: wyższy pitch → voice 1, niższy → voice 2
3. Dla nut bez chord: przydziel do voice na podstawie pitch range
   (jeśli pitch > mediana → voice 1, inaczej → voice 2)
4. Wstaw `<backup>` między voice 1 a voice 2

### Priorytet 3: Phantom rest removal

**Cel**: Usuwanie phantom rests wstawionych przez homr.

Heurystyka:
- Rest + nota w tym samym voice i overlapping timing → usuń rest
- Rest w voice 2, a w voice 1 jest nota na tym samym offset → artefakt
- Whole rest w takcie, który ma też nuty → phantom

### Priorytet 4: Key signature consistency check

**Cel**: Wymuszenie spójnej tonacji między staves tego samego systemu.

Algorytm:
- Weź key signature z treble staff (bardziej wiarygodny)
- Zastosuj na bass staff  
- Przetransponuj nuty bass staff do prawidłowej tonacji
  (np. jeśli bass miał +2 sharps → -1 flat: usuń F# → F, C# → C)

### Priorytet 5: Repeat barline detection

**Cel**: Wykrywanie powtórzeń (heavy-light / light-heavy barlines).

Podejście OpenCV:
- Szukaj pionowych linii o różnej grubości na krawędziach taktów
- Thick + thin = forward repeat
- Thin + thick = backward repeat  
- Dodaj `<barline><repeat direction="forward/backward"/></barline>`

---

## 6. Metryki sukcesu

| Metryka | Obecny wynik | Cel |
|---------|-------------|-----|
| Pitch accuracy (SA) | ~20% (tercja shift) | >80% |
| Pitch accuracy (TB) | ~10% (shift + key error) | >80% |
| Voice separation | 0% (all chords) | >90% (2 voices) |
| Key signature accuracy | 50% (1/2 correct) | 100% |
| Time signature | 0% (2/2 vs 4/4) | 100% |
| Beat count per measure | 60% (3/8 measures ok) | 100% |
| Repeat barlines | 0% | 100% |
| Note count accuracy | SA: 14/27 (52%) | >90% |
| Note count accuracy | TB: 19/27 (70%) | >90% |

---

## 7. Pliki do modyfikacji/utworzenia

| Plik | Akcja | Cel |
|------|-------|-----|
| `src/ocr/pitch_corrector.py` | **NOWY** | Post-OMR korekta pitch shift |
| `src/ocr/voice_separator.py` | **NOWY** | Rozdzielenie chordów na 2 voices |
| `src/ocr/score_builder.py` | MODYFIKUJ | Integracja pitch_corrector + voice_separator |
| `src/ocr/staff_detector.py` | MODYFIKUJ | Unicode path support (cv2.imread → numpy workaround) |
| `src/ocr/engines/homr_engine.py` | ZBADAJ | Czy homr ma opcje kalibracji pitch/key |
| `convert_pdf_to_musicxml.py` | MODYFIKUJ | Dodaj obsługę wejść PNG (nie tylko PDF) |
| `tests/test_omr_boze_moj.py` | **NOWY** | Automatyczny test porównujący z ground truth |

---

## 8. Jak uruchomić test

```bash
# 1. Skopiuj plik (workaround na unicode path)
cp tests/OMR/test_input/Boże_mój.png data/processed/temp/boze_moj_test.png

# 2. Uruchom test
python test_boze_moj.py

# 3. Porównaj wynik
# Otwórz w MuseScore:
#   data/processed/boze_moj_test_final.musicxml  (actual)
#   tests/OMR/expected_output/Boże_mój.musicxml  (expected)
```
