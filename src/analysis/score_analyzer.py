"""Main score analysis engine — produces a ScoreDescriptor from a music21 Score."""

import logging
import re
import statistics
from collections import Counter
from typing import List, Optional, Tuple

from music21 import analysis, chord, interval, key, meter, note, stream, tempo

from src.analysis.score_descriptor import ScoreDescriptor, VoiceRange

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language detection — heuristic keyword approach for liturgical music
# ---------------------------------------------------------------------------

_LANGUAGE_PROFILES = {
    "la": {  # Latin
        "keywords": {
            "kyrie", "eleison", "christe", "gloria", "sanctus", "dominus",
            "agnus", "dei", "miserere", "nobis", "dona", "pacem", "credo",
            "deus", "jesu", "ave", "maria", "alleluia", "amen", "pater",
            "noster", "lux", "aeterna", "requiem", "et", "in", "cum",
            "spiritu", "benedictus", "hosanna", "excelsis", "magnificat",
        },
        "char_pattern": r"[aeiou]{2,}",  # Latin has many vowel clusters
    },
    "pl": {  # Polish
        "keywords": {
            "boże", "panie", "jezu", "chryste", "niebo", "ziemia", "święty",
            "chwała", "błogosławiony", "alleluja", "amen", "przyjdź", "królestwo",
            "miłość", "wiara", "nadzieja", "zbawienie", "kościół", "który",
            "mój", "nasz", "twój", "jest", "się", "nie", "jak",
        },
        "char_pattern": r"[ąęóśźżćń]",
    },
    "de": {  # German
        "keywords": {
            "herr", "gott", "heilig", "ehre", "preis", "amen", "halleluja",
            "freude", "liebe", "gnade", "heil", "erlösung", "seele",
            "und", "der", "die", "das", "ist", "ich", "wir",
        },
        "char_pattern": r"[äöüß]",
    },
    "en": {  # English
        "keywords": {
            "lord", "god", "holy", "glory", "praise", "amen", "alleluia",
            "love", "grace", "salvation", "blessed", "heaven", "earth",
            "the", "and", "is", "we", "our", "thy", "thee", "thou",
        },
        "char_pattern": r"\bthe\b",
    },
    "cs": {  # Czech
        "keywords": {
            "bože", "pane", "ježíši", "kříste", "sláva", "haleluja",
            "amen", "láska", "víra", "naděje", "spasení",
            "který", "naše", "tvoje", "jsme",
        },
        "char_pattern": r"[áéíóúůýčďěňřšťž]",
    },
    "it": {  # Italian
        "keywords": {
            "signore", "dio", "gesù", "cristo", "gloria", "alleluia",
            "amen", "pace", "grazia", "salvezza", "benedetto",
            "il", "la", "di", "che", "non", "per", "una",
        },
        "char_pattern": r"\b(il|la|di|che)\b",
    },
    "fr": {  # French
        "keywords": {
            "seigneur", "dieu", "jésus", "christ", "gloire", "alléluia",
            "amen", "amour", "grâce", "salut", "béni",
            "le", "la", "les", "de", "du", "et", "est",
        },
        "char_pattern": r"[àâæçèêëîïôœùûü]",
    },
}


def _detect_language(text: str) -> Tuple[str, float]:
    """Return (iso_code, confidence) for the given lyrics text."""
    if not text.strip():
        return ("unknown", 0.0)

    words = set(re.findall(r"\b[a-zA-Ząęóśźżćńäöüßáéíúůýčďěňřšťžàâæçèêëîïôœùûüñ]+\b", text.lower()))

    scores: dict[str, float] = {}
    for lang, profile in _LANGUAGE_PROFILES.items():
        keyword_hits = len(words & profile["keywords"])
        char_hits = len(re.findall(profile["char_pattern"], text.lower()))
        scores[lang] = keyword_hits * 2.0 + char_hits * 0.5

    if not any(scores.values()):
        return ("unknown", 0.0)

    best_lang = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = scores[best_lang] / total if total > 0 else 0.0
    return (best_lang, round(confidence, 2))


# ---------------------------------------------------------------------------
# Voice range analysis
# ---------------------------------------------------------------------------

_SATB_EXPECTED = {
    "soprano": ("C4", "C6"),
    "alto": ("F3", "F5"),
    "tenor": ("C3", "C5"),
    "bass": ("E2", "E4"),
}


def _pitch_to_midi(pitch_str: str) -> int:
    from music21 import pitch as p21
    return int(p21.Pitch(pitch_str).ps)


