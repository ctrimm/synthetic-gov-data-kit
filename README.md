# synthetic-gov-data-kit

> Generate structured synthetic US government benefits data for LLM reasoning evaluation.



[![CI](https://github.com/ctrimm/synthetic-gov-data-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/ctrimm/synthetic-gov-data-kit/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)


---

## What It Does

`synthetic-gov-data-kit` generates realistic, policy-grounded test cases for evaluating how well
LLMs reason about US government benefits programs. Every case includes:

- A **synthetic citizen scenario** (household, income, assets, circumstances)
- A **task instruction** (determine eligibility, answer a policy question, etc.)
- The **expected answer** and outcome
- A **step-by-step rationale trace** — the correct reasoning chain, citing actual CFR sections

This last piece is the key differentiator. You can evaluate not just *what* a model answers,
but *whether it reasons correctly* — did it apply the right rules, in the right order, with
the right computations?

## Use Cases

| Who | What they use it for |
|-----|----------------------|
| **AI researchers** | Benchmark LLMs on structured policy reasoning; measure rationale quality, not just answer accuracy |
| **Civic tech teams** | Generate acceptance test suites before shipping a benefits chatbot or eligibility screener |
| **Government agencies** | Stress-test AI tools against edge cases (income at threshold, elderly households, asset tests) before procurement or deployment |
| **ML engineers** | Create fine-tuning or RLHF datasets grounded in real policy rules, without touching real applicant data |
| **Policy analysts** | Verify that an AI system applies the correct CFR rules in the correct order — not just gets the right answer by coincidence |

See [docs/claude-code-integration.md](docs/claude-code-integration.md) for worked examples
with Claude Code.

## Supported Programs (v0.1)

| Program | Agency | Presets | Status |
|---|---|---|---|
| [SNAP (Food Stamps)](docs/programs/snap.md) | USDA/FNS | `snap.va`, `snap.ca`, `snap.tx`, `snap.md` | Stable |
| WIC | USDA/FNS | `wic.national` | Stable |
| [Medicaid](docs/programs/medicaid.md) | CMS/HHS | `medicaid.va`, `medicaid.tx` | Stable |
| [Medicare Savings Programs + Extra Help](docs/programs/medicare.md) | CMS / SSA | `medicare.national` | Stable |
| [SSI](docs/programs/ssi.md) | SSA | `ssi.national` | Stable |
| [LIHEAP](docs/programs/liheap.md) | HHS/ACF | `liheap.va`, `liheap.ca`, `liheap.tx`, `liheap.md` | Stable |
| [CHIP / children's Medicaid](docs/programs/chip.md) | CMS/HHS | `chip.va`, `chip.ca`, `chip.tx`, `chip.md` | Stable |

## Quickstart

**Install from PyPI** (alpha; `--pre` picks up pre-releases):

```bash
pip install --pre synthetic-gov-data-kit          # add [hf] for HuggingFace export
```

The policy thresholds, census distributions and caseload tables ship inside the package, so
nothing else needs downloading. **Or install from source** for development:

```bash
git clone https://github.com/ctrimm/synthetic-gov-data-kit
cd synthetic-gov-data-kit
pip install -e ".[dev]"
```

**Python API:**

```python
from govsynth import Pipeline

# Generate 100 SNAP eligibility test cases for Virginia
pipeline = Pipeline.from_preset("snap.va")
cases = pipeline.generate(n=100, seed=42)

# Save to multiple formats
pipeline.save(cases, "./output/", formats=["yaml", "jsonl"])

print(cases[0].case_id)
# snap.va.eligibility.gross_income_at_limit.hh3

print(cases[0].expected_outcome)
# eligible

print(cases[0].rationale_trace.steps[0].rule_applied)
# 7 CFR 273.9(a)(1)
```

**CLI:**

```bash
# List available presets
govsynth list-presets

# Generate 50 SNAP/Virginia cases to a directory
govsynth generate snap.va --n 50 --seed 42 --output ./output/

# Use a specific profile strategy
govsynth generate snap.va --n 100 --seed 42 --profile-strategy realistic --output ./output/

# Stream JSONL directly to stdout (pipe-friendly)
govsynth generate snap.va --n 100 --seed 42 --format jsonl | jq '.case_id'

# Generate across multiple presets at once
govsynth batch --preset snap.va --preset wic.national --n 100 --output ./output/

# Validate generated files
govsynth validate ./output/snap.va.eligibility.gross_income_at_limit.hh3.yaml

# Inspect a single case
govsynth show ./output/snap.va.eligibility.gross_income_at_limit.hh3.yaml

# Check that bundled policy thresholds are up to date
govsynth verify-thresholds --program snap
```

## Core Concepts

### Presets

Presets bundle a data source, generator config, and profile strategy into one name:

```python
Pipeline.from_preset("snap.va")  # Virginia SNAP FY2026 — strict asset test
Pipeline.from_preset("snap.ca")  # California SNAP FY2026 — BBCE (no asset test)
Pipeline.from_preset("snap.tx")  # Texas SNAP FY2026 — strict asset test
Pipeline.from_preset("snap.md")  # Maryland SNAP FY2026 — BBCE
Pipeline.from_preset("wic.national")  # WIC FY2026 national (185% FPL)
```

Run `govsynth list-presets` to see all currently registered presets.

### Profile Strategies

Control how synthetic citizen profiles are sampled:

```python
pipeline = Pipeline.from_preset("snap.va", profile_strategy="edge_saturated")
# 60%+ of cases land at income/asset threshold boundaries — where models fail most

pipeline = Pipeline.from_preset("snap.va", profile_strategy="realistic")
# Sampled from Census ACS state distributions (default vintage: ACS 2020-2024 5-year)

pipeline = Pipeline.from_preset("snap.va", profile_strategy="uniform")
# National-level approximations, no census data required
```

### Choosing the census year

`realistic` profiles come from one ACS release ("vintage"). Pick a different year, or
spread a dataset across several years, with `census_years`:

```python
# One year: 5-year estimates ending in 2022
Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years=2022)

# Several years, spread evenly across cases (round-robin, deterministic per seed)
Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years="2021-2024")

# The most current data: ACS 1-year estimates
Pipeline.from_preset("snap.va", profile_strategy="realistic", census_years="acs1-2025")
```

```bash
govsynth generate snap.va -s realistic --census-year 2021-2024 -n 400 -o out/
govsynth generate snap.va -s realistic --census-year 2022 --census-year acs1-2025
```

A bare year means the 5-year estimates ending that year (`2024` = 2020-2024); `acs1-YYYY` means
the 1-year estimates. Each case records its vintage in `metadata["census_vintage"]`, and the
YAML, JSONL and CSV outputs carry it too. Requesting a year with no data fails up front
rather than silently falling back.

Bundled: all 50 states, DC and national, for `acs5` 2021-2024 and `acs1` 2021-2025
(468 files, ~4 MB). A jurisdiction without its own file (Guam, the Virgin Islands) uses the
same year's national file, with a warning. Refresh or add a year with:

```bash
govsynth refresh-census-data --year 2024                          # all states + DC + national
govsynth refresh-census-data --state TX --year 2025 --survey acs1  # one state, 1-year
```

No API key is needed for ACS 2021 onward: without `CENSUS_API_KEY` the command streams the
Census Bureau's bulk summary files. Older years need the API (`--source api` plus a key).

**Rules follow the census year.** SNAP cases built from ACS year *Y* data are judged by the
FY*Y* rules: that year's income limits, deductions, allotments, asset limits and BBCE
parameters (FY2021–FY2026 are bundled). Pass `match_census_year=False` (CLI:
`--fixed-policy-year`) to apply the preset's fiscal year to every case instead. Special-population
cases whose rule wasn't in force that year are skipped (the 2025 noncitizen changes before
FY2026; student rules during the 2021–2023 pandemic exemptions). See
[docs/programs/snap.md](docs/programs/snap.md#fiscal-years).

**Incomes are in the rules year's dollars.** Census incomes are in their vintage's dollars.
When a case's rules come from a different year (SNAP with `--fixed-policy-year`, or Medicaid's
CY2026 limits), income is restated with the BLS CPI-U annual average
(`data/thresholds/cpi_u_annual.json`, built by `scripts/import_cpi.py`), and each case records
`metadata["income_dollar_year"]`.

### Whole households, not independent traits

For the default vintage (`acs5-2024`), `realistic` profiles are drawn from **joint household
types** built from the ACS Public Use Microdata Sample: household size, income band, any member
60+ or disabled, any child, any earnings, the householder's citizenship and age band, plus the
type's earned share of income. Drawing a whole type keeps the correlations that drive
eligibility -- a one-person household never has children, older households earn less, larger
households have more income -- which the per-trait summary rates lose. Exact income, age and
earnings are drawn synthetically within the type; shelter costs and assets still come from the
summary tables. No microdata record is stored: each type aggregates at least three sampled
households, and smaller cells are folded into their nearest type with the same size, children,
elderly/disabled, earnings and citizenship. Profiles record `household_model`
(`pums_household_types` or `acs_marginals`), and cases copy it to `metadata["household_model"]`.
Other vintages use the summary rates until their types are built:

```bash
python scripts/build_pums_households.py --state VA --year 2023 --survey acs5
```

### Who applies, not just who lives here: the SNAP caseload

The census describes everyone who *might* ask an eligibility question. The people SNAP actually
serves look different: 60% are one-person households, half include someone elderly or disabled,
19% have no countable income, and 22% receive SSI. `population="caseload"` samples that
population instead, from the USDA FNS *Characteristics of SNAP Households: FY2024* tables built
from the SNAP Quality Control sample (`data/caseload/snap_qc_fy2024.json`,
`scripts/import_snap_qc.py`):

```python
Pipeline.from_preset("snap.va", profile_strategy="realistic", population="caseload")
```

```bash
govsynth generate snap.va -s realistic --population caseload -n 500 -o out/
govsynth validate-distribution --state all --population caseload
```

Each profile is one cell of a joint table -- children, elderly/disabled, household size, gross
income as a percent of poverty, earnings, SSI, Social Security -- fit to every national
cross-tabulation in the report and then raked to the state's own figures, so traits keep their
real correlations (elderly households stay mostly single-person and on Social Security). Incomes
are placed against the poverty guideline of the rules year, and cases record
`metadata["household_model"] = "snap_qc_fy2024"`. Caseload data is bundled for SNAP only; the
QC microdata site refuses automated access, so the published tables are used.


```bash
govsynth validate-distribution --state VA          # one state, every metric
govsynth validate-distribution --state all --json  # all 51 jurisdictions; exits 1 on any failure
govsynth validate-distribution --state VA --population caseload  # SNAP caseload vs. the QC tables
```

This samples `realistic` profiles and compares them with their census targets (children,
elderly/disabled, citizenship, earnings, household size, median income), using tolerances of
4 standard errors. It also checks the census targets themselves against plausible ranges, since
a sampler faithfully reproduces wrong data. When a state uses PUMS household types the targets are
the types' own shares, and the test suite separately checks those shares against the summary
tables. The same checks run in the test suite for every state.

### Batch Generation

**CLI (recommended):**

```bash
govsynth batch \
  --preset snap.va --preset snap.ca --preset snap.tx \
  --preset wic.national \
  --n 150 --seed 42 \
  --output ./suite-v1/
```

**Python API:**

```python
from govsynth import BatchPipeline

batch = BatchPipeline.from_presets(["snap.va", "snap.ca", "snap.tx", "wic.national"])
cases = batch.generate(n_per_pipeline=150, seed=42)
batch.save(cases, "./suite-v1/", formats=["yaml", "jsonl"])
```

### Output Formats

```python
pipeline.save(cases, "./output/", formats=["yaml"])  # One .yaml file per case
pipeline.save(cases, "./output/", formats=["jsonl"])  # Fine-tuning (messages format)
pipeline.save(cases, "./output/", formats=["csv"])  # Review/inspection
pipeline.save(cases, "./output/", formats=["yaml", "jsonl", "csv"])  # All three
```

## Example Output

```yaml
case_id: snap.va.eligibility.gross_income_at_limit.hh3
program: snap
jurisdiction: us.va
task_type: eligibility
difficulty: hard

scenario:
  summary: >
    Maria is a 34-year-old single parent in Arlington, VA with two children (ages 5 and 8).
    Her gross monthly income from part-time employment is $2,311. She has $1,800 in savings.
    No household member is elderly or disabled. She is a US citizen.
  household_size: 3
  monthly_gross_income: 2311
  state: VA

task:
  instruction: >
    Determine whether this household is eligible for SNAP benefits.
    Show your reasoning step by step, citing relevant regulations.

expected_outcome: eligible
expected_answer: >
  This household is eligible for SNAP. At $2,311/month gross income, the household is
  exactly at (not over) the 130% FPL gross income limit for a 3-person household in FY2025.
  After the 20% earned income deduction and $198 standard deduction, net income is $1,651,
  below the $1,776 net limit. Assets of $1,800 are below the $2,750 limit. Estimated
  monthly benefit: approximately $478.

rationale_trace:
  steps:
    - step: 1
      rule: "7 CFR 273.9(a)(1)"
      description: Identify gross income limit for household size
      computation: "3-person household → $2,311/month (130% FPL, FY2025)"
      result: gross_limit = $2,311
    - step: 2
      rule: "7 CFR 273.9(a)(1)"
      description: Compare gross income to limit
      computation: "$2,311 <= $2,311 — AT limit, passes gross test"
      result: PASS
    - step: 3
      rule: "7 CFR 273.9(d)(1),(d)(2)"
      description: Calculate net income after deductions
      computation: "2311 - (2311 × 0.20) - 198 = $1,651"
      result: net_income = $1,651
    - step: 4
      rule: "7 CFR 273.9(a)(2)"
      description: Compare net income to net limit
      computation: "$1,651 <= $1,776 — PASS"
      result: PASS
    - step: 5
      rule: "7 CFR 273.8(b)(1)"
      description: Check asset limit
      computation: "$1,800 <= $2,750 — PASS"
      result: PASS
  conclusion: "ELIGIBLE. All three tests passed: gross income, net income, assets."
  policy_basis:
    - "7 CFR Part 273 (2025)"
    - "FNS SNAP Income and Resource Limits FY2025"

variation_tags: [income_threshold, gross_income_at_limit, single_parent]
difficulty: hard
```

## CLI Reference

| Command | Description |
|---|---|
| `govsynth list-presets [--json]` | List all registered presets |
| `govsynth generate <preset> [--profile-strategy <s>] [--census-year <y>]` | Generate cases for one preset |
| `govsynth batch --preset ... --output` | Generate across multiple presets |
| `govsynth validate <file>` | Validate a generated output file |
| `govsynth show <file> [case_id]` | Pretty-print a single case |
| `govsynth verify-thresholds [--program]` | Check bundled threshold data is up to date |
| `govsynth refresh-census-data [--state] [--year] [--survey]` | Fetch ACS Census distributions for one vintage (keyless for 2021+) |
| `govsynth validate-distribution [--state] [--census-year] [-n]` | Check realistic profiles against their census targets |
| `govsynth parse-policy <file>` | *(coming soon)* Extract thresholds from a policy PDF |

All commands support `--json` for machine-readable output and are safe to use in CI pipelines and agentic workflows. Rich progress and status output always goes to **stderr**; data always goes to **stdout**.

```bash
# Machine-readable output — safe for scripting
govsynth list-presets --json
govsynth verify-thresholds --json
govsynth generate snap.va --n 10 --seed 42 --format jsonl --quiet

# CI usage: exit code 1 if any threshold files are unverified
govsynth verify-thresholds && echo "All thresholds verified"
```

## Notebooks

![Jupyter notebooks screenshot showing SNAP edge case analysis](docs/jupyter_notebooks_screenshot.png)

| Notebook | What it covers |
|---|---|
| [`01_quickstart.ipynb`](notebooks/01_quickstart.ipynb) | End-to-end intro: generate, inspect, export, score |
| [`02_snap_edge_cases.ipynb`](notebooks/02_snap_edge_cases.ipynb) | Deep dive into SNAP threshold boundaries |
| [`03_wic_eligibility.ipynb`](notebooks/03_wic_eligibility.ipynb) | WIC basics: 185% FPL, no asset test, categorical eligibility |
| [`04_wic_edge_cases.ipynb`](notebooks/04_wic_edge_cases.ipynb) | WIC boundary sweep: income offsets, household size sensitivity |
| [`05_realistic_profiles.ipynb`](notebooks/05_realistic_profiles.ipynb) | Census ACS distributions vs. uniform sampling |
| [`06_rationale_evaluation.ipynb`](notebooks/06_rationale_evaluation.ipynb) | Scoring LLM reasoning with `RationaleEvaluator` |
| [`07_batch_pipeline.ipynb`](notebooks/07_batch_pipeline.ipynb) | Building a full CivBench multi-program test suite |
| [`08_multi_state_batch.ipynb`](notebooks/08_multi_state_batch.ipynb) | Batch generation across states with HuggingFace export |
| [`09_cli_workflow.ipynb`](notebooks/09_cli_workflow.ipynb) | Full CLI workflow: generate → validate → show |
| [`10_custom_generator.ipynb`](notebooks/10_custom_generator.ipynb) | Adding a new program (LIHEAP example) |

## Policy Data Sources

Thresholds and policy rules come from official US government publications, except the
Medicaid and CHIP state limit tables, which are restructured (with citation) from KFF's State Health Facts.
**[DATA_SOURCES.md](DATA_SOURCES.md)** lists every bundled dataset with its source and terms.

- **SNAP**: [7 CFR Part 273](https://www.ecfr.gov/current/title-7/part-273) + FNS SNAP Handbook
- **WIC**: [7 CFR Part 246](https://www.ecfr.gov/current/title-7/part-246) + FNS WIC Policy
- **Medicaid**: [42 CFR Part 435](https://www.ecfr.gov/current/title-42/part-435) + CMS eligibility guidance
- **Federal Poverty Guidelines**: [HHS ASPE](https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines)

All generated profiles are entirely synthetic. No real applicant data is used or represented.

## Known Limitations (0.2.0a1)

- TANF and the ACA marketplace are not modeled yet (#17, #18).
- Joint census household types cover the acs5-2024 vintage only; the SNAP caseload population is
  FY2024 only.

Full list: [CHANGELOG.md](CHANGELOG.md#020a1--2026-11-17).

## Roadmap

- **Policy document parser** — `govsynth parse-policy` stub is available; full PDF/DOCX ingestion coming soon
- **Additional programs** — ACA marketplace, Section 8/HCV, TANF, SSDI
- **More task types** — policy Q&A, form completion, agentic multi-step, comparative cross-program
- **More state presets** — currently VA, CA, TX, MD for SNAP; WIC national only
- **Schema validation** — formal JSON schema (`test_case_v1.schema.yaml`) + `validate_against_schema()` utility
- **Evaluation rubrics** — structured per-difficulty scoring rubrics for `RationaleEvaluator`

---

## Bring Your Own Policy

Want to generate test cases from a policy document that isn't built in yet?
See **[docs/bring-your-own-policy.md](docs/bring-your-own-policy.md)** for a
step-by-step walkthrough: threshold JSON format, writing a DataSource connector,
writing a Generator, and registering a preset.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Policy accuracy is paramount — please cite sources
for any threshold values you add or modify.

## License

Code: MIT. See [LICENSE](LICENSE). Bundled data: see [DATA_SOURCES.md](DATA_SOURCES.md); federal
data are public domain, and the two KFF-derived tables are bundled with citation under KFF's terms for this
free, open-source project.
