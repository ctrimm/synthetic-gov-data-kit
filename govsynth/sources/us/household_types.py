"""Joint household types built from ACS PUMS (#8), for 'realistic' profile sampling.

data/census/<survey>/<year>/pums/<state>.json (built by
scripts/build_pums_households.py) holds weighted household *types* -- size, income
band, any member 60+ or disabled, any member under 18, has earnings, head is a
citizen, head's age band -- with each type's weighted mean earned share of income.
Drawing a whole type keeps the correlations between those traits that independent
per-trait rates lose. No individual record is stored; values within a type are
drawn synthetically.
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from govsynth.sources.base import _load_json_file
from govsynth.sources.us.census import CensusVintage, vintage_dir


@dataclass(frozen=True)
class HouseholdType:
    """One weighted PUMS household type."""

    size: int
    income_band: int
    eld_dis: bool
    kids: bool
    earns: bool
    head_citizen: bool
    age_band: int
    weight: float
    earned_share: float


class HouseholdTypes:
    """The weighted household types for one state and vintage."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.income_edges: list[int] = raw["income_edges"]
        self.age_bands: list[list[int]] = raw["age_bands"]
        self.types = [
            HouseholdType(
                size=int(t[0]),
                income_band=int(t[1]),
                eld_dis=bool(t[2]),
                kids=bool(t[3]),
                earns=bool(t[4]),
                head_citizen=bool(t[5]),
                age_band=int(t[6]),
                weight=float(t[7]),
                earned_share=float(t[8]),
            )
            for t in raw["types"]
        ]
        cumulative = 0.0
        self._cum: list[float] = []
        for t in self.types:
            cumulative += t.weight
            self._cum.append(cumulative)

    @property
    def total_weight(self) -> float:
        """Sum of type weights (weighted households after suppression)."""
        return self._cum[-1]

    def sample(self, rng: random.Random) -> HouseholdType:
        """Draw one type with probability proportional to its weight."""
        return self.types[bisect.bisect_right(self._cum, rng.random() * self.total_weight)]

    def draw_annual_income(self, t: HouseholdType, rng: random.Random) -> float:
        """Uniform annual income within the type's band."""
        return rng.uniform(self.income_edges[t.income_band], self.income_edges[t.income_band + 1])

    def draw_head_age(self, t: HouseholdType, rng: random.Random) -> int:
        """Uniform head age within the type's band, at least 18."""
        lo, hi = self.age_bands[t.age_band]
        return rng.randint(max(lo, 18), max(hi, 18))

    def share(self, attr: str) -> float:
        """Weighted share of households for which a boolean attribute is true."""
        return sum(t.weight for t in self.types if getattr(t, attr)) / self.total_weight

    def size_share(self, size: int) -> float:
        """Weighted share of households of a given size (6 = six or more)."""
        return sum(t.weight for t in self.types if t.size == size) / self.total_weight

    def median_annual_income(self) -> float:
        """Weighted median annual income, interpolating uniformly within bands."""
        return self._median_and_density()[0]

    def density_at_median(self) -> float:
        """Probability density of annual income at the median (per dollar)."""
        return self._median_and_density()[1]

    def _median_and_density(self) -> tuple[float, float]:
        by_band = [0.0] * (len(self.income_edges) - 1)
        for t in self.types:
            by_band[t.income_band] += t.weight
        half = self.total_weight / 2
        seen = 0.0
        for i, w in enumerate(by_band):
            lo, hi = self.income_edges[i], self.income_edges[i + 1]
            if w and seen + w >= half:
                return lo + (half - seen) / w * (hi - lo), w / self.total_weight / (hi - lo)
            seen += w
        return float(self.income_edges[-1]), 0.0


def household_types_path(state: str, vintage: CensusVintage, data_dir: Path | None = None) -> Path:
    """Path of the PUMS household-types file for a state and vintage."""
    return vintage_dir(vintage, data_dir) / "pums" / f"{state.lower()}.json"


@lru_cache(maxsize=128)
def _load(path_str: str) -> HouseholdTypes:
    return HouseholdTypes(_load_json_file(path_str))


def load_household_types(
    state: str, vintage: CensusVintage | int | str | None = None, data_dir: Path | None = None
) -> HouseholdTypes | None:
    """The PUMS household types for a state and vintage, or None if not built."""
    from govsynth.sources.us.census import DEFAULT_CENSUS_VINTAGE

    v = CensusVintage.parse(vintage) if vintage is not None else DEFAULT_CENSUS_VINTAGE
    path = household_types_path(state, v, data_dir)
    return _load(str(path)) if path.exists() else None
