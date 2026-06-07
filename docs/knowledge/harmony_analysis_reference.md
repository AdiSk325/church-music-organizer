# Harmony Analysis Reference

Version: 1.0
Scope: Algorithmic reference for the Church Music Organizer score analyser.
All music21 API references target music21 version 9.x+.

---

## 1. Key Detection Methods

### 1.1 Algorithm Comparison Table

| Algorithm | music21 Call | Best For | Typical Error | Notes |
|-----------|-------------|----------|--------------|-------|
| AardenEssen | `score.analyze('key')` (default) | General tonal music (Classical, Romantic) | ±1 semitone | Best starting point; uses weighted duration |
| KrumhanslSchmuckler | `key.KrumhanslSchmuckler()` | Baroque, Renaissance; modal ambiguity | ±2 semitones | Probe-tone correlation; less good with chromaticism |
| TemperleyKostkaPayne | `key.TemperleyKostkaPayne()` | Major key identification, Classical | ±1 semitone | Optimised for common-practice major tonality |
| SimpleWeights | `key.SimpleWeights()` | Quick pass; checking for mode (major/minor) | ±2 semitones | Fastest; usable for batch pre-screening |
| BellmanBudge | `key.BellmanBudge()` | Mixed-mode and ambiguous tonal centres | ±2 semitones | Alternative to KS for edge cases |

### 1.2 Recommended Two-Pass Strategy

1. Run `AardenEssen` as the primary detector.
2. If `chromatic_complexity` > 0.08 (see §2), cross-check with `KrumhanslSchmuckler`.
3. If the two agree within a minor second → accept `AardenEssen`; set `key_confidence` to its `correlationCoefficient`.
4. If they disagree by more than a minor second → flag `key_confidence < 0.60` and record both candidates.
5. For modal pieces (Gregorian, Renaissance): test all eight church modes against the pitch-class distribution and select the highest cosine-similarity mode.

### 1.3 Modal Detection

For modal (non-tonal) music:

- Extract duration-weighted pitch-class histogram (12 bins).
- Build ideal mode templates: scale tones → 1.0, non-scale tones → 0.0, weighted by tonal function.
- Compute cosine similarity between histogram and each mode template.
- Best-matching mode → `detected_key = "<final_pitch> <mode_name>"`, e.g. `"D Dorian"`.
- `mode` field = `"modal"`; similarity score → `key_confidence`.

### 1.4 Church Mode Templates

| Mode | Scale Tones (relative to final) | Characteristic Interval |
|------|--------------------------------|------------------------|
| Dorian | 0, 2, 3, 5, 7, 9, 10 | Minor 6th |
| Phrygian | 0, 1, 3, 5, 7, 8, 10 | Minor 2nd |
| Lydian | 0, 2, 4, 6, 7, 9, 11 | Augmented 4th |
| Mixolydian | 0, 2, 4, 5, 7, 9, 10 | Minor 7th |
| Aeolian (natural minor) | 0, 2, 3, 5, 7, 8, 10 | Minor 6th + 7th |
| Ionian (major) | 0, 2, 4, 5, 7, 9, 11 | Leading tone |

---

## 2. Chromatic Complexity Metrics

### 2.1 Chromatic Pitch Saturation

**Definition**: fraction of all notes (duration-weighted) that are chromatic — i.e. carry an accidental not native to the prevailing key.

**Formula**:
```
chromatic_complexity = Σ(duration_chromatic_notes) / Σ(duration_all_notes)
```

**Reference scale**:

| Chromatic Complexity | Style Classification | Typical Repertoire |
|---------------------|---------------------|-------------------|
| 0.00 – 0.03 | Modal / diatonic | Gregorian chant, simple unison hymns |
| 0.03 – 0.08 | Mildly chromatic | Renaissance polyphony, folk hymns |
| 0.08 – 0.15 | Moderately chromatic | Baroque chorales (Bach), Classical anthems |
| 0.15 – 0.25 | Chromatic | Early Romantic, Schubert sacred music |
| 0.25 – 0.40 | Highly chromatic | Late Romantic, Wagner-influenced choral |
| 0.40 – 1.00 | Post-tonal / atonal | Contemporary, Penderecki, twelve-tone |

