# ScoreDescriptor Schema Reference

Version: 1.0
Scope: Canonical definition of the `ScoreDescriptor` object produced by the automated score analyser.
This file serves as developer documentation AND as system-prompt context for an LLM-based descriptor generator.

A `ScoreDescriptor` is a JSON-serialisable dictionary. Every field is described with its type,
permitted values, and the detection method used to populate it.

---

## Top-Level Structure

```
ScoreDescriptor
├── metadata
├── basic_structure
├── key_and_harmony
├── texture
├── form
├── voice_ranges
├── lyrics
├── difficulty
└── narrative_description
```

---

## Section: `metadata`

Human-supplied or file-derived. Not computed algorithmically.

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `title` | string\|null | REQUIRED | Title as found in score metadata or filename | `"Missa Brevis"` |
| `composer` | string\|null | REQUIRED | Composer full name | `"Palestrina, Giovanni Pierluigi da"` |
| `lyricist` | string\|null | OPTIONAL | Author of the text if different from composer | `"Kochanowski, Jan"` |
| `year` | integer\|null | OPTIONAL | Year of composition | `1594` |
| `source_file` | string | REQUIRED | Absolute or relative path to the analysed file | `"data/uploads/missa.xml"` |

Detection: `score.metadata.title`, `.composer`, `.date` from music21; fall back to filename parsing.

---

## Section: `basic_structure`

| Field | Type | Required | Description | Permitted Values |
|-------|------|----------|-------------|-----------------|
| `voice_count` | integer | REQUIRED | Number of distinct parts (staves) | 1 – 16 |
| `voice_names` | list[string] | REQUIRED | Part names in score order | `["Soprano", "Alto", "Tenor", "Bass"]` |
| `measure_count` | integer | REQUIRED | Total measures; pickup counted as measure 0 | ≥ 1 |
| `time_signatures` | list[string] | REQUIRED | All distinct time signatures in order of appearance | `["4/4"]`, `["6/8", "3/4"]` |
| `tempo_marking` | string\|null | OPTIONAL | Tempo direction or metronome mark as written | `"Andante"`, `"♩ = 72"` |
| `has_pickup_measure` | boolean | REQUIRED | True if first measure is a pickup (anacrusis) | `true`, `false` |
| `total_duration_beats` | float | REQUIRED | Total length in quarter-note beats | `128.0` |

Detection:
- `voice_count`: `len(score.parts)`
- `voice_names`: `part.partName` for each part
- `measure_count`: `len(score.parts[0].getElementsByClass('Measure'))`
- `time_signatures`: iterate all measures, record new `TimeSignature` elements
- `has_pickup_measure`: `measure[0].duration.quarterLength < timeSignature.barDuration.quarterLength`
- `total_duration_beats`: `score.duration.quarterLength`

---

## Section: `key_and_harmony`

See `harmony_analysis_reference.md` for full algorithmic detail.

| Field | Type | Required | Description | Permitted Values |
|-------|------|----------|-------------|-----------------|
| `detected_key` | string | REQUIRED | Primary key in format `"<pitch> <mode>"` | `"C major"`, `"a minor"`, `"D Dorian"` |
| `key_confidence` | float | REQUIRED | Algorithm confidence; 0.0–1.0 | 0.0 – 1.0 |
| `mode` | string | REQUIRED | Tonal / modal classification | `"major"`, `"minor"`, `"modal"`, `"chromatic"`, `"atonal"` |
| `modulations` | list[string] | REQUIRED | Ordered key areas with measure ranges; first = home key | `["G major (mm. 1–16)", "D major (mm. 17–24)"]` |
| `harmony_epoch` | string | REQUIRED | Estimated harmonic style period | `"medieval"`, `"renaissance"`, `"baroque"`, `"classical"`, `"romantic"`, `"contemporary"` |
| `chromatic_complexity` | float | REQUIRED | Duration-weighted fraction of non-diatonic notes | 0.0 – 1.0 |
| `harmonic_rhythm` | string | REQUIRED | Coarse chord-change rate descriptor | `"slow"`, `"moderate"`, `"fast"`, `"irregular"` |
| `chord_vocabulary` | list[string] | REQUIRED | Unique chord types found (Roman numerals or names) | `["I", "ii", "IV", "V", "V7", "vi"]` |

**`harmony_epoch` decision thresholds**:

