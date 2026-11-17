"""Tests for PUMS joint household types (#8) and the 'realistic' sampler built on them."""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path
from types import ModuleType

import pytest
from govsynth.evaluation.representativeness import pums_crosscheck
from govsynth.models.enums import CitizenshipStatus
from govsynth.profiles.us_household import USHouseholdProfile
from govsynth.sources.us.census import DEFAULT_CENSUS_VINTAGE, vintage_dir
from govsynth.sources.us.census_fetcher import FIPS_CODES
from govsynth.sources.us.household_types import load_household_types

PUMS_DIR = vintage_dir(DEFAULT_CENSUS_VINTAGE) / "pums"
ROOT = Path(__file__).resolve().parents[2]


def _build_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_pums_households", ROOT / "scripts/build_pums_households.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestBundledFiles:
    def test_every_state_has_types(self) -> None:
        missing = [st for st in sorted(FIPS_CODES) if load_household_types(st) is None]
        assert not missing

    @pytest.mark.parametrize("state", sorted(FIPS_CODES))
    def test_file_shape_and_privacy(self, state: str) -> None:
        raw = json.loads((PUMS_DIR / f"{state.lower()}.json").read_text())
        meta = raw["_metadata"]
        assert meta["state"] == state
        assert meta["min_records_per_type"] >= 3
        assert meta["dropped_weight_share"] < 0.01
        assert len(raw["fields"]) == 9
        for t in raw["types"]:
            # Aggregates only: nine numbers per type, no identifiers.
            assert len(t) == 9
            assert 1 <= t[0] <= 6
            assert 0 <= t[1] < len(raw["income_edges"]) - 1
            assert 0 <= t[6] < len(raw["age_bands"])
            assert t[7] > 0
            assert 0.0 <= t[8] <= 1.0
        assert "SERIALNO" not in json.dumps(raw)

    @pytest.mark.parametrize("state", sorted(FIPS_CODES))
    def test_types_agree_with_summary_tables(self, state: str) -> None:
        bad = [c for c in pums_crosscheck(state) if not c.ok]
        assert not bad, bad

    def test_one_person_households_have_no_children(self) -> None:
        types = load_household_types("VA")
        assert types is not None
        assert not any(t.size == 1 and t.kids for t in types.types)


class TestReassignSmallCells:
    def test_small_cell_folds_into_nearest_neighbour(self) -> None:
        mod = _build_script()
        cells = {
            (2, 5, 0, 0, 1, 1, 1): [100.0, 10, 80.0],
            (2, 9, 0, 0, 1, 1, 1): [100.0, 10, 50.0],
            (2, 6, 0, 0, 1, 1, 1): [7.0, 1, 7.0],  # small: nearest is band 5
        }
        kept, reassigned, dropped = mod.reassign_small_cells(cells, 3)
        assert set(kept) == {(2, 5, 0, 0, 1, 1, 1), (2, 9, 0, 0, 1, 1, 1)}
        assert kept[(2, 5, 0, 0, 1, 1, 1)] == [107.0, 10, 87.0]
        assert (reassigned, dropped) == (7.0, 0.0)

    def test_relaxes_citizenship_before_dropping(self) -> None:
        mod = _build_script()
        cells = {(3, 4, 0, 1, 1, 1, 1): [50.0, 5, 40.0], (3, 4, 0, 1, 1, 0, 1): [5.0, 1, 4.0]}
        kept, reassigned, dropped = mod.reassign_small_cells(cells, 3)
        assert kept[(3, 4, 0, 1, 1, 1, 1)][0] == 55.0
        assert (reassigned, dropped) == (5.0, 0.0)

    def test_never_crosses_size_or_children(self) -> None:
        mod = _build_script()
        cells = {(3, 4, 0, 1, 1, 1, 1): [50.0, 5, 40.0], (4, 4, 0, 1, 1, 1, 1): [5.0, 1, 4.0]}
        kept, _, dropped = mod.reassign_small_cells(cells, 3)
        assert kept[(3, 4, 0, 1, 1, 1, 1)][0] == 50.0
        assert dropped == 5.0


class TestSampler:
    def test_realistic_uses_household_types(self) -> None:
        p = USHouseholdProfile.random(state="VA", seed=42, strategy="realistic")
        assert p.household_model == "pums_household_types"
        assert p.census_vintage == DEFAULT_CENSUS_VINTAGE.label

    def test_deterministic(self) -> None:
        a = [USHouseholdProfile.random(state="TX", seed=42 + i, strategy="realistic") for i in range(50)]
        b = [USHouseholdProfile.random(state="TX", seed=42 + i, strategy="realistic") for i in range(50)]
        assert [(p.household_size, p.monthly_gross_income, p.age_of_head) for p in a] == [
            (p.household_size, p.monthly_gross_income, p.age_of_head) for p in b
        ]

    def test_profiles_are_consistent_with_some_type(self) -> None:
        types = load_household_types("VA")
        assert types is not None
        keys = {(t.size, t.eld_dis, t.kids, t.earns) for t in types.types}
        for i in range(300):
            p = USHouseholdProfile.random(state="VA", seed=i, strategy="realistic")
            earns = (p.earned_income or 0) > 0
            # A type with earnings but $0 income yields no earned dollars; allow either flag then.
            assert (p.household_size, p.has_elderly_or_disabled, p.has_dependent_children, earns) in keys or (
                p.monthly_gross_income == 0
            )
            assert p.age_of_head is not None and 18 <= p.age_of_head <= 99
            assert (p.earned_income or 0) + (p.unearned_income or 0) == pytest.approx(p.monthly_gross_income)

    def test_joint_structure_is_kept(self) -> None:
        """The point of #8: traits are correlated, not independent."""
        ps = [USHouseholdProfile.random(state="VA", seed=i, strategy="realistic") for i in range(3000)]
        single = [p for p in ps if p.household_size == 1]
        assert not any(p.has_dependent_children for p in single)
        old = [p for p in ps if (p.age_of_head or 0) >= 75]
        young = [p for p in ps if (p.age_of_head or 0) < 45]
        earn = lambda g: sum((p.earned_income or 0) > 0 for p in g) / len(g)  # noqa: E731
        assert earn(old) < 0.5 < earn(young)
        assert all(p.has_elderly_or_disabled for p in ps if (p.age_of_head or 0) >= 60)

    def test_noncitizen_heads_split_into_qualified_and_not(self) -> None:
        ps = [USHouseholdProfile.random(state="CA", seed=i, strategy="realistic") for i in range(3000)]
        statuses = {p.citizenship_status for p in ps}
        assert CitizenshipStatus.QUALIFIED_ALIEN in statuses
        assert CitizenshipStatus.NON_QUALIFIED_ALIEN in statuses

    def test_income_dollar_year_restates(self) -> None:
        base = USHouseholdProfile.random(state="VA", seed=7, strategy="realistic")
        later = USHouseholdProfile.random(state="VA", seed=7, strategy="realistic", income_dollar_year=2026)
        assert later.income_dollar_year == 2026
        if base.monthly_gross_income > 1000:
            assert later.monthly_gross_income > base.monthly_gross_income

    def test_sample_follows_weights(self) -> None:
        types = load_household_types("VA")
        assert types is not None
        rng = random.Random(0)
        n = 20000
        got = sum(types.sample(rng).kids for _ in range(n)) / n
        assert got == pytest.approx(types.share("kids"), abs=0.015)
