"""Static guard: every save_uploaded_file call-site in app+service code must use use_library=True.

Two documented fallback call-sites legitimately omit use_library=True — the else-branches in
``pipeline_service._save_musicxml`` and ``omr_service.process_file`` that run when the piece
row cannot be found (defensive guard, should not happen in normal flow). Any NEW call without
``use_library=True`` is a regression and this test must catch it.

Usage (verify the guard works before committing a new upload handler):
    poetry run pytest tests/unit/test_use_library_guard.py -v
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parents[2]

# Files whose save_uploaded_file call-sites are guarded.
# The legacy Streamlit app (src/app/_legacy/) is intentionally excluded.
_GUARDED_FILES = [
    ROOT / "src" / "app_ng" / "pages" / "library.py",
    ROOT / "src" / "app_ng" / "pages" / "processing.py",
    ROOT / "src" / "services" / "pipeline_service.py",
    ROOT / "src" / "services" / "omr_service.py",
]

# Number of documented fallback calls that legitimately omit use_library=True.
# pipeline_service._save_musicxml else-branch  → 1
# omr_service.process_file else-branch         → 1
_KNOWN_FALLBACK_COUNT = 2


# ---------------------------------------------------------------------------
# AST helper
# ---------------------------------------------------------------------------


def _calls_without_library(source: str) -> list[tuple[int, str]]:
    """Return (lineno, description) for every save_uploaded_file call that does NOT
    pass use_library=True as a keyword argument.

    Detects both:
    - ``FileService.save_uploaded_file(...)`` (attribute call)
    - ``save_uploaded_file(...)``             (direct name call)

    A call is flagged when ``use_library=True`` is absent OR when ``use_library=False``
    is explicitly given.
    """
    tree = ast.parse(source)
    result: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_target_call = (
            isinstance(func, ast.Attribute) and func.attr == "save_uploaded_file"
        ) or (isinstance(func, ast.Name) and func.id == "save_uploaded_file")
        if not is_target_call:
            continue
        has_use_library_true = any(
            kw.arg == "use_library"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
        if not has_use_library_true:
            result.append((node.lineno, f"save_uploaded_file call at line {node.lineno}"))
    return result


# ---------------------------------------------------------------------------
# Meta-tests: the helper itself must behave correctly
# ---------------------------------------------------------------------------


def test_helper_detects_call_without_use_library_kwarg():
    """Helper must flag a call that omits use_library entirely."""
    source = textwrap.dedent("""
        FileService.save_uploaded_file(piece_id=1, filename="x.pdf", file_data=b"x")
        """)
    found = _calls_without_library(source)
    assert len(found) == 1, f"Expected 1 violation, got {found}"


def test_helper_detects_explicit_use_library_false():
    """Helper must flag a call that explicitly passes use_library=False."""
    source = textwrap.dedent("""
        FileService.save_uploaded_file(
            piece_id=1, filename="x.pdf", file_data=b"x", use_library=False
        )
        """)
    found = _calls_without_library(source)
    assert len(found) == 1, f"Expected 1 violation for use_library=False, got {found}"


def test_helper_accepts_use_library_true():
    """Helper must NOT flag a call that passes use_library=True."""
    source = textwrap.dedent("""
        FileService.save_uploaded_file(
            piece_id=1, filename="x.pdf", file_data=b"x",
            use_library=True, piece=piece, kind=kind,
        )
        """)
    found = _calls_without_library(source)
    assert found == [], f"Expected no violations for use_library=True, got {found}"


def test_helper_detects_bare_name_call():
    """Helper detects a bare ``save_uploaded_file(...)`` call (not via FileService)."""
    source = textwrap.dedent("""
        result = save_uploaded_file(piece_id=p, filename="f.pdf", file_data=data)
        """)
    found = _calls_without_library(source)
    assert len(found) == 1, f"Expected 1 bare-name violation, got {found}"


def test_helper_handles_multi_line_calls():
    """Helper correctly handles calls split across multiple lines."""
    source = textwrap.dedent("""
        stored_path = FileService.save_uploaded_file(
            piece_id=piece_id,
            filename=filename,
            file_data=out_text.encode("utf-8"),
        )
        """)
    found = _calls_without_library(source)
    assert len(found) == 1, f"Expected 1 multi-line violation, got {found}"


def test_helper_ignores_function_definition():
    """Function *definition* ``def save_uploaded_file(...)`` must not be counted."""
    source = textwrap.dedent("""
        def save_uploaded_file(piece_id, filename, file_data, use_library=False):
            pass
        """)
    found = _calls_without_library(source)
    assert found == [], f"Function definition must not be flagged, got {found}"


# ---------------------------------------------------------------------------
# Main guard: guarded files must not gain new non-library call-sites
# ---------------------------------------------------------------------------


def test_save_uploaded_file_non_library_calls_count_equals_known_fallbacks():
    """Guard: the total number of save_uploaded_file calls without use_library=True in
    guarded files must equal the number of documented fallback exceptions (2).

    Fails immediately if:
    - A new upload call is added without use_library=True (count rises above 2).
    - An existing fallback is removed without updating _KNOWN_FALLBACK_COUNT (count drops).
    """
    violations: list[str] = []
    for path in _GUARDED_FILES:
        source = path.read_text(encoding="utf-8")
        for lineno, _ in _calls_without_library(source):
            violations.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert len(violations) == _KNOWN_FALLBACK_COUNT, (
        f"Expected exactly {_KNOWN_FALLBACK_COUNT} documented fallback calls without "
        f"use_library=True in guarded files, found {len(violations)}:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n\nIf you added a new upload call: pass use_library=True + piece + kind.\n"
        "If you removed a known fallback: decrease _KNOWN_FALLBACK_COUNT accordingly."
    )


def test_app_ng_pages_have_zero_calls_without_library():
    """Strict check: NiceGUI UI pages must have ZERO save_uploaded_file calls without
    use_library=True.

    The two known fallbacks live in the service layer (pipeline_service, omr_service),
    not in the UI layer. This test ensures no UI regression sneaks in.
    """
    ui_pages = [p for p in _GUARDED_FILES if "app_ng" in str(p)]
    violations: list[str] = []
    for path in ui_pages:
        source = path.read_text(encoding="utf-8")
        for lineno, _ in _calls_without_library(source):
            violations.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert violations == [], (
        "NiceGUI page(s) have save_uploaded_file calls without use_library=True "
        "(UI layer must never fall back to data/uploads):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_guarded_files_all_exist():
    """All guarded files must exist — detect accidental renames or deletions."""
    missing = [str(p.relative_to(ROOT)) for p in _GUARDED_FILES if not p.exists()]
    assert (
        missing == []
    ), "Guarded files no longer exist. Update _GUARDED_FILES in this test:\n" + "\n".join(
        f"  - {m}" for m in missing
    )
