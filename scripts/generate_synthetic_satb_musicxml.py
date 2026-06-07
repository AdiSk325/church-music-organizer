"""Generate synthetic SATB MusicXML cases for roundtrip benchmark development.

This script deliberately prioritizes structural validity and reproducibility over
musical quality. The generated scores are useful for:

- pipeline contract testing,
- benchmark harness validation,
- artifact bookkeeping,
- MusicXML -> PDF -> MusicXML roundtrip experiments.

They are not a substitute for real printed church music or scan-based gold sets.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from music21 import clef, key, meter, metadata, note, stream  # type: ignore[import]


VOICE_SPECS: Sequence[Tuple[str, str, Tuple[int, int]]] = (
    ("Soprano", "treble", (60, 79)),
    ("Alto", "treble", (55, 72)),
    ("Tenor", "bass", (48, 67)),
    ("Bass", "bass", (40, 60)),
)

MEASURE_PATTERNS: Sequence[Sequence[float]] = (
    (4.0,),
    (2.0, 2.0),
    (2.0, 1.0, 1.0),
    (1.0, 1.0, 1.0, 1.0),
)


def _midi_to_pitch_name(midi_value: int) -> str:
    pitch_classes = ["C", "C#", "D", "E-", "E", "F", "F#", "G", "A-", "A", "B-", "B"]
    octave = (midi_value // 12) - 1
    pitch_class = pitch_classes[midi_value % 12]
    return f"{pitch_class}{octave}"


def _build_voice_measure(
    random_generator: random.Random,
    midi_range: Tuple[int, int],
) -> List[note.GeneralNote]:
    pattern = random_generator.choice(MEASURE_PATTERNS)
    elements: List[note.GeneralNote] = []
    for duration in pattern:
        if random_generator.random() < 0.15:
            rest = note.Rest()
            rest.duration.quarterLength = duration
            elements.append(rest)
            continue

        midi_value = random_generator.randint(midi_range[0], midi_range[1])
        pitch_name = _midi_to_pitch_name(midi_value)
        generated_note = note.Note(pitch_name)
        generated_note.duration.quarterLength = duration
        elements.append(generated_note)
    return elements


def build_random_satb_score(
    *,
    case_id: str,
    random_generator: random.Random,
    measures: int,
) -> stream.Score:
    score = stream.Score(id=case_id)
    score_metadata = metadata.Metadata()
    score_metadata.title = case_id
    score_metadata.composer = "synthetic-generator"
    score.insert(0, score_metadata)

    key_signature = key.KeySignature(random_generator.choice([-1, 0, 1]))
    time_signature = meter.TimeSignature("4/4")

    for voice_name, clef_name, midi_range in VOICE_SPECS:
        part = stream.Part(id=voice_name)
        part.partName = voice_name
        part.append(clef.TrebleClef() if clef_name == "treble" else clef.BassClef())
        part.append(key_signature)
        part.append(time_signature)

        for _ in range(measures):
            measure_stream = stream.Measure()
            for element in _build_voice_measure(random_generator, midi_range):
                measure_stream.append(element)
            part.append(measure_stream)

        score.append(part)

    return score


def _try_render_pdf(
    musicxml_path: Path,
    pdf_path: Path,
    *,
    musescore_path: Optional[str],
) -> Dict[str, str]:
    if not musescore_path:
        return {
            "status": "skipped",
            "reason": "MUSESCORE_PATH not provided",
        }

    try:
        result = subprocess.run(
            [musescore_path, str(musicxml_path), "-o", str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "reason": (result.stderr or result.stdout or "MuseScore failed")[:500],
            }
        return {
            "status": "success",
            "pdf_path": str(pdf_path),
        }
    except FileNotFoundError:
        return {
            "status": "failed",
            "reason": "MuseScore executable not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "reason": "MuseScore PDF export timed out",
        }


def generate_dataset(
    *,
    output_dir: Path,
    count: int,
    seed: int,
    measures: int,
    render_pdf: bool = False,
    musescore_path: Optional[str] = None,
) -> List[Dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    random_generator = random.Random(seed)

    manifest: List[Dict[str, object]] = []
    for index in range(count):
        case_id = f"synthetic_satb_{seed}_{index:03d}"
        case_dir = output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        score = build_random_satb_score(
            case_id=case_id,
            random_generator=random_generator,
            measures=measures,
        )

        musicxml_path = case_dir / f"{case_id}.musicxml"
        score.write("musicxml", fp=str(musicxml_path))

        manifest_entry: Dict[str, object] = {
            "case_id": case_id,
            "seed": seed,
            "measures": measures,
            "voice_layout": [voice_name for voice_name, _, _ in VOICE_SPECS],
            "ground_truth_musicxml": str(musicxml_path),
            "synthetic": True,
        }

        if render_pdf:
            pdf_path = case_dir / f"{case_id}.pdf"
            manifest_entry["pdf_render"] = _try_render_pdf(
                musicxml_path,
                pdf_path,
                musescore_path=musescore_path,
            )

        manifest.append(manifest_entry)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic SATB MusicXML cases for roundtrip benchmark work.",
    )
    parser.add_argument("--output-dir", default="data/synthetic_satb", help="Directory for generated cases.")
    parser.add_argument("--count", type=int, default=5, help="Number of synthetic cases to generate.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for reproducible generation.")
    parser.add_argument("--measures", type=int, default=8, help="Measures per generated score.")
    parser.add_argument(
        "--render-pdf",
        action="store_true",
        help="Attempt to render each MusicXML file to PDF using MuseScore.",
    )
    parser.add_argument(
        "--musescore-path",
        default=None,
        help="Path to MuseScore executable. If omitted, PDF rendering is skipped unless this argument is provided.",
    )
    args = parser.parse_args()

    manifest = generate_dataset(
        output_dir=Path(args.output_dir),
        count=args.count,
        seed=args.seed,
        measures=args.measures,
        render_pdf=args.render_pdf,
        musescore_path=args.musescore_path,
    )
    print(f"Generated {len(manifest)} synthetic SATB cases in {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()