#!/usr/bin/env bash
# Install a built wheel into a fresh virtualenv and exercise it from outside the
# source tree, so the repository's data/ cannot mask missing package data.
# Usage: scripts/smoke_test_wheel.sh dist/synthetic_gov_data_kit-*.whl
set -euo pipefail
wheel="$(realpath "$1")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
python -m venv "$work/venv"
"$work/venv/bin/pip" install -q "$wheel"
cd "$work"
gs="$work/venv/bin/govsynth"
py="$work/venv/bin/python"

"$py" - <<'PY'
from govsynth._paths import DATA_DIR
assert "site-packages" in str(DATA_DIR), f"data resolved outside the installed package: {DATA_DIR}"
print("data dir:", DATA_DIR)
PY
"$gs" generate snap.va -n 5 --seed 42 -o out/snap -q
"$gs" generate snap.ca -s realistic --census-year 2022 -n 5 --seed 42 -o out/realistic -q
"$gs" generate snap.tx -s realistic --population caseload -n 5 --seed 42 -o out/caseload -q
for preset in wic.national medicaid.va chip.va liheap.va medicare.national ssi.national aca.tx tanf.va; do
  "$gs" generate "$preset" -n 3 --seed 42 -o "out/$preset" -q
done
"$gs" validate-distribution --state VA -n 500 > /dev/null 2>&1
"$gs" validate-distribution --state VA --population caseload -n 500 > /dev/null 2>&1
count=$(find out -name '*.yaml' | wc -l)
[ "$count" -ge 39 ] || { echo "expected >= 39 cases, got $count"; exit 1; }
echo "wheel smoke test passed: $count cases"
