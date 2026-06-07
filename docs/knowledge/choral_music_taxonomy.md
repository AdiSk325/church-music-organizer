# Choral Music Taxonomy — Reference Guide

This document is the authoritative reference for the score analysis engine.
Each section defines a classification category, its possible values, detection heuristics,
and examples from the Western choral repertoire.

---

## 1. Voice Classification

### 1.1 Standard SATB Ranges

| Voice | Full Range | Comfortable Tessitura | Clef |
|-------|-----------|----------------------|------|
| Soprano (S) | C4 – C6 | D4 – A5 | Treble |
| Mezzo-soprano | A3 – B5 | B3 – G5 | Treble |
| Alto (A) | F3 – F5 | G3 – D5 | Treble |
| Tenor (T) | C3 – C5 | D3 – A4 | Treble 8vb |
| Baritone | A2 – G4 | C3 – E4 | Bass |
| Bass (B) | E2 – E4 | F2 – C4 | Bass |

Note: Middle C = C4 in scientific notation.

### 1.2 Extended Voicings

| Abbreviation | Description |
|---|---|
| SATB | Standard 4-part mixed choir |
| SSATBB | Double choir, divisi soprano and bass |
| SSAA | Two-part treble choir |
| TTBB | Two-part male choir |
| SAB | 3-part mixed (beginner-friendly) |
| SA / TB | Two-part |
| Unison | All voices on one melodic line |
| Children's (SA) | Unchanged voices, range roughly D4–D6 |
| Treble choir | Any unchanged/female ensemble |

### 1.3 Detection Heuristics

- Count `score.parts` to determine `voice_count`.
- Match `part.partName` (case-insensitive) against known voice labels.
- Map detected ranges to the table above: soprano if lowest note ≥ B3, bass if highest note ≤ G4.

---

## 2. Musical Texture

Texture describes **how many voices are present** and **how independently they move**.

### 2.1 Taxonomy

| Texture Type | Definition | Key Metric | Choral Example |
|---|---|---|---|
| **Monophony** | Single unison melodic line | 1 part | Gregorian chant |
| **Homophony — Chorale** | All voices move in the same rhythm (note-against-note) | Onset simultaneity > 0.85 | Bach chorales, hymn settings |
| **Homophony — Melody** | One voice leads; others accompany in different rhythm | Onset simultaneity 0.60–0.85 | Gospel anthems, contemporary praise |
| **Polyphony — Imitative** | Voices enter successively with same theme; motif heard throughout | Onset simultaneity < 0.50, shared opening intervals | Palestrina motets, fugues, canons |
| **Polyphony — Free** | Voices are independent but do not share a common theme | Onset simultaneity < 0.50, no shared motifs | Renaissance motets (some), free counterpoint |
| **Heterophony** | Multiple voices simultaneously present different variants of the same melody | Onset simultaneity ~0.70, small inter-voice intervals | Bulgarian folk choral, some Byzantine chant |

### 2.2 Quantitative Detection Criteria

```
onset_simultaneity  = (onsets_in_all_parts) / (total_unique_onsets)
voice_independence  = 1.0 − onset_simultaneity
rhythmic_variance   = stdev(onset_counts_per_part) / max(onset_counts)
```

| Range | Classification |
|---|---|
| Simultaneity > 0.85 | homophonic_chorale |
| Simultaneity 0.60–0.85 | homophonic_melody |
| Simultaneity < 0.60, rhythmic_variance > 0.3 | polyphonic_free |
| Simultaneity < 0.60, rhythmic_variance ≤ 0.3 | polyphonic_imitative |
| 1 part | monophonic |

---

## 3. Musical Form Types

### 3.1 Taxonomy

| Form | Pattern | Description | Choral Genre |
|---|---|---|---|
| **Strophic** | AAA... | Repeated music for each text stanza | Hymns, chorales, folk songs |
| **Through-composed** | ABCD... | New music for each section | Motets (some), art songs |
| **Binary** | AB | Two sections; may be repeated (||: A :||: B :||) | Baroque dance movements, some hymns |
| **Rounded Binary** | ABA' | A returns in abbreviated form inside B section | Late Baroque, early Classical |
| **Ternary** | ABA | Three sections with full return of A | Da capo arias, anthems |
| **Rondo** | ABACADA | Refrain alternates with episodes | Some cantata movements |
| **Verse-Refrain** | aB aB | Alternating solo verse and choral refrain | Responsorial psalms, gospel |
| **Canon** | strict | One voice imitates another at fixed time/pitch interval | "Dona nobis pacem", rounds |
| **Fugue** | Expo + Dev + Stretto | Subject presented in all voices, developed contrapuntally | Bach motets, Handel choruses |
| **Motet** | polyphonic | Through-composed sacred work; Renaissance = polyphonic, Baroque = concertato | Palestrina, Victoria, Bach |
| **Anthem** | homophonic | Sacred work in English tradition; full anthem vs. verse anthem | Handel, Purcell, Elgar |
| **Cantus Firmus** | CF in long notes | Pre-existing melody (chant) in long notes, other voices weave around it | Renaissance mass movements |
| **Ostinato / Passacaglia** | repeating bass | Fixed bass line or harmonic pattern repeats while upper voices vary | Baroque chaconne, some contemporary |

