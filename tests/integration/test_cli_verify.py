"""Integration tests for govsynth verify-thresholds."""

import json

from govsynth.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _snap_report() -> tuple[int, dict]:
    result = runner.invoke(app, ["verify-thresholds", "--program", "snap", "--json"])
    return result.exit_code, json.loads(result.output)


def test_verify_thresholds_snap_all_verified() -> None:
    """Every SNAP file, including the FY2021-FY2025 BBCE tables (verified in #23), is verified."""
    exit_code, data = _snap_report()
    assert exit_code == 0
    assert data["unverified"] == []


def test_verify_thresholds_default_exits_one_for_unverified() -> None:
    """Default run (no filter) finds medicaid_cy2026.json as unverified → exit 1."""
    result = runner.invoke(app, ["verify-thresholds"])
    assert result.exit_code == 1


def test_verify_thresholds_json_output_has_required_fields() -> None:
    _, data = _snap_report()
    assert "status" in data
    assert "checked" in data
    assert "unverified" in data
    assert isinstance(data["unverified"], list)


def test_verify_thresholds_filter_by_program() -> None:
    _, data = _snap_report()
    # snap_fy2021-2026 and snap_bbce_fy2021-2026; the estimated Medicaid file is filtered out.
    assert data["checked"] == 12
    assert all(entry["file"].startswith("snap_") for entry in data["unverified"])


def test_verify_thresholds_invalid_program_exits_two() -> None:
    result = runner.invoke(app, ["verify-thresholds", "--program", "notaprogram"])
    assert result.exit_code == 2
