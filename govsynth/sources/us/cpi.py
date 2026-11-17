"""CPI-U inflation factors for restating Census incomes in a program year's dollars.

ACS incomes are in the vintage's own dollars (``_metadata.dollar_year`` in each census
file). When a profile is judged by a program year's rules, its income should be in
that year's dollars. Data: data/thresholds/cpi_u_annual.json (BLS CPI-U, U.S. city
average, via FRED; built by scripts/import_cpi.py).
"""

from __future__ import annotations

from typing import Any

from govsynth.sources.base import THRESHOLD_DIR, _load_json_file


def _annual() -> dict[str, Any]:
    data: dict[str, Any] = _load_json_file(str(THRESHOLD_DIR / "cpi_u_annual.json"))["annual"]
    return data


def cpi_annual_average(year: int) -> float:
    """CPI-U annual average for a year (partial-year years average their published months).

    Raises:
        ValueError: If the year is not in the bundled table.
    """
    annual = _annual()
    if str(year) not in annual:
        raise ValueError(f"No CPI-U annual average for {year}; bundled years: {sorted(annual)}")
    return float(annual[str(year)]["average"])


def inflation_factor(from_year: int, to_year: int) -> float:
    """Multiplier that restates `from_year` dollars in `to_year` dollars (1.0 when the years match)."""
    if from_year == to_year:
        return 1.0
    return cpi_annual_average(to_year) / cpi_annual_average(from_year)