### 3.2 Detection Heuristics

- **Canon detection**: Compare interval sequences of opening 4–8 notes across parts. If ≥ 2 parts share the same interval sequence (one starting later), classify as canon.
- **Fugue vs. canon**: Canon = strict pitch-interval imitation throughout; fugue = subject/answer with tonal answer adjustment + countersubject.
- **Strophic**: Presence of repeat barlines (`Repeat` class in music21) or identical music at fixed measure intervals.
- **Ternary**: 3 structural sections with the last section matching the first (structural repetition at measure level).
- **Through-composed**: No detected repetition, no structural return.

---

## 4. Harmonic Style Epochs

### 4.1 Classification Table

| Epoch | Approx. Dates | Key Harmonic Characteristics | Chromatic Complexity |
|---|---|---|---|
| **Medieval / Gregorian** | Pre-1400 | Modal (8 church modes); parallel organum; no functional harmony; perfect intervals preferred | < 0.02 |
| **Renaissance** | 1400–1600 | Triadic harmony emerging; modal or transitional; voice-leading rules (no parallel 5ths/8ths); text expression (musica reservata) | 0.02–0.08 |
| **Baroque** | 1600–1750 | Functional tonality established; basso continuo; phrase model T→PD→D→T; sequences; dominant 7ths; Bach chorale style | 0.05–0.15 |
| **Classical** | 1750–1820 | Clear phrase structure (antecedent-consequent periods); simpler harmonies; circle-of-fifths progressions; less chromaticism than Baroque | 0.04–0.12 |
| **Romantic** | 1820–1900 | Chromaticism; extended chords (7ths, 9ths, 11ths); enharmonic modulation; distant key relationships; word-painting | 0.15–0.35 |
| **Contemporary** | 1900+ | Post-tonal; quartal/quintal harmony; modal writing; bitonality; tone clusters; folk influences; minimalism | 0.30+ |

### 4.2 Epoch Detection Algorithm

```
chromatic_complexity = non_diatonic_notes / total_notes
has_7ths  = "seventh" in any chord.commonName
has_9ths  = "ninth" or "eleventh" in any chord.commonName
```

| Conditions | → Epoch |
|---|---|
| chromatic < 0.04, no 7ths | medieval |
| chromatic < 0.04, has 7ths | renaissance |
| 0.04–0.10, has 7ths | baroque |
| 0.04–0.10, no 9ths | classical |
| 0.10–0.18, no 9ths | classical |
| 0.10–0.18, has 9ths | romantic |
| 0.18–0.30 | romantic |
| > 0.30 | contemporary |

### 4.3 Harmonic Rhythm

The rate at which harmony changes per measure:

| Rate | Description | Typical in |
|---|---|---|
| ≤ 1.5 chords/measure | Slow | Baroque chorales, hymns |
| 1.5–3.5 chords/measure | Moderate | Classical, anthems |
| > 3.5 chords/measure | Fast | Romantic, madrigals |

---

## 5. Cadence Types

| Cadence | Formula | Effect | Period |
|---|---|---|---|
| Perfect Authentic (PAC) | V → I (both in root position, soprano on tonic) | Final, complete closure | All tonal periods |
| Imperfect Authentic (IAC) | V → I (inverted, or soprano not on tonic) | Weaker closure | Classical, Baroque |
| Half cadence (HC) | ? → V | Open, anticipatory | All tonal periods |
| Plagal | IV → I | Soft "Amen" ending | Church music, hymns |
| Deceptive | V → vi | Unexpected continuation | All tonal periods |
| Phrygian half | iv⁶ → V (in minor) | Archaic flavour | Renaissance, Baroque |
| Modal | Clausula vera, no leading tone | Modal ambiguity | Medieval, Renaissance |

---

## 6. Voice Leading Quality

Voice leading quality is central to evaluating Renaissance and Baroque choral writing.

| Metric | Formula | Ideal Value | Poor Value |
|---|---|---|---|
| Parallel 5th rate | parallel_5ths / transitions | 0.00 | > 0.05 |
| Parallel octave rate | parallel_8vas / transitions | 0.00 | > 0.03 |
| Voice crossing rate | crossings / transitions | 0.00 | > 0.10 |
| Contrary motion ratio | contrary_transitions / total | > 0.40 (polyphonic) | < 0.15 |
| Average voice range | semitones per part | ≤ 19 st (12th) | > 24 st (15th) |

music21 classes: `VoiceLeadingQuartet`, methods `parallelFifth()`, `parallelOctave()`, `contraryMotion()`, `voiceCrossing()`.

---

## 7. Text Setting Styles