def _midi_to_pitch(midi: int) -> str:
    from music21 import pitch as p21
    return str(p21.Pitch(midi).nameWithOctave)


def _analyze_voice_range(part: stream.Part) -> VoiceRange:
    pitches = [n.pitch for n in part.flatten().notes if hasattr(n, "pitch")]
    if not pitches:
        return VoiceRange(
            name=part.partName or "Unknown",
            lowest_pitch="?",
            highest_pitch="?",
            range_semitones=0,
            tessitura_center="?",
        )

    midi_vals = [int(p.ps) for p in pitches]
    lo, hi = min(midi_vals), max(midi_vals)
    center = _midi_to_pitch(int((lo + hi) / 2))
    return VoiceRange(
        name=part.partName or "Part",
        lowest_pitch=_midi_to_pitch(lo),
        highest_pitch=_midi_to_pitch(hi),
        range_semitones=hi - lo,
        tessitura_center=center,
    )


# ---------------------------------------------------------------------------
# Texture classification
# ---------------------------------------------------------------------------

def _compute_texture(score: stream.Score) -> Tuple[str, float, float, float]:
    """Return (texture_type, rhythmic_variance, onset_simultaneity, voice_independence)."""
    parts = list(score.parts)
    if len(parts) <= 1:
        return ("monophonic", 0.0, 1.0, 0.0)

    # Build per-part onset sets (offset → pitch)
    part_onsets: List[set] = []
    for part in parts:
        onsets = set()
        for n in part.flatten().notes:
            onsets.add(round(float(n.offset), 3))
        part_onsets.append(onsets)

    # Onset simultaneity: fraction of onsets that occur in ALL parts simultaneously
    if not part_onsets:
        return ("monophonic", 0.0, 1.0, 0.0)

    all_onsets = set().union(*part_onsets)
    if not all_onsets:
        return ("monophonic", 0.0, 1.0, 0.0)

    simultaneous = sum(
        1 for o in all_onsets if all(o in p for p in part_onsets)
    )
    simultaneity = simultaneous / len(all_onsets)

    # Rhythmic variance: std dev of onset counts across parts (normalised)
    onset_counts = [len(p) for p in part_onsets if p]
    if len(onset_counts) > 1:
        rhythmic_variance = statistics.stdev(onset_counts) / (max(onset_counts) + 1)
    else:
        rhythmic_variance = 0.0

    voice_independence = 1.0 - simultaneity

    # Classify
    if simultaneity > 0.85:
        texture_type = "homophonic_chorale"
    elif simultaneity > 0.60:
        texture_type = "homophonic_melody"
    elif rhythmic_variance > 0.3:
        texture_type = "polyphonic_free"
    else:
        texture_type = "polyphonic_imitative"

    return (texture_type, round(rhythmic_variance, 3), round(simultaneity, 3), round(voice_independence, 3))


# ---------------------------------------------------------------------------
# Voice leading quality
# ---------------------------------------------------------------------------

def _analyze_voice_leading(score: stream.Score) -> Tuple[int, int, int, float]:
    """Return (parallel_5ths, parallel_8vas, crossings, contrary_ratio)."""
    from music21.voiceLeading import VoiceLeadingQuartet

    parts = list(score.parts)
    if len(parts) < 2:
        return (0, 0, 0, 0.0)

    parallel_5ths = 0
    parallel_8vas = 0
    crossings = 0
    contrary_count = 0
    total_transitions = 0

    # Analyse adjacent-voice pairs (S-A, A-T, T-B)
    for i in range(len(parts) - 1):
        notes_upper = [n for n in parts[i].flatten().notes if isinstance(n, note.Note)]
        notes_lower = [n for n in parts[i + 1].flatten().notes if isinstance(n, note.Note)]
        paired = list(zip(notes_upper, notes_lower))

        for j in range(len(paired) - 1):
            u1, l1 = paired[j]
            u2, l2 = paired[j + 1]
            try:
                vlq = VoiceLeadingQuartet(u1, u2, l1, l2)
                if vlq.parallelFifth():
                    parallel_5ths += 1
                if vlq.parallelOctave():
                    parallel_8vas += 1
                if vlq.voiceCrossing():
                    crossings += 1
                if vlq.contraryMotion():
                    contrary_count += 1
                total_transitions += 1
            except Exception:
                pass

    contrary_ratio = contrary_count / total_transitions if total_transitions > 0 else 0.0
    return (parallel_5ths, parallel_8vas, crossings, round(contrary_ratio, 3))


# ---------------------------------------------------------------------------
# Harmonic analysis
# ---------------------------------------------------------------------------

