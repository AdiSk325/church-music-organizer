"""Compare do Jana Kantego pipeline output with expected MusicXML."""
import sys
sys.path.insert(0, ".")
from pathlib import Path

OUTPUT = "data/processed/do Jana Kantego_final.musicxml"
EXPECTED = "tests/OMR/expected_output/do Jana Kantego.musicxml"

# ---- Raw staff OMR data ----
print("=" * 70)
print("  RAW STAFF OMR DATA (per staff MusicXML files)")
print("=" * 70)

from music21 import converter

raw_files = sorted(Path("data/processed").glob("do Jana Kantego_page_*_staff_*.musicxml"))
for rf in raw_files:
    print(f"\n  --- {rf.name} ---")
    try:
        score = converter.parse(str(rf))
        for pi, part in enumerate(score.parts):
            measures = list(part.getElementsByClass("Measure"))
            # Get key and time from first measure
            first_m = measures[0] if measures else None
            ks = first_m.keySignature if first_m and first_m.keySignature else None
            ts = first_m.timeSignature if first_m and first_m.timeSignature else None
            clefs = list(part.flatten().getElementsByClass("Clef"))
            clef_str = clefs[0].sign + str(clefs[0].line) if clefs else "?"
            
            print(f"    Part {pi}: clef={clef_str}, key={ks}, time={ts}, measures={len(measures)}")
            for mi, m in enumerate(measures):
                notes = list(m.flatten().notes)
                total_beats = sum(n.quarterLength for n in notes)
                note_strs = []
                for n in notes:
                    if hasattr(n, "pitch"):
                        note_strs.append(f"{n.pitch.nameWithOctave}({n.quarterLength}q)")
                    elif hasattr(n, "pitches"):
                        ps = "+".join(p.nameWithOctave for p in n.pitches)
                        note_strs.append(f"[{ps}]({n.quarterLength}q)")
                rests = list(m.flatten().getElementsByClass("Rest"))
                rest_beats = sum(r.quarterLength for r in rests)
                print(f"    M{mi+1}: {len(notes)}n {len(rests)}r beats={total_beats:.2f}+{rest_beats:.2f}r  {' '.join(note_strs)}")
    except Exception as e:
        print(f"    ERROR: {e}")

# ---- Comparison with expected ----
print("\n" + "=" * 70)
print("  COMPARISON: Expected vs Actual")
print("=" * 70)

exp = converter.parse(EXPECTED)
act = converter.parse(OUTPUT)

print(f"\n  Expected parts: {len(exp.parts)}")
for i, ep in enumerate(exp.parts):
    em = list(ep.getElementsByClass("Measure"))
    en = list(ep.flatten().notes)
    ks = em[0].keySignature if em and em[0].keySignature else None
    ts = em[0].timeSignature if em and em[0].timeSignature else None
    staves_attr = None
    if em:
        for el in em[0].flatten():
            if hasattr(el, 'staves'):
                staves_attr = el.staves
                break
    print(f"    Part {i} '{ep.partName}': {len(em)} measures, {len(en)} notes, key={ks}, time={ts}")

print(f"\n  Actual parts: {len(act.parts)}")
for i, ap in enumerate(act.parts):
    am = list(ap.getElementsByClass("Measure"))
    an = list(ap.flatten().notes)
    ks = am[0].keySignature if am and am[0].keySignature else None
    ts = am[0].timeSignature if am and am[0].timeSignature else None
    print(f"    Part {i} '{ap.partName}': {len(am)} measures, {len(an)} notes, key={ks}, time={ts}")