| Style | Notes per Syllable | Description | Example |
|---|---|---|---|
| Syllabic | 1.0–1.2 | One note per syllable; clear text declamation | Lutheran chorales, hymns |
| Neumatic | 1.2–3.0 | 2–4 notes per syllable; moderate decoration | Gregorian chant, folk-influenced |
| Melismatic | > 3.0 | Many notes per one syllable; ornamental | Renaissance motets, Gospel, Baroque arias |

### Word Painting (Tonmalerei)

Compositional technique where music depicts text meaning:
- **Ascending motion** for words like "rise", "heaven", "glory" (sursum corda)
- **Descending motion** for "fall", "death", "descend" (in terram)
- **Chromaticism** for pain, anguish (lament)
- **Sustained notes** for eternity, peace
- **Rapid syllabic motion** for joy, running, wind
- **Silence** for death, emptiness

Detection: Compare melodic direction at keyword positions vs. overall average. Requires text-alignment data.

---

## 8. Difficulty Classification (NYSSMA 1–6 Scale)

| Grade | Level | Range (semitones) | Key Complexity | Voice Independence | Rhythmic Complexity | Choral Examples |
|---|---|---|---|---|---|---|
| 1 | Elementary | ≤ 14 | C, G, F major | Homorhythmic | Simple quarter/half | "Simple Gifts", unison rounds |
| 2 | Elementary | ≤ 17 | 1-2 sharps/flats | Mostly together | Simple + some dotted | Easy 2-part anthems |
| 3 | Intermediate | ≤ 19 | 2-3 sharps/flats | Some independence | Moderate, 8th notes | Standard SATB hymn settings |
| 4 | Intermediate | ≤ 21 | 3-4 sharps/flats | Moderate independence | Syncopation, triplets | Handel "Hallelujah Chorus" |
| 5 | Advanced | ≤ 24 | 4+ sharps/flats, modal | High independence | Complex rhythms | Bach motets, Brahms |
| 6 | Advanced | > 24 | Chromatic, atonal | Fully independent | Very complex | Ligeti, Pärt, Whitacre |

### Difficulty Scoring Algorithm

Points accumulated:
- `voice_count ≥ 4`: +1
- `range_semitones > 24`: +2; `> 19`: +1
- `chromatic_complexity > 0.25`: +2; `> 0.12`: +1
- `voice_independence > 0.6`: +2; `> 0.3`: +1
- `parallel_fifths > 3`: +1
- `measure_count > 48`: +1

Grade = `clamp(total_points, 1, 6)`.

---

## 9. Language Codes in Liturgical Choral Music

| Language | ISO 639-1 | Common Liturgical Context | Detection Keywords |
|---|---|---|---|
| Latin | `la` | Mass, motet, psalm, requiem, all Catholic and pre-Reformation music | kyrie, gloria, sanctus, dominus, agnus, miserere, alleluia |
| Polish | `pl` | Polish Catholic hymns, kolędy (carols), contemporary sacred | Boże, Panie, Jezu, Chwała, Alleluja; characters: ą ę ó ś ź ż ć ń |
| German | `de` | Lutheran chorales, German Romantic sacred | Herr, Gott, Heilig, Ehre, Halleluja; characters: ä ö ü ß |
| English | `en` | Anglican anthems, American gospel, contemporary praise | Lord, God, Holy, Glory, Alleluia, Blessed |
| Czech | `cs` | Bohemian choral tradition, Czech carols | Bože, Pane, Ježíšu; characters: á é í ů č ř š ž |
| Italian | `it` | Madrigals, Italian sacred music, opera choruses | Signore, Dio, Gesù, Gloria; common words il, la, di |
| French | `fr` | French motets, Huguenot psalms, contemporary Catholic | Seigneur, Dieu, Gloire, Alléluia; characters: à â ç è ê |

---

## 10. CPDL / ChoralWiki Standard Metadata Fields

These fields are used by the Choral Public Domain Library (CPDL) and should be adopted in this project's catalogue schema:

| Field | Type | Allowed Values / Format |
|---|---|---|
| `voicing` | string | "S.A.T.B", "S.S.A.A", "T.T.B.B", "S.A.B", "2-part", "unison" |
| `language` | string | ISO 639-1 code: "la", "pl", "de", "en", "cs", "it", "fr" |
| `genre` | string | "Sacred" or "Secular" + subgenre (Mass, Motet, Hymn, Carol, Anthem, Madrigal, ...) |
| `orchestration` | string | "A cappella", "Piano", "Organ", "Orchestra" |
| `period` | string | "Medieval", "Renaissance", "Baroque", "Classical", "Romantic", "Contemporary" |
| `difficulty` | int | 1–6 (NYSSMA-style) |
| `composer` | string | "Surname, Firstname" |
| `year` | int | Year of composition or first publication |
| `occasion` | string | Liturgical occasion (see occasion enum in models.py) |
| `liturgical_season` | string | "Advent", "Christmas", "Lent", "Easter", "Ordinary", "All" |