| `chromatic_complexity` | Dominant-7th present | Parallel-5th rate | Assigned Epoch |
|------------------------|---------------------|-------------------|---------------|
| < 0.03 | Absent | > 0.05 | `"medieval"` |
| 0.03 – 0.08 | Rare | 0.01 – 0.05 | `"renaissance"` |
| 0.05 – 0.12 | Common | < 0.01 | `"baroque"` or `"classical"` |
| 0.08 – 0.12 + cadential 6-4 | Very common | < 0.01 | `"classical"` |
| 0.15 – 0.35 | Common + 9ths | < 0.01 | `"romantic"` |
| > 0.30 | Absent or quartal | — | `"contemporary"` |

When ranges overlap, use chord vocabulary and voice-leading rules as tiebreakers.

---

## Section: `texture`

See `choral_music_taxonomy.md §2` for classification criteria.

| Field | Type | Required | Description | Permitted Values |
|-------|------|----------|-------------|-----------------|
| `texture_type` | string | REQUIRED | Primary texture classification | `"monophonic"`, `"homophonic_chorale"`, `"homophonic_melody"`, `"polyphonic_imitative"`, `"polyphonic_free"`, `"heterophonic"` |
| `rhythmic_variance` | float | REQUIRED | Std dev of onset-count sequences across parts (normalised) | 0.0 – ~5.0 |
| `onset_simultaneity` | float | REQUIRED | Fraction of beats where all active parts attack simultaneously | 0.0 – 1.0 |
| `voice_independence` | float | REQUIRED | 1 – `onset_simultaneity` | 0.0 – 1.0 |

**Texture classification decision table**:

| `onset_simultaneity` | `rhythmic_variance` | `texture_type` |
|---------------------|--------------------|--------------------|
| N/A (1 part) | N/A | `"monophonic"` |
| > 0.85 | < 0.10 | `"homophonic_chorale"` |
| 0.50 – 0.85 | 0.10 – 0.35 | `"homophonic_melody"` |
| < 0.50, shared theme | > 0.35 | `"polyphonic_imitative"` |
| < 0.40, no shared theme | > 0.40 | `"polyphonic_free"` |
| 0.40 – 0.70, high pitch correlation | 0.15 – 0.35 | `"heterophonic"` |

**Invariant**: `onset_simultaneity + voice_independence = 1.0` (within float precision ±0.001).

---

## Section: `form`

See `choral_music_taxonomy.md §3` for form type definitions and detection signals.

| Field | Type | Required | Description | Permitted Values |
|-------|------|----------|-------------|-----------------|
| `form_type` | string | REQUIRED | Primary formal classification | `"strophic"`, `"through_composed"`, `"binary"`, `"ternary"`, `"rondo"`, `"canon"`, `"fugue"`, `"motet"`, `"anthem"`, `"cantus_firmus"`, `"ostinato"`, `"verse_refrain"`, `"unknown"` |
| `has_repetition` | boolean | REQUIRED | True if any full section (≥ 4 measures) is substantially repeated | `true`, `false` |
| `section_count` | integer | REQUIRED | Number of distinct formal sections detected | 1 – N |
| `has_imitation` | boolean | REQUIRED | True if any imitative passage is detected | `true`, `false` |
| `is_canon` | boolean | REQUIRED | True if the whole piece or movement is a strict canon | `true`, `false` |
| `canon_interval` | string\|null | REQUIRED | If `is_canon`: pitch and time interval of imitation | `"P8 / 2 beats"`, `null` |

**Invariant**: if `is_canon` is `true`, then `canon_interval` must be a non-null string.

---

## Section: `voice_ranges`

### Per-Voice Sub-object

For each voice in `voice_names`:

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `name` | string | REQUIRED | Part name matching `basic_structure.voice_names` | `"Soprano"` |
| `lowest_pitch` | string | REQUIRED | Lowest sounding pitch in scientific notation | `"G3"` |
| `highest_pitch` | string | REQUIRED | Highest sounding pitch in scientific notation | `"B4"` |
| `range_semitones` | integer | REQUIRED | Chromatic span from lowest to highest | `16` |
| `tessitura_center` | string | REQUIRED | Pitch closest to duration-weighted mean MIDI pitch | `"E4"` |

Detection: `part.analyze('ambitus')` → `Ambitus` interval; convert with `pitch.nameWithOctave`.

### Inter-Voice Counterpoint Metrics (global)

| Field | Type | Required | Ideal Value | Description |
|-------|------|----------|-------------|-------------|
| `parallel_fifths_count` | integer | REQUIRED | 0 | Total parallel perfect fifths between any pair of voices |
| `parallel_octaves_count` | integer | REQUIRED | 0 | Total parallel octaves between any pair of voices |
| `voice_crossings_count` | integer | REQUIRED | 0 | Total voice crossing events |
| `contrary_motion_ratio` | float | REQUIRED | > 0.40 | Fraction of voice-pair transitions in contrary motion |

