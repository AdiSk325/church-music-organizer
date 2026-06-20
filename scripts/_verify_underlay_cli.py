"""Verify per-voice underlay end-to-end via the claude CLI backend. Delete after.

Run with: CMO_LLM_BACKEND=claude_cli poetry run python scripts/_verify_underlay_cli.py
"""
from pathlib import Path

from music21 import converter

from src.llm.lyric_underlayer import underlay_lyrics
from src.llm.musicxml_validate import load_musicxml_text

TESTS = Path("data/tests")
OMR = Path("data/processed/eval/omr")
OUT = Path("data/processed/eval/underlay_cli")
PIECES = ["cantata-147-jesus-bleibet-meine-freude-johann-sebastian-bach", "feliz-navidad-t-ch"]


def reconstruct_text(ref_path, part_index=0):
    score = converter.parse(str(ref_path))
    parts = list(score.parts)
    if part_index >= len(parts):
        return ""
    words, cur = [], ""
    for n in parts[part_index].recurse().notes:
        for ly in (getattr(n, "lyrics", None) or []):
            t = (ly.text or "").strip()
            s = ly.syllabic or "single"
            if not t:
                continue
            if s == "single":
                if cur:
                    words.append(cur); cur = ""
                words.append(t)
            elif s == "begin":
                if cur:
                    words.append(cur)
                cur = t
            elif s == "middle":
                cur += t
            elif s == "end":
                words.append(cur + t); cur = ""
            else:
                words.append(t)
    if cur:
        words.append(cur)
    return " ".join(words)


def coverage(score):
    rows, tn, tl = [], 0, 0
    for i, p in enumerate(score.parts):
        notes = list(p.recurse().notes)
        lyr = [n for n in notes if getattr(n, "lyrics", None)]
        tn += len(notes); tl += len(lyr)
        sample = " ".join(
            (n.lyrics[0].text or "") for n in notes if getattr(n, "lyrics", None)
        ).split()[:10]
        rows.append((i, len(notes), len(lyr), " ".join(sample)))
    return tn, tl, rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for stem in PIECES:
        ref = TESTS / f"{stem}.musicxml"
        omr = OMR / f"{stem}.mxl"
        print(f"\n=== {stem} ===", flush=True)
        if not omr.exists():
            print("  no OMR cache", flush=True)
            continue
        lyrics = reconstruct_text(ref)
        try:
            result = underlay_lyrics(lyrics, load_musicxml_text(str(omr)))
        except Exception as exc:
            print(f"  EXCEPTION: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
            continue
        print(f"  changed={result.changed}", flush=True)
        if result.score is not None:
            tn, tl, rows = coverage(result.score)
            print(f"  >>> COVERAGE: {tl}/{tn} ({tl/tn:.0%})", flush=True)
            for i, nn, ll, sample in rows:
                print(f"    głos {i}: {ll}/{nn} | {sample}", flush=True)
            outp = OUT / f"final_{stem}.musicxml"
            outp.write_text(result.musicxml, encoding="utf-8")
            print(f"  saved: {outp}", flush=True)


if __name__ == "__main__":
    main()