### 2.2 Computation with music21

- `notes = score.flatten().notes` — all note objects.
- For each note, extract pitch-class name; test against the detected key's `pitches`.
- Weight by `note.duration.quarterLength`; exclude grace notes (duration = 0).
- Accidentals caused by key signature are **not** chromatic; only written accidentals on non-scale pitches count.

### 2.3 Secondary Chromatic Metrics

| Metric | Formula | Significance |
|--------|---------|-------------|
| Accidental density | count(notes with accidental) / total_notes | Simple proxy; no duration weighting |
| Chromatic voice leading | count(half-step melodic moves) / count(all melodic intervals) | High in Romantic chromatic writing |
| Enharmonic modulation indicator | count(key-area transitions > tritone) / key_areas | > 0 flags Romantic enharmonic practice |

---

## 3. Harmonic Rhythm Analysis

### 3.1 Chord Change Rate per Measure

| Rate | Classification | Typical Style |
|------|---------------|--------------|
| < 0.5 changes/measure | Very slow | Pedal points, Gregorian, ostinato |
| 0.5 – 1.5 changes/measure | Slow | Baroque chorale |
| 1.5 – 3.0 changes/measure | Moderate | Classical |
| 3.0 – 6.0 changes/measure | Fast | Romantic |
| > 6.0 changes/measure | Irregular | Contemporary, jazz-influenced |

### 3.2 Computation

1. `chords = score.chordify().flatten().getElementsByClass('Chord')` — produces one chord stream.
2. Count total distinct chord-onset events; divide by measure count.
3. Also compute variance of inter-chord intervals: high variance = irregular harmonic rhythm.

### 3.3 Harmonic Rhythm Contour

- Accelerating harmonic rhythm toward cadence points → Classical / Romantic trait.
- Constant harmonic rhythm throughout → Baroque chorales, Renaissance polyphony.
- Compare rates in first-quarter vs. last-quarter of piece to detect acceleration.

---

## 4. Chord Vocabulary Analysis

### 4.1 Chord Type → Style Mapping

| Chord Type | Presence Suggests | Absence Suggests |
|-----------|------------------|-----------------|
| Root-position triads only | Renaissance, early Classical | — |
| First inversion triads (I6, IV6) | Baroque, Classical (smooth bass) | Strict modal writing |
| Cadential 6-4 (I6/4) | Classical, Romantic | Pre-Classical |
| Dominant seventh (V7) | Baroque–present; ubiquitous | Modal / Medieval |
| Leading-tone seventh (vii°7) | Baroque, Classical | Modal |
| Non-dominant sevenths (ii7, IV7) | Romantic and later | Pre-Romantic |
| Neapolitan sixth (♭II6) | Classical, Romantic | Baroque, Renaissance |
| Augmented sixth (It+6, Fr+6, Ger+6) | Classical, Romantic | Pre-Classical |
| Ninth / eleventh chords (V9, ii9) | Romantic and later | Classical and earlier |
| Quartal / quintal stacks | Contemporary | Tonal |

### 4.2 Style Fingerprinting Summary

| Epoch | Chord Vocabulary Signature |
|-------|--------------------------|
| Medieval | Perfect intervals preferred; triadic sonorities at cadences only |
| Renaissance | Triads only; no V7 as functional chord; modal cadences |
| Baroque | V7 at every phrase; vii°7 common; 6-3 and 6-4 realisations |
| Classical | Cadential 6-4 standard; Neapolitan and Aug-6th introduced |
| Romantic | Non-dominant 7ths, 9ths, augmented triads, altered dominants |
| Contemporary | Quartal/quintal, polychords, no functional progression |

### 4.3 Detection Heuristics

1. `chords = score.chordify()`
2. For each chord: `roman.romanNumeralFromChord(chord, key_object)` → Roman numeral string.
3. Build frequency distribution of chord types.
4. Quartal sonority test: if > 50% of intervals in a chord are P4 or P5 → flag as quartal.

