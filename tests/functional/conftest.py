"""Configuration for functional tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    """Skip functional tests if no fixture files exist."""
    scans_dir = FIXTURES_DIR / "scans"
    has_fixtures = any(scans_dir.glob("*")) if scans_dir.exists() else False
    if not has_fixtures:
        skip = pytest.mark.skip(reason="No fixture files in tests/functional/fixtures/scans/")
        for item in items:
            if "functional" in str(item.fspath):
                item.add_marker(skip)
