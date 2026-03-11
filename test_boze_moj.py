"""Process Boże mój test image through OMR pipeline and compare with expected."""
import sys
sys.path.insert(0, ".")

from src.ocr.staff_detector import StaffDetector
from src.ocr.staff_splitter import StaffSplitter
from src.ocr.omr_engine import get_best_available_engine
from src.ocr.score_builder import ScoreBuilder
from src.ocr.text_classifier import ClassifiedText
from src.ocr.musicxml_validator import MusicXMLValidator

IMG = "data/processed/temp/boze_moj_test.png"
OUTPUT = "data/processed/boze_moj_test_final.musicxml"
EXPECTED = "tests/OMR/expected_output/Boże_mój.musicxml"

# 1. Staff detection
print("=" * 60)
print("  Step 1: Staff Detection")
print("=" * 60)
detector = StaffDetector()
layout = detector.detect(IMG)
print(f"  Staves: {len(layout.staves)}, Groups: {len(layout.groups)}, Systems: {len(layout.systems)}")
for s in layout.staves:
    print(f"    Staff {s.index}: y={s.y_top}-{s.y_bottom}")
for g in layout.groups:
    print(f"    Group: {g.group_type} -> staves {g.staff_indices}")

# 2. Staff splitting
print("\n" + "=" * 60)
print("  Step 2: Staff Splitting")
print("=" * 60)
splitter = StaffSplitter(output_dir="data/processed/staves")
staff_images = splitter.split(IMG, layout)
print(f"  Split into {len(staff_images)} images:")
for si in staff_images:
    idx = si["staff_indices"]
    gt = si["group_type"]
    print(f"    Staff {idx} ({gt}): {si['path']}")

# 3. OMR per staff
print("\n" + "=" * 60)
print("  Step 3: OMR per staff")
print("=" * 60)
engine = get_best_available_engine()
print(f"  Engine: {engine.engine_name}")

staff_omr_results = []
for si in staff_images:
    idx = si["staff_indices"]
    print(f"  Running OMR on staff {idx}...")
    try:
        result = engine.recognize(si["path"])
        if result.success:
            print(f"    OK: {result.measures_detected} measures, "
                  f"{result.staves_detected} staves, "
                  f"key={result.key_signature}, time={result.time_signature}")
            staff_omr_results.append({
                "path": result.musicxml_path,
                "staff_indices": si["staff_indices"],
                "group_type": si["group_type"],
            })
        else:
            print(f"    FAIL: {result.error_message}")
    except Exception as e:
        print(f"    ERROR: {e}")

# 4. Build score
print("\n" + "=" * 60)
print("  Step 4: Score Building")
print("=" * 60)
text_info = ClassifiedText(title="Boże mój", composer="m.: J. Sykulski")
builder = ScoreBuilder()
out = builder.build(
    staff_omr_results=staff_omr_results,
    text_info=text_info,
    layout=layout,
    output_path=OUTPUT,
)
print(f"  Output: {out}")

# 5. Validation
print("\n" + "=" * 60)
print("  Step 5: Validation")
print("=" * 60)
validator = MusicXMLValidator()
report = validator.validate_and_fix(out)
print(validator.get_report_text(report))

# 6. Compare with expected
print("\n" + "=" * 60)
print("  Step 6: Comparison with Expected Output")
print("=" * 60)
from music21 import converter

exp = converter.parse(EXPECTED)
act = converter.parse(out)

print(f"  Expected parts: {len(exp.parts)}")
print(f"  Actual parts:   {len(act.parts)}")

for i, ep in enumerate(exp.parts):
    em = list(ep.getElementsByClass("Measure"))
    print(f"\n  --- Expected Part {i}: '{ep.partName}' ---")
    print(f"    Measures: {len(em)}")
    print(f"    Key: {ep.analyze('key')}")
    for j, m in enumerate(em):
        notes = list(m.flatten().notes)
        print(f"    M{j+1}: {len(notes)} notes, beats={sum(n.quarterLength for n in notes):.1f}")
        for n in notes:
            if hasattr(n, "pitch"):
                print(f"      {n.pitch} ({n.quarterLength}q) voice={n.voice if hasattr(n, 'voice') else '?'}")
            elif hasattr(n, "pitches"):
                ps = ", ".join(str(p) for p in n.pitches)
                print(f"      chord[{ps}] ({n.quarterLength}q)")

print()
for i, ap in enumerate(act.parts):
    am = list(ap.getElementsByClass("Measure"))
    print(f"\n  --- Actual Part {i}: '{ap.partName}' ---")
    print(f"    Measures: {len(am)}")
    try:
        print(f"    Key: {ap.analyze('key')}")
    except Exception:
        print(f"    Key: ?")
    for j, m in enumerate(am):
        notes = list(m.flatten().notes)
        print(f"    M{j+1}: {len(notes)} notes, beats={sum(n.quarterLength for n in notes):.1f}")
        for n in notes:
            if hasattr(n, "pitch"):
                print(f"      {n.pitch} ({n.quarterLength}q) voice={n.voice if hasattr(n, 'voice') else '?'}")
            elif hasattr(n, "pitches"):
                ps = ", ".join(str(p) for p in n.pitches)
                print(f"      chord[{ps}] ({n.quarterLength}q)")

# Summary comparison
print("\n" + "=" * 60)
print("  Summary Comparison")
print("=" * 60)
for i in range(min(len(exp.parts), len(act.parts))):
    ep, ap = exp.parts[i], act.parts[i]
    e_measures = list(ep.getElementsByClass("Measure"))
    a_measures = list(ap.getElementsByClass("Measure"))
    
    e_notes = list(ep.flatten().notes)
    a_notes = list(ap.flatten().notes)
    
    e_pitches = set()
    a_pitches = set()
    for n in e_notes:
        if hasattr(n, "pitch"):
            e_pitches.add(n.pitch.midi)
        elif hasattr(n, "pitches"):
            for p in n.pitches:
                e_pitches.add(p.midi)
    for n in a_notes:
        if hasattr(n, "pitch"):
            a_pitches.add(n.pitch.midi)
        elif hasattr(n, "pitches"):
            for p in n.pitches:
                a_pitches.add(p.midi)
    
    print(f"\n  Part {i}: '{ep.partName}' vs '{ap.partName}'")
    print(f"    Measures: {len(e_measures)} expected vs {len(a_measures)} actual")
    print(f"    Notes: {len(e_notes)} expected vs {len(a_notes)} actual")
    print(f"    Pitch range expected: {min(e_pitches) if e_pitches else '?'}-{max(e_pitches) if e_pitches else '?'}")
    print(f"    Pitch range actual:   {min(a_pitches) if a_pitches else '?'}-{max(a_pitches) if a_pitches else '?'}")
    
    # Check pitch overlap
    common = e_pitches & a_pitches
    only_exp = e_pitches - a_pitches
    only_act = a_pitches - e_pitches
    print(f"    Common pitches: {len(common)}, Only expected: {only_exp}, Only actual: {only_act}")
