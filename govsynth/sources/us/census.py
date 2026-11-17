"""Census ACS distribution loader.

Loads data/census/<survey>/<year>/<state>.json into a typed CensusDistribution.
No network calls -- pure deserialization.

Each ACS release ("vintage") lives in its own directory, so a dataset can be
generated from a specific year's population, or from several years at once:

    data/census/acs5/2024/va.json      # ACS 2020-2024 5-year estimates
    data/census/acs1/2025/va.json      # ACS 2025 1-year estimates
    data/census/acs5/2024/national.json

Not a DataSource subclass: census distributions are profile-sampling
statistics, not program eligibility rules. Lives in sources/us/ for
colocation with other US data modules.
"""

from __future__ import annotations

import copy
import json
import re
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

_CENSUS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "census"

CensusSurvey = Literal["acs1", "acs5"]
_SURVEYS: tuple[CensusSurvey, ...] = ("acs5", "acs1")


@dataclass(frozen=True, order=True)
class CensusVintage:
    """One ACS release: a survey ('acs5' or 'acs1') and its end year.

    'acs5' 2024 means the 2020-2024 5-year estimates; 'acs1' 2025 means the
    2025 1-year estimates. 1-year data is more current; 5-year data is more
    stable. Both are available for every state.
    """

    survey: CensusSurvey
    year: int

    @property
    def label(self) -> str:
        """Stable identifier, e.g. 'acs5-2024'. Used in case metadata."""
        return f"{self.survey}-{self.year}"

    def __str__(self) -> str:
        return self.label

    @classmethod
    def parse(cls, value: CensusVintage | int | str) -> CensusVintage:
        """Parse a vintage from an int year or a string.

        A bare year means the 5-year estimates ending that year.

        Examples:
            2023 -> acs5-2023; "2023" -> acs5-2023;
            "acs1-2025" / "acs1:2025" / "ACS1 2025" -> acs1-2025

        Raises:
            ValueError: On an unrecognized survey or malformed value.
        """
        if isinstance(value, CensusVintage):
            return value
        if isinstance(value, int):
            return cls("acs5", value)
        text = value.strip().lower()
        m = re.fullmatch(r"(?:(acs[15])[-:\s_]?)?(\d{4})", text)
        if not m:
            raise ValueError(f"Unrecognized census vintage '{value}'. Use a year (2023) or survey-year (acs1-2025).")
        survey: CensusSurvey = "acs1" if m.group(1) == "acs1" else "acs5"
        return cls(survey, int(m.group(2)))


# The vintage used when none is requested. Pinned (rather than "latest on disk")
# so adding a newer census file never silently changes what an existing
# `generate(n, seed=42)` call produces. Bump deliberately when refreshing data.
DEFAULT_CENSUS_VINTAGE = CensusVintage("acs5", 2024)


def parse_census_years(spec: str) -> list[CensusVintage]:
    """Parse a CLI-style vintage spec into an ordered, de-duplicated list.

    Accepts comma-separated items, each a year, a survey-year, or an inclusive
    year range (optionally survey-prefixed).

    Examples:
        "2023"               -> [acs5-2023]
        "2021-2024"          -> [acs5-2021, acs5-2022, acs5-2023, acs5-2024]
        "acs1-2023-2025"     -> [acs1-2023, acs1-2024, acs1-2025]
        "2022,acs1-2025"     -> [acs5-2022, acs1-2025]

    Raises:
        ValueError: On a malformed item or a reversed range.
    """
    out: list[CensusVintage] = []
    for raw in spec.split(","):
        item = raw.strip().lower()
        if not item:
            continue
        m = re.fullmatch(r"(?:(acs[15])[-:\s_]?)?(\d{4})\s*-\s*(\d{4})", item)
        if m:
            survey: CensusSurvey = "acs1" if m.group(1) == "acs1" else "acs5"
            start, end = int(m.group(2)), int(m.group(3))
            if end < start:
                raise ValueError(f"Census year range '{raw.strip()}' ends before it starts.")
            out.extend(CensusVintage(survey, y) for y in range(start, end + 1))
        else:
            out.append(CensusVintage.parse(item))
    if not out:
        raise ValueError(f"No census vintages in '{spec}'.")
    return list(dict.fromkeys(out))


def normalize_census_years(
    census_years: Iterable[CensusVintage | int | str] | CensusVintage | int | str | None,
) -> list[CensusVintage] | None:
    """Normalize a user-supplied vintage or collection of vintages.

    Strings may be any `parse_census_years` spec (so "2021-2024" works anywhere
    a list is accepted). Returns None when nothing was requested.
    """
    if census_years is None:
        return None
    items: Iterable[CensusVintage | int | str]
    items = [census_years] if isinstance(census_years, CensusVintage | int | str) else census_years
    out: list[CensusVintage] = []
    for item in items:
        out.extend(parse_census_years(item) if isinstance(item, str) else [CensusVintage.parse(item)])
    if not out:
        raise ValueError("census_years is empty; pass None to use the default vintage.")
    return list(dict.fromkeys(out))