# ---- Per-measure detail for expected ----
print("\n" + "=" * 70)
print("  EXPECTED - per measure detail")
print("=" * 70)
for i, ep in enumerate(exp.parts):
    em = list(ep.getElementsByClass("Measure"))
    print(f"\n  --- Expected Part {i}: '{ep.partName}' ---")
    for mi, m in enumerate(em):
        notes = list(m.flatten().notes)
        rests = list(m.flatten().getElementsByClass("Rest"))
        total_beats = sum(n.quarterLength for n in notes)
        rest_beats = sum(r.quarterLength for r in rests)
        
        # Group by voice
        voices = {}
        for n in notes:
            v = n.voice if hasattr(n, 'voice') and n.voice else '?'
            if v not in voices:
                voices[v] = []
            if hasattr(n, "pitch"):
                voices[v].append(f"{n.pitch.nameWithOctave}({n.quarterLength}q)")
            elif hasattr(n, "pitches"):
                ps = "+".join(p.nameWithOctave for p in n.pitches)
                voices[v].append(f"[{ps}]({n.quarterLength}q)")
        
        voice_str = " | ".join(f"v{v}: {' '.join(ns)}" for v, ns in sorted(voices.items()))
        
        # Check for key/time changes
        ks_change = m.keySignature
        ts_change = m.timeSignature
        changes = ""
        if ks_change:
            changes += f" [key={ks_change}]"
        if ts_change:
            changes += f" [time={ts_change}]"
        
        print(f"    M{mi+1}: {len(notes)}n {len(rests)}r beats={total_beats:.1f}+{rest_beats:.1f}r{changes}")
        print(f"      {voice_str}")

# ---- Per-measure detail for actual ----
print("\n" + "=" * 70)
print("  ACTUAL - per measure detail")
print("=" * 70)
for i, ap in enumerate(act.parts):
    am = list(ap.getElementsByClass("Measure"))
    print(f"\n  --- Actual Part {i}: '{ap.partName}' ---")
    for mi, m in enumerate(am):
        notes = list(m.flatten().notes)
        rests = list(m.flatten().getElementsByClass("Rest"))
        total_beats = sum(n.quarterLength for n in notes)
        rest_beats = sum(r.quarterLength for r in rests)
        
        voices = {}
        for n in notes:
            v = n.voice if hasattr(n, 'voice') and n.voice else '?'
            if v not in voices:
                voices[v] = []
            if hasattr(n, "pitch"):
                voices[v].append(f"{n.pitch.nameWithOctave}({n.quarterLength}q)")
            elif hasattr(n, "pitches"):
                ps = "+".join(p.nameWithOctave for p in n.pitches)
                voices[v].append(f"[{ps}]({n.quarterLength}q)")
        
        voice_str = " | ".join(f"v{v}: {' '.join(ns)}" for v, ns in sorted(voices.items()))
        
        ks_change = m.keySignature
        ts_change = m.timeSignature
        changes = ""
        if ks_change:
            changes += f" [key={ks_change}]"
        if ts_change:
            changes += f" [time={ts_change}]"
        
        print(f"    M{mi+1}: {len(notes)}n {len(rests)}r beats={total_beats:.1f}+{rest_beats:.1f}r{changes}")
        print(f"      {voice_str}")

# ---- Summary ----
print("\n" + "=" * 70)
print("  SUMMARY COMPARISON")
print("=" * 70)

# Pitch ranges per part
for label, score_obj in [("Expected", exp), ("Actual", act)]:
    print(f"\n  {label}:")
    for i, p in enumerate(score_obj.parts):
        notes = list(p.flatten().notes)
        pitches = set()
        for n in notes:
            if hasattr(n, "pitch"):
                pitches.add(n.pitch.midi)
            elif hasattr(n, "pitches"):
                for pp in n.pitches:
                    pitches.add(pp.midi)
        measures = list(p.getElementsByClass("Measure"))
        if pitches:
            print(f"    Part {i} '{p.partName}': {len(measures)} measures, {len(notes)} notes, pitch range {min(pitches)}-{max(pitches)}")
        else:
            print(f"    Part {i} '{p.partName}': {len(measures)} measures, {len(notes)} notes, no pitches")

# Check lyrics
print(f"\n  Lyrics comparison:")
for label, score_obj in [("Expected", exp), ("Actual", act)]:
    for i, p in enumerate(score_obj.parts):
        lyric_count = 0
        for n in p.flatten().notes:
            if hasattr(n, 'lyrics') and n.lyrics:
                lyric_count += len(n.lyrics)
        if lyric_count > 0:
            print(f"    {label} Part {i} '{p.partName}': {lyric_count} lyric syllables")
