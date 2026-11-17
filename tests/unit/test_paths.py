"""The bundled data directory resolves in both source checkouts and installed wheels."""

from __future__ import annotations

from pathlib import Path

import pytest
from govsynth import _paths


def test_data_dir_has_every_dataset() -> None:
    for sub in (_paths.THRESHOLD_DIR, _paths.SEED_DIR, _paths.CENSUS_DIR, _paths.CASELOAD_DIR):
        assert sub.is_dir(), sub


def test_prefers_packaged_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "site-packages" / "govsynth"
    (pkg / "data" / "thresholds").mkdir(parents=True)
    monkeypatch.setattr(_paths, "_PACKAGE_DIR", pkg)
    assert _paths._find_data_dir() == pkg / "data"


def test_falls_back_to_checkout_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "repo" / "govsynth"
    pkg.mkdir(parents=True)
    (tmp_path / "repo" / "data" / "thresholds").mkdir(parents=True)
    monkeypatch.setattr(_paths, "_PACKAGE_DIR", pkg)
    assert _paths._find_data_dir() == tmp_path / "repo" / "data"


def test_missing_data_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_paths, "_PACKAGE_DIR", tmp_path / "govsynth")
    with pytest.raises(FileNotFoundError, match="data directory not found"):
        _paths._find_data_dir()