def census_years_for_strategy(
    census_years: Iterable[CensusVintage | int | str] | CensusVintage | int | str | None,
    profile_strategy: str,
) -> list[CensusVintage] | None:
    """Normalize `census_years` for a generator call and check it applies.

    Case i of a batch is sampled from vintage `years[i % len(years)]`, so a
    multi-year request is spread evenly across years and stays deterministic.

    Raises:
        ValueError: If years are given with a strategy other than 'realistic',
            the only one that samples from census data.
    """
    years = normalize_census_years(census_years)
    if years is not None and profile_strategy != "realistic":
        raise ValueError(
            f"census_years only applies to profile_strategy='realistic' (got '{profile_strategy}'); "
            "other strategies don't sample from census data."
        )
    return years


# First year the Census Bureau publishes keyless table-based summary files.
FIRST_SUMMARY_FILE_YEAR = 2021


def _fetch_command(state: str, vintage: CensusVintage) -> str:
    """The refresh command that would fetch `vintage` for `state`."""
    cmd = f"govsynth refresh-census-data --state {state.upper()} --year {vintage.year} --survey {vintage.survey}"
    if vintage.year < FIRST_SUMMARY_FILE_YEAR:
        cmd += " --source api (needs CENSUS_API_KEY; keyless files start at 2021)"
    return cmd


def check_census_available(state: str, vintages: Iterable[CensusVintage], data_dir: Path | None = None) -> None:
    """Fail fast if any requested vintage has neither this state's nor national data.

    Raises:
        ValueError: Naming the missing vintages, what is available, and the
            command that fetches them.
    """
    missing = [
        v
        for v in vintages
        if not (vintage_dir(v, data_dir) / f"{state.lower()}.json").exists()
        and not (vintage_dir(v, data_dir) / "national.json").exists()
    ]
    if missing:
        available = ", ".join(v.label for v in available_vintages(data_dir)) or "none"
        fetch = "; ".join(_fetch_command(state, v) for v in missing)
        raise ValueError(
            f"No census data for {state.upper()} in {', '.join(v.label for v in missing)}. "
            f"Available vintages: {available}. Fetch with: {fetch}"
        )


def available_vintages(data_dir: Path | None = None) -> list[CensusVintage]:
    """List the vintages that have at least one census file on disk, oldest first."""
    root = data_dir if data_dir is not None else _CENSUS_DIR
    found: list[CensusVintage] = []
    for survey in _SURVEYS:
        survey_dir = root / survey
        if not survey_dir.is_dir():
            continue
        for year_dir in survey_dir.iterdir():
            if year_dir.is_dir() and year_dir.name.isdigit() and any(year_dir.glob("*.json")):
                found.append(CensusVintage(survey, int(year_dir.name)))
    return sorted(found, key=lambda v: (v.year, v.survey))


def vintage_dir(vintage: CensusVintage, data_dir: Path | None = None) -> Path:
    """Directory holding one vintage's per-state files."""
    root = data_dir if data_dir is not None else _CENSUS_DIR
    return root / vintage.survey / str(vintage.year)