def _analyze_harmony(score: stream.Score) -> Tuple[Optional[str], float, Optional[str], float, Optional[str], List[str]]:
    """Return (key_name, confidence, mode, chromatic_complexity, epoch, chord_types)."""
    try:
        key_result = score.analyze("key")
        key_name = str(key_result)
        confidence = float(key_result.correlationCoefficient) if hasattr(key_result, "correlationCoefficient") else 0.5
        mode = key_result.mode if hasattr(key_result, "mode") else "major"
    except Exception:
        key_name, confidence, mode = None, 0.0, None

    # Chromatic complexity: ratio of non-diatonic pitches
    try:
        key_obj = key_result if key_name else key.Key("C")
        all_notes = [n for n in score.flatten().notes if isinstance(n, note.Note)]
        if all_notes:
            diatonic_scale = set(str(p.name) for p in key_obj.pitches)
            chromatic_count = sum(1 for n in all_notes if n.pitch.name not in diatonic_scale)
            chromatic_complexity = chromatic_count / len(all_notes)
        else:
            chromatic_complexity = 0.0
    except Exception:
        chromatic_complexity = 0.0

    # Chord vocabulary via chordify
    chord_types: List[str] = []
    try:
        chordified = score.chordify()
        for c in chordified.flatten().getElementsByClass(chord.Chord):
            q = c.commonName
            if q and q not in chord_types:
                chord_types.append(q)
        chord_types = chord_types[:20]  # cap for display
    except Exception:
        pass

    # Epoch classification based on chromatic complexity + chord types
    has_7ths = any("seventh" in ct.lower() for ct in chord_types)
    has_9ths = any("ninth" in ct.lower() or "eleventh" in ct.lower() for ct in chord_types)

    if chromatic_complexity < 0.04:
        epoch = "medieval" if not has_7ths else "renaissance"
    elif chromatic_complexity < 0.10:
        epoch = "baroque" if has_7ths else "renaissance"
    elif chromatic_complexity < 0.18:
        epoch = "classical" if not has_9ths else "romantic"
    elif chromatic_complexity < 0.30:
        epoch = "romantic"
    else:
        epoch = "contemporary"

    return (key_name, round(confidence, 3), mode, round(chromatic_complexity, 3), epoch, chord_types)


# ---------------------------------------------------------------------------
# Lyrics extraction
# ---------------------------------------------------------------------------

def _extract_lyrics(score: stream.Score) -> Tuple[bool, str, float, str, float]:
    """Return (has_lyrics, language, lang_confidence, setting_type, notes_per_syllable)."""
    lyrics_text = []
    notes_with_lyrics = 0
    total_notes = 0
    total_syllables = 0

    for n in score.flatten().notes:
        if not isinstance(n, note.Note):
            continue
        total_notes += 1
        if n.lyrics:
            for lyric in n.lyrics:
                if lyric.text:
                    lyrics_text.append(lyric.text)
                    total_syllables += 1
            notes_with_lyrics += 1

    has_lyrics = total_syllables > 0
    if not has_lyrics:
        return (False, "unknown", 0.0, "instrumental", 0.0)

    full_text = " ".join(lyrics_text)
    language, lang_confidence = _detect_language(full_text)

    # notes-per-syllable (approximation: notes with lyrics / total syllable count)
    notes_per_syl = notes_with_lyrics / total_syllables if total_syllables > 0 else 1.0

    if notes_per_syl <= 1.2:
        setting = "syllabic"
    elif notes_per_syl <= 3.0:
        setting = "neumatic"
    else:
        setting = "melismatic"

    return (True, language, lang_confidence, setting, round(notes_per_syl, 2))


# ---------------------------------------------------------------------------
# Harmonic rhythm
# ---------------------------------------------------------------------------

def _harmonic_rhythm(score: stream.Score) -> str:
    try:
        chordified = score.chordify()
        chords = [c for c in chordified.flatten().getElementsByClass(chord.Chord)]
        measures = score.parts[0].getElementsByClass(stream.Measure) if score.parts else []
        n_measures = len(list(measures)) or 1
        chords_per_measure = len(chords) / n_measures
        if chords_per_measure <= 1.5:
            return "slow"
        elif chords_per_measure <= 3.5:
            return "moderate"
        return "fast"
    except Exception:
        return "moderate"


# ---------------------------------------------------------------------------
# Form detection (heuristic)
# ---------------------------------------------------------------------------

