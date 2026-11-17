"""LIHEAP (Low Income Home Energy Assistance Program) data source connector.

Data sourced from data/thresholds/liheap_fy{year}.json: HHS's state median income
table (LIHEAP IM2025-02, mandatory for FY2026) and each modeled state's FY2026
LIHEAP plan, plus the HHS poverty guidelines the federal tables are built on.

Federal frame (42 U.S.C. 8624(b)(2)): a state's income ceiling may not exceed the
greater of 150% FPL or 60% of state median income, nor be set below 110% FPL, and
states may make SNAP/TANF/SSI/means-tested veterans' benefit recipients
categorically income-eligible. Within that frame each state picks its own method,
so this source only answers for states whose plan is in the data file.

Income eligibility only: LIHEAP is not an entitlement, and benefit amounts are
not modeled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from govsynth.fiscal_year import FiscalYearConfig
from govsynth.sources.base import THRESHOLD_DIR, DataSource, HouseholdThreshold, ProgramThresholds, _load_json_file

DEFAULT_LIHEAP_FY = 2026


@dataclass(frozen=True)
class LIHEAPThreshold:
    """A state's annual income limit for one component and household size, with how it was derived."""

    component: str
    household_size: int
    annual_limit: float
    basis: str  # 'fpl', 'smi', or 'smi_by_size'
    pct: float
    explanation: str