@lru_cache(maxsize=64)
def _load_census_json_cached(path_str: str) -> dict[str, Any]:
    """Cached JSON loader for census data.

    Private: returns the same dict object on every call. Use
    `_load_census_json` instead, which hands back a deep copy so callers
    can't corrupt the shared cache. After rewriting a census file
    in-process (e.g. via `refresh-census-data`), call
    `_load_census_json_cached.cache_clear()` to avoid serving stale data.
    """
    with open(path_str, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


def _load_census_json(path_str: str) -> dict[str, Any]:
    """Load census JSON with a process-lifetime cache keyed by path.

    Returns a deep copy so callers can't mutate the shared cache.
    """
    return copy.deepcopy(_load_census_json_cached(path_str))


@dataclass
class CensusDistribution:
    """Typed Census ACS distribution for one state or national."""

    state: str
    income_mu: float
    income_sigma: float
    fpl_buckets: list[dict[str, Any]]
    household_size_weights: list[float]
    pct_with_children: float
    pct_elderly_or_disabled: float
    pct_citizen: float
    pct_noncitizen_eligible: float
    labor_force_participation_rate: float
    pct_social_security: float
    pct_ssi: float
    pct_public_assistance: float
    snap_receipt_rate: float
    medicaid_coverage_rate: float
    median_gross_rent_monthly: float
    pct_renter: float
    age_mu: float
    age_sigma: float
    # Added with the corrected fetcher. Optional so census files written by the
    # earlier fetcher still load; None means "not present in this file".
    pct_households_with_earnings: float | None = None
    pct_households_60_plus: float | None = None
    pct_households_with_disability: float | None = None
    pct_noncitizen: float | None = None
    dollar_year: int | None = None
    # The vintage this distribution was loaded from, e.g. 'acs5-2024'.
    vintage: str | None = None


class CensusDataSource:
    """Load state-level ACS distributions for one vintage from local JSON.

    Args:
        state: Two-letter state code (case-insensitive) or 'national'.
        vintage: Which ACS release to read -- a CensusVintage, a year (5-year
            estimates ending that year), or a string such as 'acs1-2025'.
            None uses DEFAULT_CENSUS_VINTAGE.
        data_dir: Override the default data/census/ directory (for tests).
    """

    def __init__(
        self,
        state: str,
        vintage: CensusVintage | int | str | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.state = state.lower()
        self._explicit = vintage is not None
        self.vintage = CensusVintage.parse(vintage) if vintage is not None else DEFAULT_CENSUS_VINTAGE
        self._data_dir = data_dir if data_dir is not None else _CENSUS_DIR

    def load(self) -> CensusDistribution | None:
        """Deserialize the census JSON for this state and vintage.

        Returns:
            CensusDistribution, or None if the default vintage has no data
            file at all (callers fall back to built-in approximations).

        Raises:
            ValueError: If a vintage was explicitly requested and neither the
                state's nor the national file exists for it. An explicit year
                is a promise about which population the data reflects, so it
                is never silently replaced by built-in approximations.

        Side effects:
            Emits UserWarning when the state file is absent and falls back
            to that vintage's national.json.
        """
        directory = vintage_dir(self.vintage, self._data_dir)
        path = directory / f"{self.state}.json"
        if not path.exists():
            national = directory / "national.json"
            if self._explicit and not national.exists():
                available = ", ".join(v.label for v in available_vintages(self._data_dir)) or "none"
                raise ValueError(
                    f"No census data for '{self.state.upper()}' in vintage {self.vintage.label} "
                    f"(looked in {directory}). Available vintages: {available}. "
                    f"Fetch it with: {_fetch_command(self.state, self.vintage)}"
                )
            warnings.warn(
                f"No census data for '{self.state.upper()}' in {self.vintage.label}, "
                "falling back to national distribution",
                UserWarning,
                stacklevel=2,
            )
            path = national
            if not path.exists():
                return None

        data = _load_census_json(str(path))
        dist = _parse(data)
        dist.vintage = self.vintage.label
        return dist


def _parse(data: dict[str, Any]) -> CensusDistribution:
    """Deserialize a census JSON dict into a CensusDistribution."""
    inc = data["income"]
    hsg = data["housing"]
    hh = data["household_size"]
    dem = data["demographics"]
    isrc = data["income_sources"]
    pp = data["program_participation"]

    return CensusDistribution(
        state=data["_metadata"]["state"],
        income_mu=inc["monthly_lognormal"]["mu"],
        income_sigma=inc["monthly_lognormal"]["sigma"],
        fpl_buckets=inc["fpl_buckets"],
        household_size_weights=hh["weights"],
        pct_with_children=dem["pct_with_children"],
        pct_elderly_or_disabled=dem["pct_elderly_or_disabled"],
        pct_citizen=dem["pct_citizen"],
        pct_noncitizen_eligible=dem["pct_noncitizen_eligible"],
        labor_force_participation_rate=isrc["labor_force_participation_rate"],
        pct_social_security=isrc["pct_social_security"],
        pct_ssi=isrc["pct_ssi"],
        pct_public_assistance=isrc["pct_public_assistance"],
        snap_receipt_rate=pp["snap_receipt_rate"],
        medicaid_coverage_rate=pp["medicaid_coverage_rate"],
        median_gross_rent_monthly=hsg["median_gross_rent_monthly"],
        pct_renter=hsg["pct_renter"],
        age_mu=dem["age"]["mu"],
        age_sigma=dem["age"]["sigma"],
        pct_households_with_earnings=isrc.get("pct_households_with_earnings"),
        pct_households_60_plus=dem.get("pct_households_60_plus"),
        pct_households_with_disability=dem.get("pct_households_with_disability"),
        pct_noncitizen=dem.get("pct_noncitizen"),
        dollar_year=data["_metadata"].get("dollar_year"),
    )