def _detect_form(score: stream.Score, voice_count: int) -> Tuple[str, bool, int, bool, bool]:
    """Return (form_type, has_repetition, section_count, has_imitation, is_canon)."""
    # Imitation detection: check if any two parts share a melodic fragment
    # (simplified: compare first 4 notes of each part)
    parts = list(score.parts)
    has_imitation = False
    is_canon = False

    if len(parts) >= 2:
        first_intervals: List[List[int]] = []
        for part in parts:
            ns = [n for n in part.flatten().notes if isinstance(n, note.Note)][:8]
            if len(ns) >= 2:
                ivls = [int(interval.Interval(ns[i], ns[i + 1]).semitones) for i in range(len(ns) - 1)]
                first_intervals.append(ivls)

        # If two parts share the same opening interval sequence (offset by time)
        if len(first_intervals) >= 2:
            for i in range(len(first_intervals)):
                for j in range(i + 1, len(first_intervals)):
                    a, b = first_intervals[i], first_intervals[j]
                    if a and b and a[:4] == b[:4]:
                        has_imitation = True
                        is_canon = True  # simplified: assume imitation = canon
                        break

    # Repetition detection via repeat barlines (music21 Repeat class)
    try:
        repeats = list(score.flatten().getElementsByClass("Repeat"))
        has_repetition = len(repeats) > 0
    except Exception:
        has_repetition = False

    # Section count: count double barlines or rehearsal marks
    try:
        barlines = [b for b in score.flatten().getElementsByClass("Barline") if b.type in ("double", "final")]
        section_count = max(1, len(barlines))
    except Exception:
        section_count = 1

    # Form type heuristic
    if is_canon:
        form_type = "canon"
    elif voice_count == 1:
        form_type = "monophonic"
    elif has_imitation:
        form_type = "fugue" if voice_count >= 3 else "canon"
    elif has_repetition:
        form_type = "strophic"
    elif section_count >= 3:
        form_type = "ternary"
    elif section_count == 2:
        form_type = "binary"
    else:
        form_type = "through_composed"

    return (form_type, has_repetition, section_count, has_imitation, is_canon)


# ---------------------------------------------------------------------------
# Difficulty estimation
# ---------------------------------------------------------------------------

def _estimate_difficulty(
    voice_count: int,
    range_semitones_max: int,
    chromatic_complexity: float,
    voice_independence: float,
    parallel_fifths: int,
    measure_count: int,
) -> Tuple[int, str, List[str]]:
    """Estimate NYSSMA 1-6 difficulty grade."""
    score = 0
    factors = []

    # Voice count
    if voice_count >= 4:
        score += 1
        factors.append("four_or_more_voices")

    # Range difficulty
    if range_semitones_max > 24:
        score += 2
        factors.append("wide_range")
    elif range_semitones_max > 19:
        score += 1
        factors.append("moderate_range")

    # Harmonic complexity
    if chromatic_complexity > 0.25:
        score += 2
        factors.append("high_chromaticism")
    elif chromatic_complexity > 0.12:
        score += 1
        factors.append("moderate_chromaticism")

    # Voice independence (polyphony)
    if voice_independence > 0.6:
        score += 2
        factors.append("high_voice_independence")
    elif voice_independence > 0.3:
        score += 1
        factors.append("moderate_voice_independence")

    # Voice leading issues
    if parallel_fifths > 3:
        score += 1
        factors.append("voice_leading_complexity")

    # Length
    if measure_count > 48:
        score += 1
        factors.append("long_work")

    grade = min(6, max(1, score))
    if grade <= 2:
        label = "elementary"
    elif grade <= 4:
        label = "intermediate"
    else:
        label = "advanced"

    return (grade, label, factors)


# ---------------------------------------------------------------------------
# Narrative generator
# ---------------------------------------------------------------------------

