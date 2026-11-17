"""Tests for the representativeness check (#12) -- run for every bundled state."""

from __future__ import annotations

import math

import pytest
from govsynth.cli.main import app
from govsynth.evaluation.representativeness import check_state, truncated_lognormal_median
from govsynth.sources.us.census_fetcher import FIPS_CODES
from typer.testing import CliRunner


@pytest.mark.parametrize("state", sorted(FIPS_CODES))
def test_realistic_profiles_match_census_targets(state: str) -> None:
    bad = [c for c in check_state(state, n=1000, seed=42) if not c.ok]
    assert not bad, bad


def test_every_bundled_census_file_is_plausible() -> None:
    from govsynth.evaluation.representativeness import plausibility_problems
    from govsynth.sources.us.census import available_vintages

    problems = [p for v in available_vintages() for st in sorted(FIPS_CODES) for p in plausibility_problems(st, v)]
    assert not problems, problems[:10]


def test_plausibility_catches_the_original_mislabeled_children_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """The original bug read '% with children' from married-couple rows: 0.756 for VA."""
    from govsynth.evaluation.representativeness import plausibility_problems
    from govsynth.sources.us import census

    real_load = census.CensusDataSource.load

    def corrupted(self: census.CensusDataSource) -> census.CensusDistribution | None:
        dist = real_load(self)
        if dist is not None:
            dist.pct_with_children = 0.756
        return dist

    monkeypatch.setattr(census.CensusDataSource, "load", corrupted)
    assert any("pct_with_children" in p for p in plausibility_problems("VA"))


def test_check_flags_a_sampler_that_ignores_its_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the sampler drifts from the data (e.g. hard-coded rates), the check fails."""
    import govsynth.profiles.us_household as uh

    real = uh._build_realistic_profile

    def drifting(*args: object, **kwargs: object) -> uh.USHouseholdProfile:
        profile = real(*args, **kwargs)  # type: ignore[arg-type]
        profile.has_dependent_children = profile.household_size > 1  # ~70%, far from the ~30% target
        return profile

    monkeypatch.setattr(uh, "_build_realistic_profile", drifting)
    checks = {c.metric: c for c in check_state("VA", n=1000)}
    assert not checks["pct_with_children"].ok


def test_truncated_median() -> None:
    assert truncated_lognormal_median(8.0, 1.0, 1e12) == pytest.approx(math.exp(8.0), rel=1e-6)
    assert truncated_lognormal_median(8.0, 1.0, math.exp(9.0)) < math.exp(8.0)


def test_cli() -> None:
    runner = CliRunner()
    ok = runner.invoke(app, ["validate-distribution", "--state", "VA", "-n", "800"])
    assert ok.exit_code == 0, ok.output
    assert runner.invoke(app, ["validate-distribution", "--state", "ZZ"]).exit_code == 2
    js = runner.invoke(app, ["validate-distribution", "--state", "MD", "-n", "500", "--json"])
    assert js.exit_code == 0 and '"status": "ok"' in js.stdout
