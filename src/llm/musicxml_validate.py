"""Validate MusicXML produced by an LLM before it is persisted.

The LLM agents in steps 4 and 5 rewrite MusicXML, which is risky: a single broken
tag yields a file that no notation software can open.  Every LLM output is therefore
round-tripped through ``music21`` (already a project dependency) and only accepted
when it passes a set of structural + rhythmic checks — otherwise the caller keeps the
previous, known-good version.

Public API
----------
``validate_musicxml(xml) -> (ok, reason, score)``
    Returns a 3-tuple: success flag, human-readable reason (``None`` on success), and
    the parsed music21 ``Score`` (``None`` on failure). Reusing the returned ``Score``
    for the subsequent export avoids a second parse.

``export_score_to_mxl(score) -> bytes``
    Write a music21 ``Score`` to a compressed ``.mxl`` archive and return the raw bytes.
    Used to produce a MuseScore-compatible artifact after a successful validation.
"""

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


def load_musicxml_text(path: str) -> str:
    """Return the plain MusicXML text for a file, decompressing ``.mxl`` if needed.

    Audiveris writes compressed ``.mxl`` (a zip containing the score plus ``META-INF``);
    the LLM agents need uncompressed MusicXML. Uncompressed ``.xml`` files are read as-is.

    Raises:
        ValueError: when a ``.mxl`` archive contains no MusicXML entry.
    """
    p = Path(path)
    if p.suffix.lower() != ".mxl":
        return p.read_text(encoding="utf-8")

    with zipfile.ZipFile(p) as zf:
        rootfile: Optional[str] = None
        # The container manifest names the primary score file.
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8")
            match = re.search(r'full-path\s*=\s*"([^"]+)"', container)
            if match:
                rootfile = match.group(1)
        except KeyError:
            pass

        if rootfile is None:
            candidates = [
                n
                for n in zf.namelist()
                if not n.startswith("META-INF") and n.lower().endswith((".xml", ".musicxml"))
            ]
            if not candidates:
                raise ValueError(f"Archiwum .mxl nie zawiera pliku MusicXML: {path}")
            rootfile = candidates[0]

        return zf.read(rootfile).decode("utf-8")


# ---------------------------------------------------------------------------
# Główna walidacja
# ---------------------------------------------------------------------------


def validate_musicxml(xml: str) -> Tuple[bool, Optional[str], Optional[Any]]:
    """Parse ``xml`` with music21 and run structural + rhythmic checks.

    Checks (in order):
      1. dokument parsuje się przez music21,
      2. zawiera >=1 partię (``part``),
      3. zawiera >=1 nutę,
      4. zawiera deklarację ``<divisions>`` (wymaganą przez MuseScore).

    Przepełnione takty oraz osierocone wiązania są LOGOWANE jako ostrzeżenia, ale NIE
    powodują odrzucenia — sprawdzono empirycznie, że MuseScore importuje takie pliki
    (Audiveris bywa o pół wartości za długi w pojedynczym takcie, a wynik z recall≈1.0
    nie powinien być wyrzucany przez tak drobny błąd, który użytkownik łatwo poprawi).

    Returns:
        ``(True, None, score)`` gdy dokument poprawny — ``score`` to sparsowany obiekt
        music21 gotowy do eksportu bez ponownego parsowania;
        ``(False, "<powód>", None)`` gdy dokument odrzucony.
    """
    if not xml or not xml.strip():
        return False, "Pusty dokument MusicXML.", None

    # Imported lazily — music21 import is comparatively heavy.
    from music21 import converter

    try:
        score = converter.parseData(xml, format="musicxml")
    except Exception as exc:  # music21 raises a broad family of parse errors
        logger.warning("validate_musicxml: music21 nie sparsował dokumentu: %s", exc)
        return False, f"music21 nie sparsował dokumentu: {exc}", None

    try:
        parts = list(score.parts)
    except Exception as exc:
        return False, f"Błąd przy odczycie partii: {exc}", None
    if not parts:
        return False, "Brak partii (part) w dokumencie — wymagana co najmniej jedna.", None

    try:
        note_count = len(list(score.recurse().notes))
    except Exception as exc:
        return False, f"Dokument sparsowany, ale nieczytelny dla music21: {exc}", None
    if note_count == 0:
        return False, "Dokument sparsowany, ale nie zawiera żadnych nut.", None

    if not re.search(r"<divisions\s*>", xml):
        return (
            False,
            "Brak deklaracji <divisions> w dokumencie — MuseScore może odrzucić plik.",
            None,
        )

    overfull = _check_rhythmic_sums(score)
    if overfull:
        logger.warning(
            "validate_musicxml: %s (nie odrzucam — MuseScore importuje takie pliki)", overfull
        )

    _warn_orphaned_ties(score)
    return True, None, score


