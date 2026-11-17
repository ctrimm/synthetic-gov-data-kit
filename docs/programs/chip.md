# CHIP and children's Medicaid

Which coverage a child (0–18) qualifies for, CY2026 (`data/thresholds/chip_cy2026.json`,
presets `chip.va`, `chip.ca`, `chip.tx`, `chip.md`; any of the 50 states or DC works with
`CHIPEligibilityGenerator(state=...)`).

## Rules modeled

1. Household MAGI as a percent of the 2026 poverty guidelines.
2. At or below the Medicaid limit for the child's age group (0–1, 1–5, 6–18) → **Medicaid**,
   insured or not.
3. Above it, only **uninsured** children qualify (42 CFR 457.310(b)(2)):
   - within the CHIP-funded Medicaid range → **Medicaid (CHIP-funded)**;
   - at or below the separate CHIP limit → **separate CHIP**.
4. Otherwise ineligible.

Limits are compared in monthly dollars rounded to the cent, so an income a few cents over a
limit is never rounded into it.

| State | Medicaid (0–1 / 1–5 / 6–18) | Above Medicaid | Upper limit |
|---|---|---|---|
| VA | 148% / 148% / 148% | separate CHIP | 205% |
| CA | 208% / 142% / 133% | CHIP-funded Medicaid | 266% |
| TX | 203% / 149% / 138% | separate CHIP | 206% |
| MD | 194% / 138% / 133% | CHIP-funded Medicaid | 322% |

## Source

KFF, *Medicaid and CHIP Income Eligibility Limits for Children as a Percent of the Federal
Poverty Level*, as of January 2026 (survey with the Georgetown University Center for Children and
Families). A secondary compilation: the CMS Medicaid.gov eligibility-levels table, retrieved for
#24, is dated December 1, 2023, so it is a stale cross-check rather than a 2026 source. All 51 rows are
internally consistent (upper limit = the row's maximum; CHIP-funded ranges start at or below the
Medicaid limit).

## Not modeled

Waiting periods, state-employee exclusions, premiums, immigrant-children options, county-level
variation (some California counties have higher separate-CHIP limits), and pregnant-women coverage.
