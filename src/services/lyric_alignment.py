"""Algorithmic lyric underlay — assign syllables to notes from melodic structure + text.

Motivation
----------
Asking an LLM to align lyrics *per voice* (one call per part) is slow and expensive and was
timing out on real scores. Yet most choral underlay is mechanical: text is syllabified, one
syllable sits under one note, and where there are more notes than syllables a syllable is held
over several notes (a **melisma**) — and the score already tells us where melismas go via
**slurs** and **ties**. This module does that assignment in pure Python (no LLM, no network),
and reports a **confidence** so the caller can invoke the LLM only on the hard cases.

The two ingredients we already have:
* the **clean lyrics** (step 2), and
* the **melodic structure** of each voice (music21 notes, rests, slurs, ties).

Pipeline of this module:
1. :func:`syllabify_text` — split text into syllables (language-agnostic vowel-group rules,
   accent-aware via Unicode NFD; handles pre-hyphenated text). No external dependency.
2. :func:`extract_phrases` — turn a music21 part into phrases (split on rests) of *slots*,
   where a slot is one syllable position: notes joined by a slur/tie are collapsed into the
   preceding slot (they are melisma continuations, not new syllables).
3. :func:`align_part` — distribute the syllables over the slots (1:1 when counts match,
   melismas when there are more notes, overflow when there are more syllables) and score the
   result. The caller applies the assignment with music21 and, when confidence is low, asks an
   LLM to redo just that part.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Base vowels after stripping diacritics (NFD). 'y' counts as a vowel (Polish/Latin).
_BASE_VOWELS = set("aeiouy")
# Word-edge punctuation to strip (keep inner apostrophes/hyphens).
_EDGE_PUNCT = "\"'`„”“»«.,;:!?()[]{}…—–-"


@dataclass
class Syllable:
    """One sung syllable plus its position in the word (MusicXML ``syllabic``)."""

    text: str
    syllabic: str  # single | begin | middle | end


@dataclass
class PartAlignment:
    """Result of aligning the whole text to one voice's notes.

    ``note_assignments`` is one ``(note, text, syllabic)`` per note in document order; ``text``
    is empty for melisma-continuation / untexted notes.
    """

    note_assignments: List[Tuple[object, str, str]] = field(default_factory=list)
    slot_count: int = 0
    syllable_count: int = 0
    placed: int = 0
    overflow: int = 0
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# 1. Syllabification (no external dependency, language-agnostic)
# ---------------------------------------------------------------------------


def _base_char(ch: str) -> str:
    """Diacritic-stripped lowercase base letter (so ą→a, ó→o, é→e, etc.)."""
    decomposed = unicodedata.normalize("NFD", ch)
    return decomposed[0].lower() if decomposed else ch.lower()


def _is_vowel(ch: str) -> bool:
    return ch.isalpha() and _base_char(ch) in _BASE_VOWELS


def syllabify_word(word: str) -> List[str]:
    """Split a single word into syllable strings using vowel-group rules.

    Each maximal run of vowels is one syllable nucleus; intervocalic consonants are split so a
    single consonant opens the next syllable (V-CV) and a cluster leaves one with the previous
    (VC-CV). Diacritics are handled via NFD, so the rule works for Polish, Latin, German, etc.
    Not linguistically perfect (hiatus like Latin *de-us* counts as one) — good enough for the
    note count, with the LLM correcting the residual hard cases.
    """
    chars = list(word)
    voweled = [_is_vowel(c) for c in chars]

    nuclei: List[Tuple[int, int]] = []  # (start, end) of each vowel run
    i = 0
    while i < len(chars):
        if voweled[i]:
            j = i
            while j < len(chars) and voweled[j]:
                j += 1
            nuclei.append((i, j))
            i = j
        else:
            i += 1

    if len(nuclei) <= 1:
        return [word]

    cuts: List[int] = []
    for a in range(len(nuclei) - 1):
        c_start, c_end = nuclei[a][1], nuclei[a + 1][0]  # consonant span between two nuclei
        ncons = c_end - c_start
        if ncons <= 1:
            cut = c_start  # hiatus or single consonant → consonant opens next syllable
        else:
            cut = c_start + 1  # cluster → one consonant stays, the rest open the next
        cuts.append(cut)

    parts, prev = [], 0
    for cut in cuts:
        parts.append("".join(chars[prev:cut]))
        prev = cut
    parts.append("".join(chars[prev:]))
    return [p for p in parts if p]


def syllabify_text(text: str) -> List[Syllable]:
    """Flatten ``text`` into an ordered list of :class:`Syllable` with ``syllabic`` markers.

    Splits on whitespace into words; each word is syllabified (respecting explicit hyphens as
    syllable breaks). Pure-punctuation tokens are dropped. Verse/line breaks are not encoded
    here — musical phrasing (rests) drives boundaries in :func:`align_part`.
    """
    out: List[Syllable] = []
    for raw in re.split(r"\s+", text or ""):
        token = raw.strip(_EDGE_PUNCT)
        if not token or not any(c.isalpha() for c in token):
            continue
        # Respect an explicit hyphenation already present in the text.
        pieces: List[str] = []
        for seg in token.split("-"):
            seg = seg.strip(_EDGE_PUNCT)
            if seg:
                pieces.extend(syllabify_word(seg))
        if not pieces:
            continue
        if len(pieces) == 1:
            out.append(Syllable(pieces[0], "single"))
        else:
            for k, piece in enumerate(pieces):
                if k == 0:
                    syllabic = "begin"
                elif k == len(pieces) - 1:
                    syllabic = "end"
                else:
                    syllabic = "middle"
                out.append(Syllable(piece, syllabic))
    return out


# ---------------------------------------------------------------------------
# 2. Melodic structure → phrases of slots (music21)
# ---------------------------------------------------------------------------


def _is_melisma_continuation(note_el) -> bool:
    """True when this note continues the previous syllable (tie-held or inside a slur)."""
    tie = getattr(note_el, "tie", None)
    if tie is not None and getattr(tie, "type", None) in ("stop", "continue"):
        return True
    try:
        for sp in note_el.getSpannerSites():
            if "Slur" in sp.classes and not sp.isFirst(note_el):
                return True
    except Exception:  # pragma: no cover - defensive (spanner API edge cases)
        pass
    return False


def extract_phrases(part) -> List[List[List[object]]]:
    """Turn a music21 part into ``phrases -> slots -> notes``.

    Rests split phrases. Within a phrase, a new slot starts a new syllable; melisma
    continuations (tied/slurred notes) are appended to the current slot's note list.
    """
    phrases: List[List[List[object]]] = []
    cur_phrase: List[List[object]] = []
    cur_slot: Optional[List[object]] = None

    for el in part.recurse().notesAndRests:
        if el.isRest:
            if cur_phrase:
                phrases.append(cur_phrase)
            cur_phrase, cur_slot = [], None
            continue
        if cur_slot is not None and _is_melisma_continuation(el):
            cur_slot.append(el)
        else:
            cur_slot = [el]
            cur_phrase.append(cur_slot)

    if cur_phrase:
        phrases.append(cur_phrase)
    return phrases


# ---------------------------------------------------------------------------
# 3. Distribution + confidence
# ---------------------------------------------------------------------------


def _largest_remainder(total: int, weights: List[int]) -> List[int]:
    """Apportion ``total`` integer units across buckets ∝ ``weights`` (largest-remainder)."""
    wsum = sum(weights)
    if total <= 0 or wsum <= 0:
        return [0] * len(weights)
    raw = [total * w / wsum for w in weights]
    base = [int(x) for x in raw]
    remainder = total - sum(base)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in range(remainder):
        base[order[i]] += 1
    return base


def _spread_phrase(syls: List[Syllable], slots: List[List[object]]):
    """Place ``syls`` over a phrase's ``slots``. Returns ``(assignments, overflow)``.

    1:1 when counts match; melismas (held syllables) when there are more slots than syllables;
    overflow (unplaceable syllables) when there are more syllables than slots.
    """
    assignments: List[Tuple[object, str, str]] = []
    k, m = len(slots), len(syls)

    if m == 0:
        for slot in slots:
            for nt in slot:
                assignments.append((nt, "", ""))
        return assignments, 0

    if m >= k:  # one syllable per slot; the rest overflow to be handled by the caller
        for i, slot in enumerate(slots):
            syl = syls[i]
            for j, nt in enumerate(slot):
                assignments.append((nt, syl.text, syl.syllabic) if j == 0 else (nt, "", ""))
        return assignments, m - k

    # m < k → melismas: distribute slots across syllables as evenly as possible.
    sizes = [k // m + (1 if i < k % m else 0) for i in range(m)]
    idx = 0
    for i, size in enumerate(sizes):
        group = slots[idx: idx + size]
        idx += size
        first = True
        for slot in group:
            for j, nt in enumerate(slot):
                if first and j == 0:
                    assignments.append((nt, syls[i].text, syls[i].syllabic))
                else:
                    assignments.append((nt, "", ""))
            first = False
    return assignments, 0


def align_part(syllables: List[Syllable], phrases: List[List[List[object]]]) -> PartAlignment:
    """Distribute ``syllables`` over a voice's ``phrases`` and score the alignment."""
    slot_counts = [len(p) for p in phrases]
    total_slots = sum(slot_counts)
    n_syll = len(syllables)

    if total_slots == 0:
        return PartAlignment(syllable_count=n_syll)

    per_phrase = _largest_remainder(n_syll, slot_counts)
    assignments: List[Tuple[object, str, str]] = []
    overflow_total = 0
    cursor = 0
    for phrase, take in zip(phrases, per_phrase):
        phrase_syls = syllables[cursor: cursor + take]
        cursor += take
        phrase_assign, overflow = _spread_phrase(phrase_syls, phrase)
        assignments.extend(phrase_assign)
        overflow_total += overflow
    overflow_total += max(0, n_syll - cursor)  # any tail that never got a phrase

    placed = sum(1 for _, text, _ in assignments if text)

    # Confidence: how cleanly the counts line up. A perfect 1:1 → 1.0; large mismatch or
    # leftover syllables drag it down so the caller can escalate that part to the LLM.
    mismatch = abs(total_slots - n_syll) / max(total_slots, n_syll, 1)
    overflow_penalty = overflow_total / max(n_syll, 1)
    confidence = max(0.0, min(1.0, 1.0 - mismatch - 0.5 * overflow_penalty))

    return PartAlignment(
        note_assignments=assignments,
        slot_count=total_slots,
        syllable_count=n_syll,
        placed=placed,
        overflow=overflow_total,
        confidence=round(confidence, 3),
    )