# ---------------------------------------------------------------------------
# Pomocnicze sprawdzenia
# ---------------------------------------------------------------------------


def _check_rhythmic_sums(score) -> Optional[str]:
    """Zwróć komunikat błędu, gdy takt (poza pierwszym) jest znacznie przepełniony.

    Tolerancja: ``max(5% długości taktu, 0.1 ćwierćnuty)`` — filtruje błędy
    zmiennoprzecinkowe. Pierwszy takt każdej partii jest pomijany (anakruza/pickup).
    """
    problematic = []
    for part_idx, part in enumerate(score.parts):
        try:
            measures = list(part.getElementsByClass("Measure"))
        except Exception:
            continue

        for m_idx, measure in enumerate(measures):
            if m_idx == 0:
                continue  # anakruza/pickup w pierwszym takcie — dozwolona
            try:
                bar_ql = measure.barDuration.quarterLength
                actual_ql = measure.highestTime
            except Exception:
                continue
            if bar_ql <= 0:
                continue
            tolerance = max(bar_ql * 0.05, 0.1)
            if actual_ql > bar_ql + tolerance:
                measure_num = getattr(measure, "number", None) or (m_idx + 1)
                problematic.append(
                    f"takt {measure_num} partia {part_idx + 1}: "
                    f"{actual_ql:.2f} > {bar_ql:.2f} ćwierćnuty"
                )

    if not problematic:
        return None

    sample = "; ".join(problematic[:3])
    suffix = "..." if len(problematic) > 3 else ""
    return (
        f"Przepełnione takty — MuseScore może odrzucić plik "
        f"({len(problematic)} taktów): {sample}{suffix}."
    )


def _warn_orphaned_ties(score) -> None:
    """Loguj ostrzeżenie, gdy zakończenie wiązania (tie stop) pojawia się bez otwarcia."""
    orphan_count = 0
    for part in score.parts:
        try:
            open_pitches: dict = {}
            for n in part.recurse().getElementsByClass("Note"):
                tie = getattr(n, "tie", None)
                if tie is None:
                    continue
                key = n.pitch.nameWithOctave
                if tie.type == "start":
                    open_pitches[key] = True
                elif tie.type in ("stop", "continue"):
                    if key not in open_pitches:
                        orphan_count += 1
                    elif tie.type == "stop":
                        open_pitches.pop(key, None)
        except Exception:
            continue

    if orphan_count > 0:
        logger.warning(
            "validate_musicxml: %d osieroconych zakończeń wiązań (tie bez start) — "
            "może powodować błędy w MuseScore.",
            orphan_count,
        )


# ---------------------------------------------------------------------------
# Eksport do .mxl
# ---------------------------------------------------------------------------


def export_score_to_mxl(score) -> bytes:
    """Zapisz obiekt music21 ``Score`` do skompresowanego ``.mxl`` i zwróć bajty.

    Używa katalogu tymczasowego (``score.write`` wymaga ścieżki na dysku) i zawsze
    sprząta po sobie. Zwraca kompletne archiwum ZIP kompatybilne z MuseScore.

    Raises:
        Exception: gdy music21 nie może wyeksportować lub odczytać wyniku.
    """
    tmpdir = tempfile.mkdtemp(prefix="cmo_mxl_")
    out_path = Path(tmpdir) / "score.mxl"
    try:
        written = score.write("mxl", fp=str(out_path))
        result_path = Path(written) if written else out_path
        return result_path.read_bytes()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def export_score_to_musicxml(score) -> str:
    """Zapisz obiekt music21 ``Score`` do NIESKOMPRESOWANEGO ``.musicxml`` i zwróć tekst.

    Nieskompresowany MusicXML jest preferowanym formatem wynikowym pipeline'u: można go
    przeglądać i edytować element po elemencie oraz precyzyjnie porównywać (diff) z referencją.
    MuseScore otwiera go tak samo jak ``.mxl``.

    Raises:
        Exception: gdy music21 nie może wyeksportować lub odczytać wyniku.
    """
    tmpdir = tempfile.mkdtemp(prefix="cmo_xml_")
    out_path = Path(tmpdir) / "score.musicxml"
    try:
        written = score.write("musicxml", fp=str(out_path))
        result_path = Path(written) if written else out_path
        return result_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
