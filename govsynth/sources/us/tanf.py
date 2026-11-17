"""TANF cash assistance eligibility for applicants in VA, MD, TX and CA (2026).

Each state runs its own program with its own tests, so `TANFSource.evaluate` returns the
ordered list of facts and checks the state applies, and the generator renders exactly that
list as the rationale trace. Data: data/thresholds/tanf_{state}_2026.json
(scripts/build_tanf_tables.py, from the state primary sources posted to issue #17).

Modeled households are **applicants** (no TANF in the past four months) with a caretaker
relative and children; earnings come from one employed adult's wages, and unearned income
is Social Security (counted in full in every state). Not modeled: dependent-care and
child-support disregards, time limits, work requirements, sanctions, child-only cases,
self-employment, and California's property limit (sources disagree on the current amount).

State rules:
  VA (22VAC40-295-50; VDSS Manual Ch. 300): gross income at or below the Maximum Income
     Chart for the locality group; then earnings minus an amount equal to the SNAP standard
     deduction and 20% of the remainder, plus unearned income, must be less than the
     standard of assistance.
  MD (COMAR 07.03.03.11, .13E): 80% of earnings (20% disregard at application) plus
     unearned income must not exceed the allowable payment; a benefit of at least $10 must
     result (allowable payment minus net income rounded down to the dollar).
  TX (Texas Works Handbook A-1341, A-1425): countable resources at most $1,000; Budgetary
     Needs test ($120 work expense; unmet need at least $0.50); Recognizable Needs Part A
     (applicants: $120 then 1/3 of the remainder; unmet need at least $0.01); Part B ($120
     then 90% of remaining earnings, capped at $1,400).
  CA (CalWORKs; ACL 26-39, 26-66): applicant test -- income minus $450 per employed adult
     below the MBSAC for the region; then a grant must remain: MAP minus (earnings above
     $600, halved, plus unearned income).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from govsynth.sources.base import THRESHOLD_DIR, DataSource, HouseholdThreshold, ProgramThresholds, _load_json_file

TANF_STATES = ("VA", "MD", "TX", "CA")


def _usd(x: float) -> str:
    """Dollars with the sign in front: -$306.53, not $-306.53."""
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


@dataclass(frozen=True)
class TANFHousehold:
    """An applicant assistance unit."""

    size: int
    earned: float = 0.0  # monthly gross wages of the one employed adult
    unearned: float = 0.0  # monthly Social Security
    locality: str | None = None  # VA: county or city name, e.g. "Fairfax County"
    county: str | None = None  # CA county
    two_parent: bool = False  # TX case type
    countable_resources: float = 0.0  # TX


@dataclass(frozen=True)
class TANFCheck:
    """One fact or test, in the order the state applies them. `passed` is None for a fact."""

    title: str
    rule: str
    computation: str
    result: str
    passed: bool | None = None
    inputs: dict[str, Any] = field(default_factory=dict)


class TANFSource(DataSource):
    """TANF rules for one of VA, MD, TX, CA.

    Args:
        state: Two-letter state code.
        year: Rule year. Only 2026 is bundled.
    """

    def __init__(self, state: str = "VA", year: int = 2026) -> None:
        super().__init__(year=year, state=state)
        if self.state not in TANF_STATES:
            raise ValueError(f"TANF rules are bundled for {TANF_STATES}, not {self.state}")
        self.raw: dict[str, Any] = _load_json_file(str(THRESHOLD_DIR / f"tanf_{self.state.lower()}_{year}.json"))

    @property
    def program(self) -> str:
        return "tanf"

    @property
    def sizes(self) -> tuple[int, ...]:
        """Assistance-unit sizes modeled (a caretaker plus at least one child; TX two-parent from 3)."""
        return (2, 3, 4, 5, 6)

    # -- locality helpers ------------------------------------------------

    def va_group(self, locality: str) -> str:
        """'group_ii' or 'group_iii' for a Virginia locality like 'Fairfax County' or 'Norfolk city'.

        Raises:
            ValueError: If the locality is not in the VDSS list.
        """
        groups = self.raw["locality_groups"]
        name, _, kind = locality.rpartition(" ")
        kind = kind.lower()
        for g in ("group_ii", "group_iii"):
            if name in groups[f"{g}_{'counties' if kind == 'county' else 'cities'}"]:
                return g
        raise ValueError(f"Unknown Virginia locality {locality!r}")

    def ca_region(self, county: str) -> str:
        """'region_1' or 'region_2' for a California county."""
        return "region_1" if county in self.raw["region_1_counties"] else "region_2"

    # -- evaluation -------------------------------------------------------

    def all_checks(self, hh: TANFHousehold) -> list[TANFCheck]:
        """Every fact and test, without stopping at the first failure (for locating boundaries)."""
        return {"VA": self._va, "MD": self._md, "TX": self._tx, "CA": self._ca}[self.state](hh)

    def evaluate(self, hh: TANFHousehold) -> list[TANFCheck]:
        """Facts and tests in order, stopping after the first failed test."""
        checks = self.all_checks(hh)
        out: list[TANFCheck] = []
        for c in checks:
            out.append(c)
            if c.passed is False:
                break
        return out

    def is_eligible(self, hh: TANFHousehold) -> bool:
        """Whether every test passes."""
        return all(c.passed is not False for c in self.evaluate(hh))

    def _va(self, hh: TANFHousehold) -> list[TANFCheck]:
        if hh.locality is None:
            raise ValueError("Virginia cases need a locality")
        g = self.va_group(hh.locality)
        label = "Group II" if g == "group_ii" else "Group III"
        n = str(hh.size)
        gross = round(hh.earned + hh.unearned, 2)
        max_income = self.raw["maximum_income"][g][n]
        soa = self.raw["standard_of_assistance"][g][n]
        snap = _load_json_file(str(THRESHOLD_DIR / "snap_fy2026.json"))["standard_deductions_48_states_dc"]
        std = float(snap[str(min(hh.size, 6)) if hh.size < 6 else "6+"])
        first = min(std, hh.earned)
        remainder = hh.earned - first
        pct = self.raw["earned_disregard"]["pct_of_remainder"]
        countable_earned = round(remainder * (1 - pct / 100), 2)
        net = round(countable_earned + hh.unearned, 2)
        return [
            TANFCheck(
                "Identify the locality group",
                "VDSS TANF Manual 304, Appendix 1",
                f"{hh.locality} is a {label} locality.",
                label,
            ),
            TANFCheck(
                "Gross income screening against the Maximum Income Chart",
                "VDSS TANF Manual 305.1; Appendix 1 to 305",
                f"Gross income ${hh.earned:,.2f} earned + ${hh.unearned:,.2f} unearned = ${gross:,.2f} "
                f"{'<=' if gross <= max_income else '>'} ${max_income:,} ({label}, unit of {hh.size})",
                "PASS" if gross <= max_income else "FAIL - over the maximum income",
                gross <= max_income,
                {"gross_income": gross, "maximum_income": max_income},
            ),
            TANFCheck(
                "Apply the earned income disregards",
                "22VAC40-295-50.C",
                (
                    f"Earnings ${hh.earned:,.2f} − ${first:,.2f} (equal to the FY2026 SNAP standard deduction for "
                    f"{hh.size}) = ${remainder:,.2f}; − {pct}% = ${countable_earned:,.2f}; + unearned "
                    f"${hh.unearned:,.2f} = ${net:,.2f} net countable income"
                    if hh.earned > 0
                    else f"No earnings, so no earned income disregard; unearned income ${hh.unearned:,.2f} counts in "
                    f"full: ${net:,.2f} net countable income"
                ),
                f"Net countable income ${net:,.2f}",
                inputs={"net_income": net},
            ),
            TANFCheck(
                "Compare net income to the standard of assistance",
                "22VAC40-295-50.A",
                f"${net:,.2f} {'<' if net < soa else '>='} ${soa:,} ({label} standard of assistance, unit of "
                f"{hh.size}); eligible only if less",
                "PASS" if net < soa else "FAIL - net income not below the standard of assistance",
                net < soa,
                {"net_income": net, "standard_of_assistance": soa},
            ),
        ]

    def _md(self, hh: TANFHousehold) -> list[TANFCheck]:
        allowable = self.raw["allowable_payment"]["by_size"][str(hh.size)]
        pct = self.raw["earned_disregard_pct_application"]
        disregard = round(hh.earned * pct / 100, 2)
        net = round(hh.earned - disregard + hh.unearned, 2)
        benefit = allowable - math.floor(net)
        minimum = self.raw["minimum_benefit"]
        checks = [
            TANFCheck(
                "Apply the application earned income disregard",
                "COMAR 07.03.03.13E(3)(a)",
                f"Earnings ${hh.earned:,.2f} − {pct}% (${disregard:,.2f}) + unearned ${hh.unearned:,.2f} = "
                f"${net:,.2f} net countable income",
                f"Net countable income ${net:,.2f}",
                inputs={"net_income": net},
            ),
            TANFCheck(
                "Compare net income to the allowable payment",
                "COMAR 07.03.03.11A; IM 26-13 FIP schedule",
                f"${net:,.2f} {'<=' if net <= allowable else '>'} ${allowable:,} (allowable payment, unit of "
                f"{hh.size}, effective January 1, 2026)",
                "PASS" if net <= allowable else "FAIL - net income exceeds the allowable payment",
                net <= allowable,
                {"net_income": net, "allowable_payment": allowable},
            ),
        ]
        checks.append(
            TANFCheck(
                "Compute the benefit and apply the $10 minimum",
                "COMAR 07.03.03.13E(1)-(2)",
                f"${allowable:,} − ${math.floor(net):,} (net income rounded down) = ${benefit:,}; a benefit is issued "
                f"only if at least ${minimum}",
                f"PASS - benefit ${benefit:,}"
                if benefit >= minimum
                else f"FAIL - benefit ${benefit:,} is under ${minimum}",
                benefit >= minimum,
                {"benefit": benefit, "minimum_benefit": minimum},
            )
        )
        return checks

    def _tx(self, hh: TANFHousehold) -> list[TANFCheck]:
        case = "two_parent" if hh.two_parent else "one_parent"
        table = self.raw["budgetary_allowances"][case]
        n = str(hh.size)
        bn, rn = table["budgetary_needs"][n], table["recognizable_needs"][n]
        limit = self.raw["asset_limit"]
        wre = min(float(self.raw["work_related_expense"]), hh.earned)
        rem = round(hh.earned - wre, 2)
        net_bn = round(rem + hh.unearned, 2)
        unmet_bn = round(bn - net_bn, 2)
        adj_a = round(rem * 2 / 3 + hh.unearned, 2) if hh.earned > 0 else round(hh.unearned, 2)
        unmet_a = round(rn - adj_a, 2)
        eid = round(
            min(rem * self.raw["earned_income_deduction_pct"] / 100, self.raw["earned_income_deduction_cap"]), 2
        )
        adj_b = round(rem - eid + hh.unearned, 2)
        unmet_b = round(rn - adj_b, 2)
        kind = "two-parent" if hh.two_parent else "one-parent (no second parent)"
        min_bn, min_rn = self.raw["budgetary_needs_min_unmet"], self.raw["recognizable_needs_min_unmet"]
        return [
            TANFCheck(
                "Identify the case type and standards",
                "Texas Works Handbook C-111 (Rev. 26-4, effective October 1, 2026)",
                f"{kind.capitalize()} caretaker case, size {hh.size}: Budgetary Needs ${bn:,}, Recognizable Needs "
                f"${rn:,}. The household has not received TANF in the past four months, so the applicant tests apply.",
                f"Budgetary Needs ${bn:,}; Recognizable Needs ${rn:,}",
            ),
            TANFCheck(
                "Check countable resources",
                "Texas Works Handbook A-1200; A-1238",
                f"Countable resources ${hh.countable_resources:,.2f} "
                f"{'<=' if hh.countable_resources <= limit else '>'} ${limit:,}",
                "PASS" if hh.countable_resources <= limit else "FAIL - over the resource limit",
                hh.countable_resources <= limit,
                {"countable_resources": hh.countable_resources, "resource_limit": limit},
            ),
            TANFCheck(
                "Budgetary Needs test (applicants)",
                "Texas Works Handbook A-1341; A-1425.1; C-111",
                f"Earnings ${hh.earned:,.2f} − ${wre:,.2f} work-related expense + unearned ${hh.unearned:,.2f} = "
                f"${net_bn:,.2f}; Budgetary Needs ${bn:,} ({kind}, size {hh.size}) − ${net_bn:,.2f} = unmet need "
                f"{_usd(unmet_bn)} (must be at least ${min_bn:.2f})",
                "PASS" if unmet_bn >= min_bn else "FAIL - no unmet budgetary need",
                unmet_bn >= min_bn,
                {"net_income": net_bn, "budgetary_needs": bn},
            ),
            TANFCheck(
                "Recognizable Needs test, Part A (applicants: $120 and 1/3 disregard)",
                "Texas Works Handbook A-1341; A-1425.2; C-111",
                (
                    f"(${hh.earned:,.2f} − ${wre:,.2f}) × 2/3 + unearned ${hh.unearned:,.2f} = ${adj_a:,.2f}"
                    if hh.earned > 0
                    else f"No earnings, so no disregard: ${adj_a:,.2f}"
                )
                + f"; Recognizable Needs ${rn:,} − ${adj_a:,.2f} = unmet need {_usd(unmet_a)} (must be at least "
                f"${min_rn:.2f})",
                "PASS" if unmet_a >= min_rn else "FAIL - no unmet recognizable need (Part A)",
                unmet_a >= min_rn,
                {"adjusted_income": adj_a, "recognizable_needs": rn},
            ),
            TANFCheck(
                "Recognizable Needs test, Part B ($120 and 90% earned income deduction)",
                "Texas Works Handbook A-1341; A-1425.3",
                f"${rem:,.2f} − 90% (${eid:,.2f}, cap $1,400) + unearned ${hh.unearned:,.2f} = ${adj_b:,.2f}; "
                f"Recognizable Needs ${rn:,} − ${adj_b:,.2f} = unmet need {_usd(unmet_b)}",
                "PASS" if unmet_b >= min_rn else "FAIL - no unmet recognizable need (Part B)",
                unmet_b >= min_rn,
                {"adjusted_income": adj_b, "recognizable_needs": rn},
            ),
        ]

    def _ca(self, hh: TANFHousehold) -> list[TANFCheck]:
        if hh.county is None:
            raise ValueError("California cases need a county")
        region = self.ca_region(hh.county)
        label = "Region 1" if region == "region_1" else "Region 2"
        n = str(hh.size)
        mbsac = self.raw["mbsac"][region][n]
        map_ = self.raw["map_non_exempt"][region][n]
        ded = min(float(self.raw["applicant_earned_deduction_per_employed_adult"]), hh.earned)
        applicant_income = round(hh.earned - ded + hh.unearned, 2)
        first = self.raw["benefit_earned_disregard_first"]
        countable = round(
            max(0.0, hh.earned - first) * (1 - self.raw["benefit_earned_disregard_pct_of_remainder"] / 100)
            + hh.unearned,
            2,
        )
        grant = round(map_ - countable, 2)
        return [
            TANFCheck("Identify the region", "ACL 26-66", f"{hh.county} County is in {label}.", label),
            TANFCheck(
                "Applicant income test against the MBSAC",
                "Welfare and Institutions Code 11450.12; ACL 26-39",
                f"Earnings ${hh.earned:,.2f} − ${ded:,.2f} (employed adult) + unearned ${hh.unearned:,.2f} = "
                f"${applicant_income:,.2f} {'<' if applicant_income < mbsac else '>='} ${mbsac:,} ({label} MBSAC, "
                f"unit of {hh.size}, effective July 1, 2026)",
                "PASS" if applicant_income < mbsac else "FAIL - income not below the MBSAC",
                applicant_income < mbsac,
                {"applicant_income": applicant_income, "mbsac": mbsac},
            ),
            TANFCheck(
                "Compute the grant against the MAP",
                "Welfare and Institutions Code 11451.5, 11450; ACL 26-66",
                f"Countable income: (${hh.earned:,.2f} − ${first}) × 50% + unearned ${hh.unearned:,.2f} = "
                f"${countable:,.2f}; MAP ${map_:,} ({label}, non-exempt, unit of {hh.size}, effective October 1, "
                f"2026) − ${countable:,.2f} = {_usd(grant)}",
                f"PASS - grant ${grant:,.2f}" if grant > 0 else "FAIL - no grant remains",
                grant > 0,
                {"countable_income": countable, "map": map_, "grant": grant},
            ),
        ]

    # -- DataSource -----------------------------------------------------

    def fetch_thresholds(self) -> ProgramThresholds:
        """The state's main income standard by unit size (VA Group III SOA, MD allowable, TX budgetary, CA MBSAC R1)."""
        r = self.raw
        table = {
            "VA": r.get("standard_of_assistance", {}).get("group_iii"),
            "MD": r.get("allowable_payment", {}).get("by_size"),
            "TX": r.get("budgetary_allowances", {}).get("one_parent", {}).get("budgetary_needs"),
            "CA": r.get("mbsac", {}).get("region_1"),
        }[self.state]
        households = {
            int(k): HouseholdThreshold(household_size=int(k), gross_monthly=float(v), net_monthly=float(v))
            for k, v in table.items()
        }
        return ProgramThresholds(
            program="tanf",
            fiscal_year=self.year,
            state=self.state,
            source=r["_metadata"]["source"],
            source_url=r["_metadata"]["source_url"],
            households=households,
            extra={"rules_reference": r["_metadata"]["rules_reference"]},
        )

    def fetch_policy_summary(self) -> str:
        m = self.raw["_metadata"]
        return f"TANF ({self.state}, 2026): {m['rules_reference']}. Source: {m['source']}"