**Invariant**: `len(voice_ranges.voices)` equals `basic_structure.voice_count`.

---

## Section: `lyrics`

| Field | Type | Required | Description | Permitted Values |
|-------|------|----------|-------------|-----------------|
| `has_lyrics` | boolean | REQUIRED | True if any lyrics are attached to notes | `true`, `false` |
| `lyrics_language` | string\|null | REQUIRED | ISO 639-1 code of detected language | `"la"`, `"pl"`, `"de"`, `"en"`, `"cs"`, `"it"`, `"fr"`, `"el"`, `"he"`, `null` |
| `language_confidence` | float\|null | REQUIRED | Confidence of language detection | 0.0 – 1.0; `null` if no lyrics |
| `text_setting_type` | string\|null | REQUIRED | Note-to-syllable ratio style | `"syllabic"`, `"neumatic"`, `"melismatic"`, `null` |
| `notes_per_syllable_avg` | float\|null | REQUIRED | Mean notes per lyric syllable | ≥ 1.0; `null` if no lyrics |
| `has_word_painting` | boolean\|null | OPTIONAL | Whether Tonmalerei was detected | `true`, `false`, `null` (null = undetermined) |

**Invariants**:
- If `has_lyrics` is `false`, then `lyrics_language`, `language_confidence`, `text_setting_type`, and `notes_per_syllable_avg` must all be `null`.
- `language_confidence` must be in [0.0, 1.0] when not null.

Detection: `note.lyric` on all notes; language by keyword matching (see `choral_music_taxonomy.md §8`).

---

## Section: `difficulty`

See `choral_music_taxonomy.md §7` for the full NYSSMA 1–6 grading criteria.

| Field | Type | Required | Description | Permitted Values |
|-------|------|----------|-------------|-----------------|
| `estimated_grade` | integer | REQUIRED | Overall NYSSMA-style difficulty grade | 1, 2, 3, 4, 5, 6 |
| `grade_label` | string | REQUIRED | Human-readable label | `"elementary"`, `"intermediate"`, `"advanced"` |
| `difficulty_factors` | list[string] | REQUIRED | Specific factors that raised the estimate | See token list below |

**Permitted `difficulty_factors` tokens**:

| Token | Meaning |
|-------|---------|
| `wide_range` | Any voice spans > 20 semitones |
| `extreme_high` | Soprano or Tenor must sustain above comfortable tessitura |
| `extreme_low` | Bass or Alto must sustain below comfortable tessitura |
| `complex_rhythm` | Dotted rhythms, syncopation, or cross-rhythm between voices |
| `compound_meter` | Time signature is compound (6/8, 9/8, 12/8) |
| `polyrhythm` | Two or more simultaneous metre patterns |
| `chromatic_harmony` | `chromatic_complexity` > 0.20 |
| `distant_modulations` | Any modulation by tritone or chromatic mediant |
| `many_key_areas` | More than 4 distinct key areas |
| `polyphonic_independence` | `voice_independence` > 0.70 |
| `stretto` | Fugue subject entries overlap |
| `extended_tessitura` | Tessitura centre outside normal range for voice type |
| `many_sharps_flats` | Key signature with > 3 sharps or flats |
| `a_cappella` | No instrumental accompaniment (increases difficulty) |
| `unusual_time_signature` | Non-standard meter (5/4, 7/8, mixed) |
| `long_work` | More than 48 measures |
| `voice_leading_complexity` | More than 3 parallel fifths detected |
| `four_or_more_voices` | Four or more independent voice parts |

**Scoring algorithm**:
1. Score each sub-scale 1–6: range (25%), rhythm (20%), harmony (20%), key signatures (15%), voice independence (20%).
2. Weighted average rounded to nearest integer, clamped to [1, 6].
3. Append factor tokens for any sub-scale scoring ≥ 2 points above the weighted mean.

---

## Section: `narrative_description`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `narrative_description` | string | REQUIRED | Auto-generated human-readable paragraph for a choir director or librarian |

**Format requirements**:
- One paragraph, 3–6 sentences, approximately 80–150 words.
- Must reference: key, texture type, form, epoch, language (if present), and difficulty grade.
- Written in English.
- Must not introduce information not derivable from other `ScoreDescriptor` fields.

