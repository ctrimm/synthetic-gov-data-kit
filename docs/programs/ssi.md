# SSI — Supplemental Security Income

Federal SSI eligibility and payment, CY2026 (`data/thresholds/ssi_cy2026.json`, preset
`ssi.national`).

## Determination order (each case's rationale follows it)

1. Aged (65+), blind, or disabled — 20 CFR 416.202
2. Non-blind disabled applicants with earnings: earnings above SGA ($1,690/month in 2026) mean
   the applicant is not disabled — 20 CFR 416.920(b)
3. Resources ≤ $2,000 individual / $3,000 couple — 20 CFR 416.1205
4. Countable income: $20 general exclusion (unearned first), then $65 + one-half of remaining
   earnings — 20 CFR 416.1124(c)(12), 416.1112
5. Payment = federal benefit rate − countable income; none if countable income ≥ FBR.
   FBR 2026: $994 individual / $1,491 couple (90 FR 49047).

## Case types (edge-saturated)

`countable_income_vs_fbr` (incomes back-solved to land on and around the FBR, including exactly
at it), `resource_limit`, `substantial_gainful_activity` (a disabled applicant earning just over
or under SGA — over it is ineligible even though the income test alone would pay), and
`not_aged_blind_disabled`.

## Not modeled

State supplementary payments, in-kind support and maintenance, deeming from a spouse or
parent, the student earned income exclusion, and impairment-related work expenses.
