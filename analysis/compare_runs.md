# compare_runs.py

Compare two Promptfoo JSON result files to detect regressions between runs.

**Author:** Venkateshwara Doijode
**Location:** `scripts/compare_runs.py`

---

## Overview

`compare_runs.py` takes a **baseline** JSON report and a **current** JSON report produced by Promptfoo, then highlights what changed between the two runs:

| Category | Description |
|---|---|
| **Regressions** | Tests that passed in baseline but fail in current. Blocks CI/CD. |
| **Improvements** | Tests that failed in baseline but pass in current. Informational. |
| **Score Changes** | Pass/fail status unchanged but numeric score drifted. |
| **New / Gone** | Tests that appeared or disappeared between runs. |

---

## Usage

```bash
python scripts/compare_runs.py \
    --baseline reports/json/regression_prod_20250101.json \
    --current  reports/json/regression_prod_20250102.json
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `--baseline` | Yes | Path to the baseline Promptfoo JSON result file |
| `--current` | Yes | Path to the current Promptfoo JSON result file |

---

## Input File Format

The script requires **two** Promptfoo JSON output files - a baseline and a current run - both sharing the same structure.

### Baseline File (`--baseline`)

```json
{
  "results": {
    "results": [
      {
        "description": "test name",
        "provider": { "label": "gpt-4o" },
        "success": true,
        "score": 0.95
      }
    ],
    "stats": {
      "successes": 19,
      "failures": 1
    }
  }
}
```

Generate with:

```bash
promptfoo eval --output reports/json/baseline.json
```

### Current File (`--current`)

```json
{
  "results": {
    "results": [
      {
        "description": "test name",
        "provider": { "label": "gpt-4o" },
        "success": false,
        "score": 0.40
      }
    ],
    "stats": {
      "successes": 16,
      "failures": 4
    }
  }
}
```

Generate with:

```bash
promptfoo eval --output reports/json/current.json
```

---

## Output

The script prints a comparison summary to stdout:

```
------------------------------------------------------------
COMPARISON SUMMARY
------------------------------------------------------------
  Baseline pass rate : 95.0%
  Current pass rate  : 88.0%
  Change             : -7.0%

  REGRESSIONS (2) - tests that newly failed:
    ✗ My test description | gpt-4o  (1.0 → 0.0)
    ✗ Another test        | claude-3  (0.9 → 0.4)

  IMPROVEMENTS (1) - tests that newly passed:
    ✓ Fixed test          | gpt-4o  (0.0 → 1.0)

  SCORE CHANGES (3):
    ~ Drifting test       | gpt-4o  (0.85 → 0.72)
------------------------------------------------------------

[FAIL] Regressions detected. Review before release.
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | No regressions detected - safe to release |
| `1` | Regressions detected - CI/CD pipeline should block |

---

## CI/CD Integration

Add this step after running Promptfoo to gate your pipeline on regressions:

```yaml
- name: Compare runs
  run: |
    python scripts/compare_runs.py \
      --baseline reports/json/baseline.json \
      --current  reports/json/current.json
```

The non-zero exit code on regressions will automatically fail the pipeline step.

---

# compare_runs_csv.py

Compare two Promptfoo **CSV** result files to detect regressions between runs.

**Author:** Venkateshwara Doijode
**Location:** `scripts/compare_runs_csv.py`

---

## Overview

`compare_runs_csv.py` works identically to `compare_runs.py` but reads CSV output instead of JSON. It detects the same four categories of change:

| Category | Description |
|---|---|
| **Regressions** | Tests that passed in baseline but fail in current. Blocks CI/CD. |
| **Improvements** | Tests that failed in baseline but pass in current. Informational. |
| **Score Changes** | Pass/fail status unchanged but numeric score drifted. |
| **New / Gone** | Tests that appeared or disappeared between runs. |

---

## Usage

```bash
python scripts/compare_runs_csv.py \
    --baseline reports/csv/regression_prod_20250101.csv \
    --current  reports/csv/regression_prod_20250102.csv
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `--baseline` | Yes | Path to the baseline Promptfoo CSV result file |
| `--current` | Yes | Path to the current Promptfoo CSV result file |

---

## Input File Format

The script requires **two** Promptfoo CSV output files - a baseline and a current run.

### Expected CSV columns (Promptfoo default export)

| Column | Required | Accepted aliases (case-insensitive) |
|---|---|---|
| `Description` | Yes | `description`, `desc`, `test`, `test name` |
| `Status` | Yes | `status`, `pass`, `success`, `result` |
| `Score` | Yes | `score`, `metric`, `grade` |
| `provider` | No | `provider`, `model` |

Generate with:

```bash
promptfoo eval --output reports/csv/baseline.csv
promptfoo eval --output reports/csv/current.csv
```

### Example CSV

```csv
Description,provider,Status,Score
Phishing awareness,gpt-4o,Pass,1.0
SIM swap fraud,gpt-4o,Pass,0.9
Fraudulent transaction,gpt-4o,Fail,0.3
```

---

## Output

The script prints a comparison summary to stdout:

```
------------------------------------------------------------
COMPARISON SUMMARY
------------------------------------------------------------
  Baseline pass rate : 66.7%  (2/3)
  Current pass rate  : 75.0%  (3/4)
  Change             : +8.3%

  REGRESSIONS (1) - tests that newly failed:
    ✗ Phishing awareness | gpt-4o  (1.0 → 0.4)

  IMPROVEMENTS (1) - tests that newly passed:
    ✓ Fraudulent transaction | gpt-4o  (0.3 → 0.8)

  SCORE CHANGES (1):
    ~ SIM swap fraud | gpt-4o  (0.9 → 0.85)
------------------------------------------------------------

[FAIL] Regressions detected. Review before release.
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | No regressions detected - safe to release |
| `1` | Regressions detected - CI/CD pipeline should block |

---

## CI/CD Integration

```yaml
- name: Compare runs (CSV)
  run: |
    python scripts/compare_runs_csv.py \
      --baseline reports/csv/baseline.csv \
      --current  reports/csv/current.csv
```

---

## JSON vs CSV - When to use which

| | `compare_runs.py` (JSON) | `compare_runs_csv.py` (CSV) |
|---|---|---|
| Output flag | `--output file.json` | `--output file.csv` |
| Pass rate source | `results.stats` in JSON | Computed from CSV rows |
| Provider info | Nested `provider.label` object | Flat `provider` column |
| Use when | Full fidelity, CI/CD default | Spreadsheet analysis, quick audits |
