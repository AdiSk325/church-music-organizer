"""Unit tests for the algorithmic (LLM-free) lyric alignment engine."""

from src.services.lyric_alignment import (
    align_part,
    extract_phrases,
    syllabify_text,
    syllabify_word,
)


# --- syllabification -------------------------------------------------------

def test_syllabify_word_basic():
    assert syllabify_word("alleluja") == ["al", "le", "lu", "ja"]
    assert syllabify_word("matka") == ["mat", "ka"]
    assert syllabify_word("Maryja") == ["Ma", "ry", "ja"]
    assert syllabify_word("Bóg") == ["Bóg"]  # single nucleus (accent via NFD)


def test_syllabify_word_polish_soft_i_and_diacritics():
    # 'i'+vowel form one nucleus (soft consonant), accents handled.
    assert syllabify_word("ciało") == ["cia", "ło"]


def test_syllabify_text_markers_and_punctuation():
    syls = syllabify_text("Ave, Ma!")
    assert [s.text for s in syls] == ["A", "ve", "Ma"]
    assert [s.syllabic for s in syls] == ["begin", "end", "single"]
    # pure punctuation / numbers are dropped
    assert syllabify_text("--- 123 !!!") == []


def test_syllabify_respects_existing_hyphenation():
    syls = syllabify_text("A-ve")
    assert [s.text for s in syls] == ["A", "ve"]
    assert [s.syllabic for s in syls] == ["begin", "end"]


# --- distribution / confidence --------------------------------------------

def _phrase(*slot_sizes):
    """Build one phrase whose slots hold the given number of opaque note tokens."""
    return [[object() for _ in range(size)] for size in slot_sizes]


def test_align_one_to_one_is_full_confidence():
    syls = syllabify_text("la la la")  # 3 single syllables
    res = align_part(syls, [_phrase(1, 1, 1)])
    assert res.slot_count == 3 and res.syllable_count == 3
    assert res.placed == 3 and res.overflow == 0
    assert res.confidence == 1.0


def test_align_more_notes_makes_melisma():
    syls = syllabify_text("A")  # 1 syllable
    res = align_part(syls, [_phrase(1, 1, 1)])  # 3 slots
    assert res.placed == 1  # one syllable, two melisma notes
    assert res.overflow == 0
    assert res.confidence < 0.6  # low → caller escalates to LLM


def test_align_more_syllables_overflows():
    syls = syllabify_text("la la la")  # 3
    res = align_part(syls, [_phrase(1)])  # only 1 slot
    assert res.placed == 1 and res.overflow == 2
    assert res.confidence < 0.6


def test_align_distributes_across_phrases():
    syls = syllabify_text("la la la la")  # 4
    res = align_part(syls, [_phrase(1, 1), _phrase(1, 1)])  # 2 phrases × 2 slots
    assert res.placed == 4 and res.overflow == 0
    assert res.confidence == 1.0


# --- melodic structure extraction (music21) --------------------------------

def test_extract_phrases_slur_collapses_into_one_slot():
    from music21 import note, spanner, stream

    part = stream.Part()
    m = stream.Measure(number=1)
    n1, n2, n3 = note.Note("C4"), note.Note("D4"), note.Note("E4")
    m.append([n1, n2, n3])
    part.append(m)
    part.insert(0, spanner.Slur([n1, n2]))  # n2 is a melisma continuation of n1

    phrases = extract_phrases(part)
    assert len(phrases) == 1
    slots = phrases[0]
    assert len(slots) == 2  # [n1,n2] collapsed, [n3] separate
    assert slots[0] == [n1, n2] and slots[1] == [n3]


def test_extract_phrases_rest_splits_phrases():
    from music21 import note, stream

    part = stream.Part()
    m = stream.Measure(number=1)
    m.append([note.Note("C4"), note.Rest(), note.Note("E4")])
    part.append(m)

    phrases = extract_phrases(part)
    assert len(phrases) == 2  # rest splits the two notes into separate phrases
