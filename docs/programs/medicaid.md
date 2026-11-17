# Medicaid (MAGI)

Whether an applicant qualifies for MAGI-based Medicaid, CY2026
(`data/thresholds/medicaid_cy2026.json`, presets `medicaid.va`, `medicaid.tx`; any of the 50
states or DC works with `MedicaidEligibilityGenerator(state=...)`).

## Rules modeled

1. Household MAGI as a percent of the 2026 HHS poverty guideline **for the MAGI household size**
   (42 CFR 435.603). A pregnant woman's household counts the expected child (435.603(b)). Alaska
   and Hawaii use their own guidelines.
2. The applicant's coverage group and its state limit:

   | Applicant | Group | Limit |
   |---|---|---|
   | Adult, no dependent children (19–64) | 42 CFR 435.119 (ACA expansion) | 138% in expansion states; 100% in GA (Georgia Pathways) and WI (§1115); none elsewhere |
   | Parent / caretaker relative | 42 CFR 435.110 | state limit (138% in expansion states; 15–105% elsewhere) |
   | Pregnant woman | 42 CFR 435.116 | state Medicaid limit (138–324%) |
   | Child 0–18 (no other coverage) | 42 CFR 435.118 | by age group 0–1 / 1–5 / 6–18, including CHIP-funded Medicaid |

3. MAGI at or below the limit, compared in monthly dollars to the cent, is eligible.

An adult without dependent children in a state with no coverage for them is ineligible at any
income. Below 100% FPL that is the **coverage gap** (also too poor for marketplace premium tax
credits); at or above 100% the trace notes the marketplace instead.

Limits are KFF's published MAGI-converted standards, which already include the 5-point
disregard, so MAGI is compared to them directly.

## Source

KFF State Health Facts (survey with the Georgetown University Center for Children and Families),
retrieved 2026-11-17 (issue #24): *Medicaid Income Eligibility Limits for Adults* and *for Pregnant
Women* (as of January 2026), *Status of State Action on the Medicaid Expansion Decision* (as of
November 2026: 41 adopted including DC, 10 not), and the children's table already verified in
`chip_cy2026.json`. `scripts/build_medicaid_limits.py` holds the transcription and checks it
against KFF's stated counts. Medicaid.gov's eligibility-levels page (as of December 1, 2023) is a
stale cross-check only; it agrees on expansion status.

## Not modeled

Non-MAGI groups (aged, blind, disabled; medically needy), immigrant eligibility rules, work
requirements (PL 119-21 §71119, from January 1, 2027), CHIP and FCEP pregnancy coverage (noted in
the trace when it would apply), and postpartum extensions.
