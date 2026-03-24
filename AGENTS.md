# AGENTS.md

Guidelines for AI agents (Claude Code, Cursor, Copilot Workspace, etc.) working in this repo.

---

## What This Repo Does

Generates structured synthetic US government benefits test cases for LLM evaluation.
The output feeds directly into CivBench.

**Primary concern when making changes**: policy accuracy. An incorrect income threshold
or miscited CFR section produces test cases that will silently evaluate models against
wrong ground truth. Always verify threshold values against `data/thresholds/` before
generating or modifying cases.

---

## Repo Map for Agents

```
govsynth/models/          ← Start here. Core data structures.
govsynth/sources/us/      ← Data connectors. One file per program.
govsynth/profiles/        ← Profile generators. us_household.py is the main one.
govsynth/generators/      ← Test case builders. eligibility.py is the main one.
govsynth/reasoning/       ← Rationale trace construction.
govsynth/formatters/      ← Output serialization. civbench_yaml.py, jsonl.py, csv.py.
govsynth/pipeline.py      ← High-level API. Most users start here.
govsynth/presets.py       ← Preset registry. Maps names like "snap.va" to config.
data/thresholds/          ← Source of truth for all income/asset limits.
data/seeds/us/            ← Policy text excerpts used in rationale generation.
tests/unit/               ← Test coverage. Match file to module name.
```

---

## Agent Task Playbooks

### Adding a new US program

**Files to create/modify (in order):**

1. `data/thresholds/{program}_{year}.json` — threshold table
2. `data/seeds/us/{program}/` — policy text excerpts
3. `govsynth/sources/us/{program}.py` — source connector
4. `govsynth/reasoning/templates/{program}_trace.py` — trace template
5. `govsynth/reasoning/rules_engine.py` — register program rules
6. `govsynth/presets.py` — register presets
7. `tests/unit/test_{program}_source.py` — unit tests
8. `docs/programs/{program}.md` — program documentation

**Verification:** After adding, run:
```bash
python -c "from govsynth import Pipeline; p = Pipeline.from_preset('{program}.{state}'); cases = p.generate(n=5, seed=42); print(cases[0].civbench_id)"
```

---

### Updating annual thresholds

Federal poverty levels and program income limits update each October (federal fiscal year).

1. Update `data/thresholds/us_fpl_{new_year}.json`
2. Update relevant program threshold files
3. Update `govsynth/config.py` → `DEFAULT_FISCAL_YEAR`
4. Run `pytest tests/unit/test_thresholds.py` to verify all lookups pass
5. Update `data/thresholds/README.md` with new source citations

**Source URLs:**
- FPL: https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines
- SNAP: https://www.fns.usda.gov/snap/recipient/eligibility
- WIC: https://www.fns.usda.gov/wic/eligibility
- Medicaid: https://www.medicaid.gov/medicaid/eligibility

---

### Adding a new output format

1. Create `govsynth/formatters/{format_name}.py`
2. Extend `BaseFormatter` from `govsynth/formatters/base.py`
3. Implement `format(cases: list[TestCase]) -> Any` and `write(cases, path)` methods
4. Register in `govsynth/formatters/__init__.py`
5. Add `format="{format_name}"` handling in `Pipeline.save()`
6. Add tests in `tests/unit/test_formatter_{format_name}.py`

---

### Adding edge case variations

Edge cases live in `govsynth/profiles/edge_cases.py`. Each program has a set of named
threshold types:

```python
SNAP_THRESHOLDS = [
    "gross_income_limit",      # 130% FPL
    "net_income_limit",        # 100% FPL
    "asset_limit_general",     # $2,750
    "asset_limit_elderly",     # $4,250
    "standard_deduction",      # varies by HH size
    "earned_income_deduction", # 20% of earned income
]
```

To add a new variation type:
1. Add to the relevant `{PROGRAM}_THRESHOLDS` list
2. Implement `_build_{program}_{threshold}` in `EdgeCaseFactory`
3. Add test in `tests/unit/test_edge_cases.py`
4. Document in `docs/edge-cases.md`

---

## Agent Rules

### Never do these

- **Never fabricate policy thresholds.** Always load from `data/thresholds/` or fetch from
  official source URLs. Do not hardcode income limits in generator logic.
- **Never add PII to seeds or test fixtures.** All names/SSNs/addresses must use Faker.
- **Never skip rationale traces.** If `include_reasoning_trace=True` (the default), every
  `TestCase` must have a populated `rationale_trace`. A case with `rationale_trace=None`
  is not CivBench-compatible.
- **Never change a `civbench_id` format** without updating `docs/id-schema.md` and the
  CivBench schema validator.

### Always do these

- **Cite the CFR section** for every `ReasoningStep.rule_applied` field.
- **Use `seed=42` in tests** to ensure deterministic output.
- **Run `ruff check . && mypy govsynth/`** before committing.
- **Keep threshold logic in source connectors**, not in generators. Generators call
  `source.fetch_thresholds()` — they do not hardcode values.

---

## Output Contract

Every `TestCase` produced by this library must satisfy:

```python
assert case.civbench_id != ""
assert case.program in KNOWN_PROGRAMS
assert case.jurisdiction != ""
assert case.scenario.summary != ""
assert case.task.instruction != ""
assert case.expected_outcome != ""
assert case.expected_answer != ""
assert len(case.rationale_trace.steps) >= 2
assert len(case.source_citations) >= 1
```

The `TestCase.validate()` method runs these checks. Always call it before serializing.

---

## Testing Conventions

```
tests/unit/test_{module_name}.py    — mirrors govsynth/{module_name}.py
tests/integration/test_{workflow}.py — end-to-end workflow tests
```

Every new public function needs at least:
- One happy-path test
- One edge case test (boundary condition)
- One invalid input test (raises expected exception)

```python
# Naming convention
def test_{function}_{condition}():
    ...

# Examples
def test_snap_threshold_household_size_3():
def test_snap_threshold_at_gross_income_limit():
def test_snap_threshold_raises_on_invalid_state():
```

---

## Dependency Policy

- **Core dependencies** (in `[dependencies]`): must work without any optional extras
- **HF features**: gated behind `[hf]` extra; `datasets` and `huggingface_hub` never imported at top level
- **No LLM SDKs in core**: Anthropic/OpenAI SDKs are not dependencies. Any LLM-assisted enrichment utilities go in `govsynth/enrichment/` (optional, not imported by default)

---

## CivBench Compatibility

Output YAML must validate against the CivBench test case schema. The canonical schema lives at:
`https://github.com/civbench/civbench/blob/main/schemas/test_case_v1.schema.yaml`

A local copy is maintained at `tests/fixtures/civbench_schema_v1.yaml` for offline validation.

Validation utility:
```python
from govsynth.formatters.civbench_yaml import validate_against_schema
errors = validate_against_schema(case)
assert errors == []
```
