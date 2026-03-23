# CLAUDE.md

This file provides context for Claude Code and AI coding assistants working in this repository.

---

## Project Overview

`synthetic-gov-data-kit` is a Python library for generating structured synthetic US government
benefits data used to evaluate LLM reasoning and rationale quality. It is the data generation
layer for [CivBench](https://github.com/civbench/civbench) — the open benchmark for government
AI agents.

The core value proposition is **reasoning-grounded test cases**: every generated case includes
not just a question and expected answer, but a step-by-step `RationaleTrace` mapping the correct
policy reasoning chain. This enables evaluation of *how* a model reasons, not just *what* it answers.

---

## Repository Layout

```
govsynth/               Main Python package
  sources/us/           US government data connectors (SNAP, WIC, Medicaid, etc.)
  profiles/             Synthetic citizen/household profile generators
  generators/           Test case generators (eligibility, policy_qa, form, agentic)
  reasoning/            RationaleTrace builders and policy rules engine
  formatters/           Output serializers (CivBench YAML, JSONL, CSV, HuggingFace)
  evaluation/           Rationale scoring utilities

data/seeds/us/          Bundled policy seed data (income limits, CFR excerpts)
data/thresholds/        Annually-updated threshold tables (FPL, program limits)

tests/unit/             Unit tests — one file per module
tests/integration/      Integration tests — end-to-end pipeline runs

notebooks/              Jupyter notebooks (quickstart, program-specific examples)
docs/                   Extended documentation
```

---

## Key Abstractions

| Class | File | Purpose |
|---|---|---|
| `DataSource` | `sources/base.py` | Abstract base for all data connectors |
| `CitizenProfile` | `profiles/base.py` | Abstract base for synthetic applicant profiles |
| `Generator` | `generators/base.py` | Abstract base for test case generators |
| `TestCase` | `models/test_case.py` | Core output data structure |
| `RationaleTrace` | `models/rationale.py` | Step-by-step reasoning chain |
| `Pipeline` | `pipeline.py` | High-level orchestration |
| `BatchPipeline` | `pipeline.py` | Multi-program orchestration |

---

## Data Models (Pydantic v2)

All core data models use **Pydantic v2** with strict validation. When adding fields:
- Always provide `description=` in `Field()`
- Use `Literal` types for constrained string fields
- Use `Annotated` for field-level constraints (e.g. income must be >= 0)

```python
# Correct pattern
from pydantic import BaseModel, Field
from typing import Annotated
from annotated_types import Ge

class HouseholdProfile(BaseModel):
    monthly_gross_income: Annotated[float, Ge(0)] = Field(
        description="Pre-deduction monthly gross income in USD"
    )
```

---

## Policy Data

### Threshold Tables

All program threshold tables live in `data/thresholds/` as JSON. They are loaded at import time
by the relevant source connector. The schema is:

```json
{
  "program": "snap",
  "fiscal_year": 2025,
  "effective_date": "2024-10-01",
  "source": "FNS SNAP Income and Resource Limits FY2025",
  "households": {
    "1": { "gross_monthly": 1580, "net_monthly": 1215, "max_benefit": 292 },
    "2": { "gross_monthly": 2137, "net_monthly": 1644, "max_benefit": 535 },
    ...
  }
}
```

### Policy Seeds

Policy seed documents in `data/seeds/us/` are plain text excerpts from CFR and agency handbooks,
used as grounding context when generating rationale traces. They are **not** full documents —
only the specific sections relevant to eligibility determination.

**Important**: Never embed PII or real applicant data in seed files. Seeds contain only
policy rules, thresholds, and regulatory citations.

---

## Test Case IDs

CivBench case IDs follow this schema:
```
{program}.{jurisdiction}.{task_type}.{variation_descriptor}[.{disambiguator}]
```

Examples:
- `snap.va.eligibility.gross_income_at_limit.hh3`
- `snap.ca.eligibility.categorical_eligibility_override`
- `wic.national.eligibility.pregnant_income_185pct_fpl`
- `medicaid.tx.eligibility.non_expansion_coverage_gap`

Rules:
- All lowercase, dot-separated
- Jurisdiction uses ISO-style codes: `us.va`, `us.ca`, `us.tx`, or just `va` for US states
- `task_type` must be one of: `eligibility`, `policy_qa`, `form`, `agentic`, `comparative`
- Descriptor should be human-readable and specific enough to be self-documenting

---

## Adding a New Program

To add support for a new US benefits program (e.g., LIHEAP):

1. **Add threshold data**: `data/thresholds/liheap_2025.json`
2. **Add seed policy docs**: `data/seeds/us/liheap/` (CFR + agency handbook excerpts)
3. **Create source connector**: `govsynth/sources/us/liheap.py` extending `DataSource`
4. **Add program rules** to `govsynth/reasoning/rules_engine.py`
5. **Add rationale template**: `govsynth/reasoning/templates/liheap_trace.py`
6. **Register presets** in `govsynth/presets.py`
7. **Add unit tests**: `tests/unit/test_liheap_source.py`
8. **Document in** `docs/programs/liheap.md`

---

## Running Tests

```bash
# All tests
pytest

# Unit only (faster)
pytest tests/unit/

# Single test file
pytest tests/unit/test_snap_source.py -v

# With coverage report
pytest --cov=govsynth --cov-report=html
```

---

## Code Style

- **Formatter**: `ruff format` (line length 100)
- **Linter**: `ruff check` (see `pyproject.toml` for rules)
- **Type checker**: `mypy --strict`
- All public functions and classes must have docstrings
- Use Google-style docstrings

```bash
# Format + lint
ruff format . && ruff check .

# Type check
mypy govsynth/
```

---

## Important Constraints

1. **No real PII ever** — all profiles are synthetic. The `Faker` library is used for names/addresses.
2. **Policy accuracy matters** — threshold values must match the actual CFR/FNS tables for the given fiscal year. Always cite the source regulation.
3. **Deterministic with seeds** — all random generation must accept a `seed: int | None` parameter and use it. Tests should use `seed=42`.
4. **CivBench compatibility** — generated YAML must validate against the CivBench test case schema.
5. **No LLM calls in generation** — the core library generates cases from policy rules, not by calling an LLM. LLM calls are only in optional enrichment utilities (clearly marked).

---

## Common Patterns

### Loading threshold data
```python
from govsynth.sources.us.snap import SNAPSource
source = SNAPSource(year=2025, state="VA")
thresholds = source.fetch_thresholds()
limit = thresholds.by_household_size(3)
```

### Generating edge cases
```python
from govsynth.profiles.us_household import USHouseholdProfile
profile = USHouseholdProfile.at_threshold(
    program="snap", threshold="gross_income_limit",
    state="VA", household_size=3, offset_pct=0.0
)
```

### Running a pipeline
```python
from govsynth import Pipeline
pipeline = Pipeline.from_preset("snap.va")
cases = pipeline.generate(n=100, seed=42)
pipeline.save(cases, "./output/", formats=["civbench_yaml", "jsonl"])
```
