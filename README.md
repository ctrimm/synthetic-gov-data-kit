# synthetic-gov-data-kit

> Generate structured synthetic US government benefits data for LLM reasoning evaluation.



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

## Supported Programs (v0.1)

| Program | Agency | Coverage |
|---|---|---|
| SNAP (Food Stamps) | USDA/FNS | All 50 states + DC |
| WIC | USDA/FNS | National |
| Medicaid | CMS/HHS | All states (expansion + non-expansion) |

## Quickstart

```bash
pip install synthetic-gov-data-kit
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
Pipeline.from_preset("snap.va")          # Virginia SNAP, edge-saturated
Pipeline.from_preset("snap.ca")          # California SNAP (broad-based categorical eligibility)
Pipeline.from_preset("snap.tx")          # Texas SNAP (strict asset test)
Pipeline.from_preset("snap.national")    # All states, jurisdiction as variation axis
Pipeline.from_preset("wic.national")     # WIC national
Pipeline.from_preset("medicaid.va")      # Virginia Medicaid (expansion)
Pipeline.from_preset("medicaid.tx")      # Texas Medicaid (non-expansion)
```

### Profile Strategies

Control how synthetic citizen profiles are sampled:

```python
pipeline = Pipeline.from_preset("snap.va", profile_strategy="edge_saturated")
# 60%+ of cases land at income/asset threshold boundaries — where models fail

pipeline = Pipeline.from_preset("snap.va", profile_strategy="realistic")
# Sampled from Census ACS income distributions — representative of real applicants

pipeline = Pipeline.from_preset("snap.va", profile_strategy="adversarial")
# Conflicting documents, missing information, ambiguous circumstances
```

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
from govsynth import Pipeline

pipelines = ["snap.va", "snap.ca", "snap.tx", "wic.national"]
all_cases = []
for i, preset in enumerate(pipelines):
    pipeline = Pipeline.from_preset(preset)
    all_cases.extend(pipeline.generate(n=150, seed=42 + i))

Pipeline.from_preset(pipelines[0]).save(all_cases, "./suite-v1/", formats=["yaml", "jsonl"])
```

### Output Formats

```python
pipeline.save(cases, "./output/", formats=["yaml"])    # One .yaml file per case
pipeline.save(cases, "./output/", formats=["jsonl"])   # Fine-tuning (messages format)
pipeline.save(cases, "./output/", formats=["csv"])     # Review/inspection
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
      rule: "7 CFR 273.9(c)(1),(c)(2)"
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
| `govsynth generate <preset>` | Generate cases for one preset |
| `govsynth batch --preset ... --output` | Generate across multiple presets |
| `govsynth validate <file>` | Validate a generated output file |
| `govsynth show <file> [case_id]` | Pretty-print a single case |
| `govsynth verify-thresholds [--program]` | Check bundled threshold data is up to date |
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

## Policy Data Sources

All threshold values and policy rules are sourced from official US government publications:

- **SNAP**: [7 CFR Part 273](https://www.ecfr.gov/current/title-7/part-273) + FNS SNAP Handbook
- **WIC**: [7 CFR Part 246](https://www.ecfr.gov/current/title-7/part-246) + FNS WIC Policy
- **Medicaid**: [42 CFR Part 435](https://www.ecfr.gov/current/title-42/part-435) + CMS eligibility guidance
- **Federal Poverty Guidelines**: [HHS ASPE](https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines)

All generated profiles are entirely synthetic. No real applicant data is used or represented.

## Roadmap

- **Policy document parser** — `govsynth parse-policy` stub is available; full PDF/DOCX ingestion coming soon
- **Additional programs** — LIHEAP, CHIP, Section 8/HCV, TANF, SSI/SSDI
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

MIT. See [LICENSE](LICENSE).
