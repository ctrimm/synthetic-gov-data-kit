"""Where govsynth's bundled data lives.

In a source checkout the data is the repository's top-level ``data/`` directory.
In an installed wheel it is packaged inside the package as ``govsynth/data``
(pyproject.toml force-includes ``data/`` there), because a top-level ``data``
directory would land at ``site-packages/data`` and collide with other packages.
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def _find_data_dir() -> Path:
    for candidate in (_PACKAGE_DIR / "data", _PACKAGE_DIR.parent / "data"):
        if (candidate / "thresholds").is_dir():
            return candidate
    raise FileNotFoundError(
        f"govsynth data directory not found (looked in {_PACKAGE_DIR / 'data'} and {_PACKAGE_DIR.parent / 'data'}). "
        "Reinstall the package, or run from a source checkout."
    )


DATA_DIR = _find_data_dir()
THRESHOLD_DIR = DATA_DIR / "thresholds"
SEED_DIR = DATA_DIR / "seeds"
CENSUS_DIR = DATA_DIR / "census"
CASELOAD_DIR = DATA_DIR / "caseload"
