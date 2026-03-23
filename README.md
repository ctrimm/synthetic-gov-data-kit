# synthetic-gov-data-kit

> Generate structured synthetic US government benefits data for LLM reasoning evaluation.

Part of the [CivBench](https://github.com/civbench) ecosystem — the open benchmark for government AI agents.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CivBench Compatible](https://img.shields.io/badge/CivBench-compatible-orange.svg)](https://github.com/civbench/civbench)

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

```python
from govsynth import Pipeline

# Generate 100 SNAP eligibility test cases for Virginia
pipeline = Pipeline.from_preset("snap.va")
cases = pipeline.generate(n=100, seed=42)

# Save to multiple formats
pipeline.save(cases, "./output/", formats=["civbench_yaml", "jsonl"])

print(cases[0].civbench_id)
# snap.va.eligibility.gross_income_at_limit.hh3

print(cases[0].expected_outcome)
# eligible

print(cases[0].rationale_trace.steps[0].rule_applied)
# 7 CFR 273.9(a)(1)
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

```python
from govsynth import BatchPipeline

batch = BatchPipeline.from_presets([
    "snap.va", "snap.ca", "snap.tx",
    "wic.national",
    "medicaid.va", "medicaid.tx",
])

cases = batch.generate(n_per_pipeline=150, seed=42)
batch.save(cases, "./civbench-suite-v1/", format="civbench_yaml")
```

### Output Formats

```python
pipeline.save(cases, "output.yaml",    format="civbench_yaml")   # CivBench native
pipeline.save(cases, "output.jsonl",   format="jsonl")            # Fine-tuning
pipeline.save(cases, "output.csv",     format="csv")              # Review/inspection
pipeline.save(cases, "./hf_dataset/",  format="hf_dataset")       # HuggingFace (requires [hf] extra)
```

## Example Output

```yaml
civbench_id: snap.va.eligibility.gross_income_at_limit.hh3
program: snap
jurisdiction: us.va
task_type: eligibility_determination
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

## CivBench Integration

Cases output directly from `synthetic-gov-data-kit` are compatible with the CivBench
eval runner without transformation:

```bash
civbench run \
  --agent my_snap_agent.py \
  --suite-dir ./civbench-suite-v1/snap/va/ \
  --output results/
```

## Policy Data Sources

All threshold values and policy rules are sourced from official US government publications:

- **SNAP**: [7 CFR Part 273](https://www.ecfr.gov/current/title-7/part-273) + FNS SNAP Handbook
- **WIC**: [7 CFR Part 246](https://www.ecfr.gov/current/title-7/part-246) + FNS WIC Policy
- **Medicaid**: [42 CFR Part 435](https://www.ecfr.gov/current/title-42/part-435) + CMS eligibility guidance
- **Federal Poverty Guidelines**: [HHS ASPE](https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines)

All generated profiles are entirely synthetic. No real applicant data is used or represented.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Policy accuracy is paramount — please cite sources
for any threshold values you add or modify.

## License

MIT. See [LICENSE](LICENSE).

---

*Part of the [CivBench](https://github.com/civbench) open source ecosystem for government AI evaluation.*