**Example**:
> "This four-voice SATB piece in F major (Renaissance, grade 5) uses imitative polyphonic texture, each voice entering successively with the same theme in the style of a motet. The harmonic language is nearly diatonic (chromatic complexity 0.04) with slow harmonic rhythm and modal cadences consistent with sixteenth-century Renaissance counterpoint. The Latin text is set neümatically with approximately 2.8 notes per syllable. High voice independence (0.69) and full SATB ranges place this piece at grade 5, requiring advanced choral singers. No parallel fifths or octaves were detected, reflecting careful Palestrina-style voice leading."

---

## Full Example ScoreDescriptor (JSON)

```json
{
  "metadata": {
    "title": "Adoramus Te Christe",
    "composer": "Palestrina, Giovanni Pierluigi da",
    "lyricist": null,
    "year": 1575,
    "source_file": "data/uploads/adoramus_te.xml"
  },
  "basic_structure": {
    "voice_count": 4,
    "voice_names": ["Soprano", "Alto", "Tenore", "Basso"],
    "measure_count": 32,
    "time_signatures": ["4/4"],
    "tempo_marking": null,
    "has_pickup_measure": false,
    "total_duration_beats": 128.0
  },
  "key_and_harmony": {
    "detected_key": "F Lydian",
    "key_confidence": 0.82,
    "mode": "modal",
    "modulations": ["F Lydian (mm. 1-32)"],
    "harmony_epoch": "renaissance",
    "chromatic_complexity": 0.04,
    "harmonic_rhythm": "slow",
    "chord_vocabulary": ["I", "II", "IV", "V", "vi", "VII"]
  },
  "texture": {
    "texture_type": "polyphonic_imitative",
    "rhythmic_variance": 0.52,
    "onset_simultaneity": 0.31,
    "voice_independence": 0.69
  },
  "form": {
    "form_type": "motet",
    "has_repetition": false,
    "section_count": 3,
    "has_imitation": true,
    "is_canon": false,
    "canon_interval": null
  },
  "voice_ranges": {
    "voices": [
      {"name": "Soprano", "lowest_pitch": "C4", "highest_pitch": "G5", "range_semitones": 19, "tessitura_center": "E4"},
      {"name": "Alto",    "lowest_pitch": "G3", "highest_pitch": "D5", "range_semitones": 19, "tessitura_center": "B3"},
      {"name": "Tenore",  "lowest_pitch": "C3", "highest_pitch": "G4", "range_semitones": 19, "tessitura_center": "E3"},
      {"name": "Basso",   "lowest_pitch": "F2", "highest_pitch": "C4", "range_semitones": 19, "tessitura_center": "A2"}
    ],
    "parallel_fifths_count": 0,
    "parallel_octaves_count": 0,
    "voice_crossings_count": 2,
    "contrary_motion_ratio": 0.58
  },
  "lyrics": {
    "has_lyrics": true,
    "lyrics_language": "la",
    "language_confidence": 0.97,
    "text_setting_type": "neumatic",
    "notes_per_syllable_avg": 2.8,
    "has_word_painting": null
  },
  "difficulty": {
    "estimated_grade": 5,
    "grade_label": "advanced",
    "difficulty_factors": ["polyphonic_independence", "extended_tessitura", "a_cappella"]
  },
  "narrative_description": "This SATB Renaissance motet in F Lydian mode features imitative polyphony across four independent voices, typical of the Palestrina style. The harmonic language is nearly diatonic (chromatic complexity 0.04) with slow harmonic rhythm and no functional dominant seventh chords, consistent with Renaissance modal counterpoint. Three imitative sections set the Latin text with neumatic inflections averaging 2.8 notes per syllable. Voice independence is high (0.69), requiring each section to sustain independent melodic lines, placing this piece at grade 5. No parallel fifths or octaves were detected, and the contrary motion ratio of 0.58 confirms the careful voice-leading discipline expected in this style."
}
```

---

## Validation Invariants

The following must hold for every valid `ScoreDescriptor`:

1. `voice_count == len(voice_names) == len(voice_ranges.voices)`
2. If `has_lyrics == false`: `lyrics_language`, `language_confidence`, `text_setting_type`, `notes_per_syllable_avg` are all `null`
3. If `is_canon == true`: `canon_interval` is a non-null string
4. `key_confidence ∈ [0.0, 1.0]`
5. `chromatic_complexity ∈ [0.0, 1.0]`
6. `onset_simultaneity + voice_independence == 1.0` (±0.001)
7. `estimated_grade ∈ {1, 2, 3, 4, 5, 6}`
8. `harmony_epoch ∈ {"medieval", "renaissance", "baroque", "classical", "romantic", "contemporary"}`
9. All pitch strings match pattern `[A-G][#b-]?[0-9]` (scientific notation)
10. `section_count >= 1`
