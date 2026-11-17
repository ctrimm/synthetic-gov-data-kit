# TANF (cash assistance)

Whether a first-time applicant household is eligible for TANF cash assistance in Virginia,
Maryland, Texas or California, 2026 (`data/thresholds/tanf_{va,md,tx,ca}_2026.json`, presets
`tanf.va`, `tanf.md`, `tanf.tx`, `tanf.ca`). Each state runs its own program, so each has its
own tests, in its own order; the rationale trace is exactly that list.

## Rules modeled

| State | Tests, in order | Key amounts (unit of 3) |
|---|---|---|
| **VA** (22VAC40-295-50; VDSS Manual Ch. 300) | Locality group (II or III, by county/city) → gross income ≤ Maximum Income Chart → earnings − SNAP standard deduction − 20% of the remainder + unearned income **less than** the standard of assistance | Group II / III: max income $966 / $1,175; standard $482 / $587 |
| **MD** (COMAR 07.03.03.11, .13E; IM 26-13) | 80% of earnings + unearned ≤ allowable payment → allowable − net (rounded down) ≥ $10 | allowable payment $773 (from Jan 1, 2026) |
| **TX** (TWH A-1341, A-1425, C-111 Rev. 26-4) | Resources ≤ $1,000 → Budgetary Needs ($120 work expense; unmet need ≥ $0.50) → Recognizable Needs Part A ($120, then 1/3 of the rest; ≥ $0.01) → Part B ($120, then 90% up to $1,400) | Budgetary $751, Recognizable $188 (one-parent, from Oct 1, 2026) |
| **CA** (CalWORKs; ACL 26-39, 26-66) | Region (1 or 2, by county) → income − $450 per employed adult **below** the MBSAC → MAP − ((earnings − $600) / 2 + unearned) > $0 | Region 1: MBSAC $1,960 (Jul 1, 2026); MAP $1,196 non-exempt (Oct 1, 2026) |

Households are first-time applicants (no TANF in the past four months): a caretaker relative
and children, earnings from one adult's wages and/or Social Security (counted in full
everywhere). For Texas, households have earnings or Social Security but not both, because the
handbook's "1/3 of the remaining income" could be read as applying to unearned income too;
with one income type the readings agree. In Texas, Part A is stricter than Part B for every
applicant, so Part B never decides a case.

**Virginia's disregard.** 22VAC40-295-50.C disregards "an amount equal to the Food Stamp
standard deduction". The VDSS manual's examples show $198/$208/$244/$279, the FY2024 SNAP
amounts; this uses the current FY2026 SNAP standard deduction ($209 for units of 1-3), per the
regulation.

## Sources

Retrieved 2026-11-17 and posted to issue #17: VDSS TANF Manual Chapter 300 (standards of
assistance 7/22, Maximum Income Chart, locality groups 7/20, maximum reimbursable payment);
22VAC40-295-50; COMAR 07.03.03 and Maryland DHS IM 26-13; Texas Works Handbook A-1341, A-1420/
A-1425 and C-111 (Rev. 26-4); CDSS ACL 26-39 (MBSAC) and ACL 26-66 (MAP, AB 152).
`scripts/build_tanf_tables.py` holds the transcription and checks it against relations the
sources state (VA maximum income is about 200% of the standard; TX Recognizable Needs is 25% of
Budgetary Needs; MD's 20% disregard reproduces NCCP's $941.25 family-of-three limit).

## Not modeled

Benefit amounts beyond what eligibility needs (Virginia's $723/$861 payment cap, Texas's maximum
grant), recipients (ongoing disregards), dependent-care and child-support disregards,
self-employment, two-earner households, child-only cases, time limits, work requirements and
sanctions, California's property limit and exempt MAP (sources disagree on the current property
limit), and California's minimum grant (cases stay at least 3% from a California boundary).
