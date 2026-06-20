"""Algorithmic structural analysis of ground-truth MusicXML reference scores.

For each ``*.musicxml`` reference in ``data/tests`` this extracts every fact useful for
defining and computing reference-based success metrics for the pdf -> musicxml pipeline:
metadata, voices/parts, note & measure counts, key/meter, tempo/dynamics/articulation
markings and lyric coverage. The result is printed and written to a JSON facts file.

Run:  poetry run python scripts/analyze_reference.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

TESTS_DIR = Path("data/tests")
OUT_DIR = Path("data/processed/eval")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def analyze(path: Path) -> dict:
    from music21 import converter, dynamics, expressions, tempo

    score = converter.parse(str(path))

    md = score.metadata
    meta = {
        "title": _safe(lambda: md.title) if md else None,
        "movement": _safe(lambda: md.movementName) if md else None,
        "composer": _safe(lambda: md.composer) if md else None,
        "lyricist": _safe(lambda: md.lyricist) if md else None,
        "copyright": _safe(lambda: str(md.copyright) if md.copyright else None) if md else None,
    }

    parts = list(score.parts)
    part_facts = []
    total_notes = 0
    total_chords = 0
    parts_with_lyrics = 0
    for idx, p in enumerate(parts):
        notes = list(p.recurse().notes)
        n_notes = len(notes)
        n_chords = sum(1 for n in notes if getattr(n, "isChord", False))
        total_notes += n_notes
        total_chords += n_chords
        lyric_notes = sum(1 for n in notes if getattr(n, "lyrics", None))
        if lyric_notes:
            parts_with_lyrics += 1
        pitches = []
        for n in notes:
            try:
                if n.isChord:
                    pitches.extend(pp.midi for pp in n.pitches)
                else:
                    pitches.append(n.pitch.midi)
            except Exception:
                pass
        measures = list(p.getElementsByClass("Measure"))
        # max simultaneous voices in any measure (polyphony within a staff)
        max_voices = 1
        for m in measures:
            vs = list(m.getElementsByClass("Voice"))
            if vs:
                max_voices = max(max_voices, len(vs))
        part_facts.append(
            {
                "index": idx,
                "name": _safe(lambda: p.partName),
                "instrument": _safe(lambda: p.getInstrument(returnDefault=False).instrumentName)
                if p else None,
                "measures": len(measures),
                "notes": n_notes,
                "chords": n_chords,
                "lyric_notes": lyric_notes,
                "pitch_min_midi": min(pitches) if pitches else None,
                "pitch_max_midi": max(pitches) if pitches else None,
                "max_voices_in_measure": max_voices,
            }
        )

    flat = score.flatten()
    time_sigs = [ts.ratioString for ts in flat.getElementsByClass("TimeSignature")]
    key_sigs = []
    for ks in flat.getElementsByClass("KeySignature"):
        key_sigs.append(_safe(lambda: ks.asKey().name) or str(ks))
    tempos = []
    for t in flat.getElementsByClass(tempo.TempoIndication):
        tempos.append(_safe(lambda: str(getattr(t, "text", None) or t.number)) or "tempo")
    dyns = [d.value for d in flat.getElementsByClass(dynamics.Dynamic)]
    expr = [type(e).__name__ for e in flat.getElementsByClass(expressions.Expression)]
    # articulations live on notes
    artic = set()
    for n in flat.notes:
        for a in getattr(n, "articulations", []) or []:
            artic.add(type(a).__name__)

    detected_key = _safe(lambda: str(score.analyze("key")))
    measure_count = max((pf["measures"] for pf in part_facts), default=0)

    return {
        "file": path.name,
        "metadata": meta,
        "part_count": len(parts),
        "part_names": [pf["name"] for pf in part_facts],
        "parts": part_facts,
        "total_notes": total_notes,
        "total_chords": total_chords,
        "parts_with_lyrics": parts_with_lyrics,
        "measure_count": measure_count,
        "time_signatures": time_sigs[:10],
        "time_signature_changes": len(set(time_sigs)) > 1,
        "key_signatures": list(dict.fromkeys(key_sigs))[:10],
        "detected_key": detected_key,
        "tempo_markings": tempos[:20],
        "dynamics": sorted(set(dyns)),
        "dynamics_count": len(dyns),
        "expressions": sorted(set(expr)),
        "articulations": sorted(artic),
    }


def main() -> None:
    refs = sorted(TESTS_DIR.glob("*.musicxml"))
    if not refs:
        print("Brak plików .musicxml w", TESTS_DIR)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_facts = {}
    for ref in refs:
        print(f"\n=== {ref.name} ===")
        facts = analyze(ref)
        all_facts[ref.stem] = facts
        m = facts["metadata"]
        print(f"  title={m['title']!r} composer={m['composer']!r}")
        print(f"  parts={facts['part_count']} names={facts['part_names']}")
        print(f"  total_notes={facts['total_notes']} chords={facts['total_chords']} "
              f"measures={facts['measure_count']}")
        print(f"  key_sigs={facts['key_signatures']} detected={facts['detected_key']}")
        print(f"  time_sigs={facts['time_signatures']} changes={facts['time_signature_changes']}")
        print(f"  tempo={facts['tempo_markings']}")
        print(f"  dynamics({facts['dynamics_count']})={facts['dynamics']} "
              f"artic={facts['articulations']}")
        print(f"  parts_with_lyrics={facts['parts_with_lyrics']}")

    out = OUT_DIR / "reference_facts.json"
    out.write_text(json.dumps(all_facts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nZapisano fakty referencyjne do {out}")


if __name__ == "__main__":
    main()
