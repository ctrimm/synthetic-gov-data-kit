# ACA premium tax credit (2026)

Whether a household qualifies for the marketplace premium tax credit for 2026 coverage, and
how much (`data/thresholds/aca_ptc_ty2026.json`, presets `aca.va`, `aca.tx`, `aca.ca`, `aca.md`;
any state works with `ACAPremiumTaxCreditGenerator(state=...)`).

## Rules modeled, in order

1. **Filing status** — married taxpayers must file jointly, unless they live apart and cannot
   file jointly because of domestic abuse or abandonment, and certify it (26 CFR 1.36B-2(b)(2)).
2. **Household income 100–400% of the poverty line** — the 2025 guidelines, the ones in effect
   when 2026 open enrollment began (1.36B-1(h)). The ARPA/IRA enhanced credits, which removed the
   400% limit, expired after 2025, and no extension was enacted.
   - From 2026 there is no under-100% route for lawfully present noncitizens who are
     Medicaid-ineligible because of status (PL 119-21 §71302 removed 36B(c)(1)(B)).
3. **Not eligible for Medicaid** — using `MedicaidSource` (CY2026 limits, monthly income
   against the 2026 guidelines).
4. **No affordable employer coverage** — the employee's self-only contribution is affordable
   if it is at most **9.96%** of household income (Rev. Proc. 2025-25 §3.02).
5. **Not enrolled through an income-based special enrollment period** (PL 119-21 §71304, plan
   years after 2025).
6. **Credit** = the lesser of the enrolled plan premium and the benchmark (second-lowest-cost
   silver) premium minus household income × the applicable percentage / 12 (1.36B-3(d)). The
   applicable percentage rises linearly within each band of the Rev. Proc. 2025-25 table and is
   rounded to 0.01% (1.36B-3(g)); a $0 credit means no credit.

| Household income (% FPL) | Applicable percentage |
|---|---|
| under 133% | 2.10% |
| 133% – under 150% | 3.14% → 4.19% |
| 150% – under 200% | 4.19% → 6.60% |
| 200% – under 250% | 6.60% → 8.44% |
| 250% – under 300% | 8.44% → 9.96% |
| 300% – 400% | 9.96% |

Benchmark and enrolled premiums are synthetic and stated in each scenario.

## Sources

IRS Rev. Proc. 2025-25; 90 FR 27074 and CMS *APTC and CSR Basics* (expiry of the enhanced
credits); Public Law 119-21 §§71302, 71304, 71305 as implemented in IRS FS-2025-10, IR-2025-127
and the proposed regulations at 91 FR 65494; 26 CFR 1.36B-1 through 1.36B-3. Retrieved
2026-11-17 (issue #18).

## Not modeled

Reconciliation of advance payments (from 2026, excess advance credit is repaid in full, §71305),
the eligible-alien restriction (§71301, from 2027), pre-enrollment verification (§71303, from
2028), cost-sharing reductions, the family-coverage affordability test for related individuals,
HRA offers, and the Basic Health Program states.