class LIHEAPSource(DataSource):
    """LIHEAP income eligibility for one state and federal fiscal year.

    Args:
        fiscal_year: Federal fiscal year. Default FY2026.
        state: Two-letter code of a state whose plan is in the data file (VA, CA, TX, MD).

    Raises:
        ValueError: If the state's plan is not in the data file.
    """

    def __init__(self, fiscal_year: int = DEFAULT_LIHEAP_FY, state: str = "VA") -> None:
        super().__init__(year=fiscal_year, state=state)
        self.fy_config = FiscalYearConfig.for_program("liheap", fiscal_year)
        self._raw = self._load_threshold_json(self.fy_config.threshold_filename)
        if self.state not in self._raw["states"]:
            raise ValueError(
                f"No FY{fiscal_year} LIHEAP plan data for {self.state}; modeled states: {sorted(self._raw['states'])}"
            )
        self._plan: dict[str, Any] = self._raw["states"][self.state]
        self._smi: dict[str, Any] = self._raw["state_median_income"][self.state]
        fpl = _load_json_file(str(THRESHOLD_DIR / f"us_fpl_{self._raw['_metadata']['fpl_basis_year']}.json"))
        region = {"AK": "alaska", "HI": "hawaii"}.get(self.state, "contiguous_48_dc")
        self._fpl: dict[str, Any] = fpl["regions"][region]

    @property
    def program(self) -> str:
        return "liheap"

    @property
    def raw(self) -> dict[str, Any]:
        """The parsed liheap_fy{year}.json."""
        return self._raw

    @property
    def components(self) -> list[str]:
        """Components this state's plan designates an income threshold for."""
        return list(self._plan["components"])

    @property
    def categorical_programs(self) -> list[str]:
        """Benefits that make a household categorically income-eligible in this state (may be empty)."""
        return list(self._plan["categorical_programs"])

    # ------------------------------------------------------------------
    # Federal building blocks
    # ------------------------------------------------------------------

    def annual_fpl(self, household_size: int) -> float:
        """Annual poverty guideline for the household size."""
        by_size = self._fpl["by_household_size"]
        if household_size <= 8:
            return float(by_size[str(household_size)]["annual"])
        return float(by_size["8"]["annual"]) + (household_size - 8) * float(self._fpl["per_additional_person_annual"])

    def sixty_pct_smi(self, household_size: int) -> float:
        """60% of state median income for the household size (HHS table; 45 CFR 96.85 above size 12)."""
        table = self._smi["sixty_pct_smi"]
        if str(household_size) in table:
            return float(table[str(household_size)])
        fed = self._raw["federal"]
        factor = fed["smi_size_factors_pct"]["12"] + (household_size - 12) * fed["smi_size_factor_increment_above_12"]
        return float(round(self._smi["smi_4_person"] * 0.6 * factor / 100))

    def federal_ceiling(self, household_size: int) -> float:
        """Greater of 150% FPL or 60% SMI: the highest limit any state may set."""
        return max(self.annual_fpl(household_size) * 1.5, self.sixty_pct_smi(household_size))

    # ------------------------------------------------------------------
    # State thresholds and determinations
    # ------------------------------------------------------------------

    def threshold(self, component: str, household_size: int) -> LIHEAPThreshold:
        """The state's annual income limit for a component and household size."""
        if component not in self._plan["components"]:
            raise ValueError(f"{self.state} designates no LIHEAP income threshold for '{component}'")
        spec = self._plan["components"][component]
        basis = spec["basis"]
        if basis == "fpl":
            pct = float(spec["pct"])
            fpl = self.annual_fpl(household_size)
            limit = fpl * pct / 100
            how = f"{pct:g}% x ${fpl:,.0f} (2025 HHS poverty guideline, household of {household_size})"
        elif basis == "smi":
            pct = float(spec["pct"])
            limit = self.sixty_pct_smi(household_size) * pct / 60
            how = f"{pct:g}% of state median income for a household of {household_size} (HHS IM2025-02 table)"
        elif basis == "smi_by_size":
            ramp = spec["pct_by_size"]
            pct = float(ramp[str(min(household_size, max(int(k) for k in ramp)))])
            smi_for_size = self.sixty_pct_smi(household_size) / 0.6
            limit = smi_for_size * pct / 100
            how = (
                f"{pct:g}% (the {self.state} rate for a household of {household_size}) x "
                f"${smi_for_size:,.0f} state median income for that household size"
            )
        else:  # pragma: no cover - guarded by data tests
            raise ValueError(f"unknown LIHEAP threshold basis {basis!r}")
        return LIHEAPThreshold(component, household_size, round(limit, 2), basis, pct, how)

    def determine(
        self,
        component: str,
        household_size: int,
        annual_gross_income: float,
        receives: tuple[str, ...] = (),
    ) -> tuple[bool, str]:
        """Return (income-eligible, reason) for a household and component."""
        conferring = [p for p in receives if p in self.categorical_programs]
        if conferring:
            return True, (
                f"Eligible: receives {conferring[0]}, which makes the household categorically income-eligible "
                f"for {self.state} LIHEAP"
            )
        t = self.threshold(component, household_size)
        if annual_gross_income <= t.annual_limit:
            return True, (
                f"Eligible: annual gross income ${annual_gross_income:,.2f} <= ${t.annual_limit:,.2f} "
                f"({self.state} {component} limit)"
            )
        return False, (
            f"Ineligible: annual gross income ${annual_gross_income:,.2f} exceeds ${t.annual_limit:,.2f} "
            f"({self.state} {component} limit)"
        )

    # ------------------------------------------------------------------
    # DataSource interface
    # ------------------------------------------------------------------

    def fetch_thresholds(self) -> ProgramThresholds:
        """Monthly income limits for the state's first component, by household size 1-8."""
        component = self.components[0]
        households = {}
        for size in range(1, 9):
            monthly = math.floor(self.threshold(component, size).annual_limit / 12 * 100) / 100
            households[size] = HouseholdThreshold(household_size=size, gross_monthly=monthly, net_monthly=monthly)
        return ProgramThresholds(
            program="liheap",
            fiscal_year=self.year,
            state=self.state,
            source=self._raw["_metadata"]["source"],
            source_url=self._plan["plan_url"],
            households=households,
            extra={
                "component": component,
                "components": self.components,
                "categorical_programs": self.categorical_programs,
                "verification_status": self._raw["_metadata"]["verification_status"],
            },
        )

    def fetch_policy_summary(self) -> str:
        """Plain-text summary of the state's LIHEAP income rules."""
        lines = [f"LIHEAP ({self.fy_config.period_label}, {self.state} — {self._plan['agency']}):"]
        for c in self.components:
            t = self.threshold(c, 3)
            lines.append(f"- {c}: household of 3 limit ${t.annual_limit:,.0f}/year ({t.explanation}).")
        if self.categorical_programs:
            lines.append(f"- Categorically income-eligible: recipients of {', '.join(self.categorical_programs)}.")
        lines.append("- Federal ceiling: greater of 150% FPL or 60% SMI; floor 110% FPL (42 U.S.C. 8624(b)(2)).")
        return "\n".join(lines)