def _build_narrative(d: ScoreDescriptor) -> str:
    parts = []

    title_str = f'"{d.title}"' if d.title else "This work"
    composer_str = f" by {d.composer}" if d.composer else ""
    parts.append(f"{title_str}{composer_str}")

    if d.voice_count and d.voice_names:
        parts.append(
            f"is scored for {d.voice_count} voice{'s' if d.voice_count != 1 else ''}"
            f" ({', '.join(d.voice_names)})"
        )
    elif d.voice_count:
        parts.append(f"is scored for {d.voice_count} voice{'s' if d.voice_count != 1 else ''}")

    if d.measure_count:
        ts = f" in {'/'.join(d.time_signatures)}" if d.time_signatures else ""
        parts.append(f"and spans {d.measure_count} measures{ts}")

    if d.detected_key:
        parts.append(f"The key is {d.detected_key}")

    if d.texture_type:
        texture_labels = {
            "homophonic_chorale": "homophonic chorale texture (homorhythmic)",
            "homophonic_melody": "melody-dominated homophonic texture",
            "polyphonic_imitative": "imitative polyphonic texture",
            "polyphonic_free": "free polyphonic texture",
            "monophonic": "monophonic (single line)",
        }
        parts.append(f"The texture is {texture_labels.get(d.texture_type, d.texture_type)}")

    if d.form_type:
        parts.append(f"Form: {d.form_type.replace('_', '-')}")

    if d.harmony_epoch:
        parts.append(f"Harmonic style appears {d.harmony_epoch}")

    if d.has_lyrics:
        lang_names = {
            "la": "Latin", "pl": "Polish", "de": "German", "en": "English",
            "cs": "Czech", "it": "Italian", "fr": "French", "unknown": "unknown language",
        }
        lang = lang_names.get(d.lyrics_language or "unknown", d.lyrics_language)
        parts.append(f"The text is in {lang} set in a {d.text_setting_type} style")
    else:
        parts.append("No lyrics detected (instrumental or text not encoded)")

    if d.grade_label and d.estimated_grade:
        parts.append(
            f"Estimated difficulty: Grade {d.estimated_grade} ({d.grade_label})"
        )

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------

class ScoreAnalyzer:
    """Analyse a music21 Score and produce a ScoreDescriptor."""

    def analyze(self, score: stream.Score, source_file: Optional[str] = None) -> ScoreDescriptor:
        d = ScoreDescriptor()
        d.source_file = source_file

        # Metadata
        if score.metadata:
            d.title = score.metadata.title
            d.composer = score.metadata.composer

        # Basic structure
        parts = list(score.parts)
        d.voice_count = len(parts)
        d.voice_names = [p.partName or f"Part {i+1}" for i, p in enumerate(parts)]

        first_part = parts[0] if parts else None
        if first_part:
            measures = list(first_part.getElementsByClass(stream.Measure))
            d.measure_count = len(measures)

            ts_seen = []
            for ts in first_part.flatten().getElementsByClass(meter.TimeSignature):
                ts_str = ts.ratioString
                if ts_str not in ts_seen:
                    ts_seen.append(ts_str)
            d.time_signatures = ts_seen

            tempos = list(first_part.flatten().getElementsByClass(tempo.MetronomeMark))
            if tempos:
                d.tempo_marking = str(tempos[0])

            # Pickup measure detection
            if measures and measures[0].paddingLeft > 0:
                d.has_pickup_measure = True

        # Total duration
        try:
            d.total_duration_beats = float(score.duration.quarterLength)
        except Exception:
            pass

        # Key and harmony
        key_name, conf, mode, chrom, epoch, chords = _analyze_harmony(score)
        d.detected_key = key_name
        d.key_confidence = conf
        d.mode = mode
        d.chromatic_complexity = chrom
        d.harmony_epoch = epoch
        d.chord_vocabulary = chords
        d.harmonic_rhythm = _harmonic_rhythm(score)

        # Texture
        texture, rvar, onset_sim, v_indep = _compute_texture(score)
        d.texture_type = texture
        d.rhythmic_variance = rvar
        d.onset_simultaneity = onset_sim
        d.voice_independence = v_indep

        # Voice ranges
        d.voice_ranges = [_analyze_voice_range(p) for p in parts]

        # Voice leading
        p5, p8, crossings, contrary = _analyze_voice_leading(score)
        d.parallel_fifths_count = p5
        d.parallel_octaves_count = p8
        d.voice_crossings_count = crossings
        d.contrary_motion_ratio = contrary

        # Form
        form, has_rep, n_sections, has_imit, is_canon = _detect_form(score, d.voice_count)
        d.form_type = form
        d.has_repetition = has_rep
        d.section_count = n_sections
        d.has_imitation = has_imit
        d.is_canon = is_canon

        # Lyrics
        has_lyr, lang, lang_conf, setting, nps = _extract_lyrics(score)
        d.has_lyrics = has_lyr
        d.lyrics_language = lang
        d.language_confidence = lang_conf
        d.text_setting_type = setting
        d.notes_per_syllable_avg = nps

        # Difficulty
        max_range = max((vr.range_semitones for vr in d.voice_ranges), default=0)
        grade, label, factors = _estimate_difficulty(
            d.voice_count, max_range, d.chromatic_complexity,
            d.voice_independence, d.parallel_fifths_count, d.measure_count,
        )
        d.estimated_grade = grade
        d.grade_label = label
        d.difficulty_factors = factors

        # Narrative
        d.narrative_description = _build_narrative(d)

        return d