---

## 5. Voice Leading Quality Metrics

### 5.1 Metrics and Thresholds

| Metric | Formula | Ideal | Poor | Significance |
|--------|---------|-------|------|-------------|
| Parallel 5th rate | P5→P5_count / consecutive_pairs | 0.00 | > 0.05 | Banned in Renaissance/Baroque theory |
| Parallel octave rate | P8→P8_count / consecutive_pairs | 0.00 | > 0.03 | Same period restrictions |
| Voice crossing rate | crossings / consecutive_pairs | 0.00 | > 0.10 | Poor arrangement or unusual style |
| Contrary motion ratio | contrary_pairs / total_pairs | > 0.50 | < 0.20 | Higher = more sophisticated counterpoint |
| Average stepwise motion | step_moves / all_melodic_intervals | > 0.60 | < 0.40 | Steps preferred for singability |
| Average interval size (st) | Σ(semitones) / count(intervals) | 2.0 – 3.5 | > 6 | Leaps > P5 are vocally difficult |
| Large leap rate | count(leaps > P5) / all_intervals | < 0.05 | > 0.15 | High = instrumentally conceived writing |

### 5.2 Parallel Motion Detection (music21)

```python
from music21.voiceLeading import VoiceLeadingQuartet

vlq = VoiceLeadingQuartet(note1_upper, note2_upper, note1_lower, note2_lower)
vlq.parallelFifth()   # True if parallel P5
vlq.parallelOctave()  # True if parallel P8
vlq.voiceCrossing()   # True if voices cross
vlq.contraryMotion()  # True if contrary motion
```

Iterate adjacent-voice pairs (S-A, A-T, T-B) across consecutive note pairs.

### 5.3 Contrary Motion Ratio Computation

- At each beat transition, compute direction for each active voice: up (+1), down (−1), same (0).
- A voice pair is contrary if one = +1 and the other = −1.
- `contrary_motion_ratio = contrary_pairs / (active_pairs × transitions)`.

### 5.4 Voice Crossing Detection

At each beat: `assert pitch_S >= pitch_A >= pitch_T >= pitch_B` (MIDI comparison).
Any violation = 1 crossing event.

---

## 6. Modulation Detection

### 6.1 Key Area Identification Algorithm

1. Divide the score into overlapping windows of 4 measures (stride = 2 measures).
2. Run `AardenEssen` on each window.
3. Merge consecutive windows with the same key result.
4. Minimum stable key area: 2 measures (shorter spans = tonicisations, not modulations).
5. Record each area as `(key_name, start_measure, end_measure)`.

### 6.2 Modulation Distance Classification

| Interval Between Keys | Classification | Style Context |
|----------------------|---------------|--------------|
| P5 or P4 (dominant/subdominant) | Closely related | All tonal epochs |
| m3 or M3 (relative/parallel minor-major) | Common | Classical, Baroque |
| M3 or m6 (chromatic mediant) | Distant | Romantic |
| Tritone (A4 / d5) | Very distant; enharmonic | Late Romantic, Contemporary |
| Direct (no common chord) | Knife-edge / surprise | Contemporary |

### 6.3 Pivot Chord vs. Direct Modulation

- **Pivot chord**: last chord before new key functions diatonically in both old and new key.
  - Test: `romanNumeralFromChord(chord, old_key)` AND `romanNumeralFromChord(chord, new_key)` both return a diatonic function.
- **Direct modulation**: first chord of new key area is non-diatonic in old key.

### 6.4 Tonicisation vs. Modulation

| | Tonicisation | Modulation |
|---|---|---|
| Duration | < 2 measures | ≥ 2 measures |
| Ends with cadence in new key | No | Yes (authentic cadence) |
| Recorded in `modulations` field | No | Yes |

### 6.5 `modulations` Field Format

- First entry: home key spanning full piece (or first stable section).
- Subsequent entries: `"<key_name> (mm. <start>–<end>)"`.
- Example: `["C major (mm. 1–24)", "G major (mm. 25–32)", "a minor (mm. 33–40)", "C major (mm. 41–56)"]`.
