"""Convert a PDF sheet music file to MusicXML using the improved OMR pipeline.

NEW "general to specific" approach:
  1. Text classification — extract title, composer, part names, lyrics, tempo
  2. Staff detection   — find staves, groups (bracket/brace), systems
  3. Staff splitting    — cut each staff group into a separate image
  4. OMR per staff      — run homr on each staff image independently
  5. Score building     — assemble multi-part MusicXML with correct structure
  6. Lyrics alignment   — attach lyrics to vocal parts only
  7. Validation         — check measure completeness, note ranges

Usage:
    python convert_pdf_to_musicxml.py <pdf_path> [output_path] [--engine homr|oemer|audiveris]
    python convert_pdf_to_musicxml.py data/uploads/Alleluja_-_werset_sw_Anna.pdf
"""

import sys
import argparse
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.ocr.omr_engine import get_engine, get_best_available_engine, OMREngineType
from src.ocr.preprocessing import ImagePreprocessor
from src.ocr.text_classifier import TextClassifier
from src.ocr.staff_detector import StaffDetector
from src.ocr.staff_splitter import StaffSplitter
from src.ocr.score_builder import ScoreBuilder
from src.ocr.lyrics_aligner import LyricsAligner
from src.ocr.musicxml_validator import MusicXMLValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def convert_pdf_to_musicxml(
    pdf_path: str,
    output_path: str = None,
    engine_name: str = None,
) -> str:
    """Convert a PDF file to MusicXML using the full OMR pipeline.

    Args:
        pdf_path: Path to the input PDF file
        output_path: Optional output path for the MusicXML file
        engine_name: OMR engine to use ('homr', 'oemer', 'audiveris').
            If None, auto-selects the best available engine.

    Returns:
        Path to the generated MusicXML file, or empty string on failure
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return ""

    output_dir = Path("data/processed")
    output_dir.mkdir(parents=True, exist_ok=True)

    # ===================================================================
    print(f"\n{'=' * 60}")
    print(f"  Church Music OMR Pipeline (v2 — general to specific)")
    print(f"{'=' * 60}")
    print(f"  Input:  {pdf_path}")

    # -------------------------------------------------------------------
    # Stage 1: Select OMR engine
    # -------------------------------------------------------------------
    if engine_name:
        try:
            engine_type = OMREngineType(engine_name.lower())
            engine = get_engine(engine_type)
        except (ValueError, RuntimeError) as e:
            logger.error(f"Engine '{engine_name}' not available: {e}")
            return ""
    else:
        engine = get_best_available_engine()
        if engine is None:
            logger.error(
                "No OMR engine available. Install homr (pip install homr) "
                "or oemer (pip install oemer)."
            )
            return ""

    print(f"  Engine: {engine.engine_name}")

    # -------------------------------------------------------------------
    # Stage 2: Text Classification — extract metadata BEFORE OMR
    # -------------------------------------------------------------------
    print(f"\n  [1/7] Classifying text from PDF ...")
    text_classifier = TextClassifier()
    text_info = text_classifier.classify(str(pdf_path))
    print(text_classifier.get_summary(text_info))

    # -------------------------------------------------------------------
    # Stage 3: Preprocess PDF -> images
    # -------------------------------------------------------------------
    print(f"\n  [2/7] Preprocessing PDF pages ...")
    preprocessor = ImagePreprocessor(output_dir=str(output_dir / "temp"))
    processed_images = preprocessor.preprocess_for_omr(str(pdf_path))
    if not processed_images:
        logger.error("Failed to preprocess PDF pages")
        return ""
    print(f"        {len(processed_images)} page image(s)")

    # -------------------------------------------------------------------
    # Stage 4: Staff Detection — find staves, groups, systems
    # -------------------------------------------------------------------
    print(f"\n  [3/7] Detecting staff layout ...")
    staff_detector = StaffDetector()
    layout = staff_detector.detect(processed_images[0])
    print(staff_detector.get_summary(layout))

    staves_per_system = layout.num_staves_per_system

    # -------------------------------------------------------------------
    # Stage 5: Staff Splitting + per-staff OMR
    # -------------------------------------------------------------------
    print(f"\n  [4/7] Running OMR per staff ...")
    staff_splitter = StaffSplitter(output_dir=str(output_dir / "staves"))

    all_staff_results = []

    if staves_per_system >= 2 and layout.systems:
        # Split into per-staff images and run OMR on each
        for page_idx, img_path in enumerate(processed_images):
            print(f"        Page {page_idx + 1}:")

            if page_idx == 0:
                page_layout = layout
            else:
                page_layout = staff_detector.detect(img_path)

            staff_images = staff_splitter.split(img_path, page_layout)

            for si in staff_images:
                indices_str = ",".join(str(i) for i in si["staff_indices"])
                print(f"          Staff [{indices_str}] ({si['group_type']}) ...")

                try:
                    result = engine.recognize(si["path"])
                    if result.success and result.musicxml_path:
                        si["omr_result"] = result
                        print(f"            -> {result.measures_detected} measures, "
                              f"{result.staves_detected} staves detected")
                    else:
                        print(f"            -> FAILED: {result.error_message}")
                        si["omr_result"] = None
                except Exception as e:
                    print(f"            -> ERROR: {e}")
                    si["omr_result"] = None

                all_staff_results.append(si)
    else:
        # Layout detection failed or single staff — fallback to full-page OMR
        print(f"        Staff detection found {staves_per_system} staves/system.")
        print(f"        Falling back to full-page OMR ...")

        try:
            result = engine.recognize_pdf(str(pdf_path))
            if result.success:
                all_staff_results.append({
                    "path": result.musicxml_path,
                    "staff_indices": [],
                    "group_type": "full",
                    "omr_result": result,
                })
                print(f"        -> {result.measures_detected} measures, "
                      f"{result.staves_detected} staves")
            else:
                logger.error(f"Full-page OMR failed: {result.error_message}")
                return ""
        except Exception as e:
            logger.error(f"OMR failed: {e}")
            return ""

    # -------------------------------------------------------------------
    # Stage 6: Score Building — assemble multi-part MusicXML
    # -------------------------------------------------------------------
    print(f"\n  [5/7] Building multi-part MusicXML ...")

    final_stem = pdf_path.stem
    final_output = str(output_dir / f"{final_stem}_final.musicxml")

    builder = ScoreBuilder()

    staff_omr_for_builder = []
    for si in all_staff_results:
        omr = si.get("omr_result")
        if omr and omr.success and omr.musicxml_path:
            staff_omr_for_builder.append({
                "path": omr.musicxml_path,
                "staff_indices": si["staff_indices"],
                "group_type": si["group_type"],
            })

    if len(staff_omr_for_builder) >= 2:
        musicxml_out = builder.build(
            staff_omr_results=staff_omr_for_builder,
            text_info=text_info,
            layout=layout,
            output_path=final_output,
        )
        print(f"        Assembled {len(staff_omr_for_builder)} staff results")
    elif len(staff_omr_for_builder) == 1:
        omr_path = staff_omr_for_builder[0]["path"]
        musicxml_out = builder.build_from_single_omr(
            omr_musicxml_path=omr_path,
            text_info=text_info,
            layout=layout,
            output_path=final_output,
        )
        print(f"        Restructured single OMR result using layout info")
    else:
        logger.error("No successful OMR results to build from")
        return ""

    # -------------------------------------------------------------------
    # Stage 7: Lyrics Alignment — only on vocal parts
    # -------------------------------------------------------------------
    print(f"\n  [6/7] Aligning lyrics ...")

    if text_info.lyrics_syllables:
        print(f"        {len(text_info.lyrics_syllables)} syllables to align")
        preview = " ".join(text_info.lyrics_syllables[:8])
        print(f"        \"{preview} ...\"")

        aligner = LyricsAligner()
        try:
            # Determine vocal part indices from ScoreBuilder
            vocal_indices = []
            if hasattr(builder, 'last_parts_def') and builder.last_parts_def:
                for i, pdef in enumerate(builder.last_parts_def):
                    if pdef.is_vocal:
                        vocal_indices.append(i)
            if not vocal_indices:
                vocal_indices = [0]  # fallback

            from src.ocr.pdf_text_extractor import LyricsData
            lyrics_data = LyricsData(
                title=text_info.title,
                composer=text_info.composer,
                syllables=text_info.lyrics_syllables,
            )

            musicxml_out = aligner.align_from_lyrics_data(
                musicxml_path=musicxml_out,
                lyrics_data=lyrics_data,
                vocal_part_indices=vocal_indices,
                output_path=musicxml_out,
            )
            print(f"        Lyrics aligned to parts {vocal_indices}")
        except Exception as e:
            logger.warning(f"Lyrics alignment failed: {e}")
    else:
        print(f"        No lyrics found in text layer")

    # -------------------------------------------------------------------
    # Stage 8: Validation
    # -------------------------------------------------------------------
    print(f"\n  [7/7] Validating MusicXML ...")
    validator = MusicXMLValidator()
    try:
        report = validator.validate_and_fix(musicxml_out)
        print(validator.get_report_text(report))
    except Exception as e:
        logger.warning(f"Validation failed: {e}")

    # -------------------------------------------------------------------
    # Final output
    # -------------------------------------------------------------------
    if output_path:
        import shutil
        shutil.copy2(musicxml_out, output_path)
        final_path = output_path
    else:
        final_path = musicxml_out

    print(f"\n{'=' * 60}")
    print(f"  Output:  {final_path}")
    print(f"  Open this file in MuseScore to view/edit the score.")
    print(f"{'=' * 60}\n")

    return final_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert sheet music PDF to MusicXML using OMR"
    )
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument("output_path", nargs="?", default=None,
                        help="Output MusicXML path (optional)")
    parser.add_argument("--engine", choices=["homr", "oemer", "audiveris"],
                        default=None, help="OMR engine to use (auto if omitted)")

    args = parser.parse_args()

    result = convert_pdf_to_musicxml(
        args.pdf_path,
        args.output_path,
        args.engine,
    )

    if result:
        print(f"Done! Output: {result}")
    else:
        print("\nConversion failed.")
        sys.exit(1)


if __name__ == '__main__':
    main()
