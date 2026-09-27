"""
compare_runs_csv.py - Compare two PromptFoo CSV result files to detect regressions.
Author: Venkateshwara Doijode

Usage:
    python scripts/compare_runs_csv.py \
        --baseline reports/csv/regression_prod_20250101.csv \
        --current  reports/csv/regression_prod_20250102.csv

Output:
    - Tests that newly failed (regressions)
    - Tests that newly passed (improvements)
    - Tests that changed score
    - Overall pass rate change

Expected CSV columns (Promptfoo default export):
    Description, provider (or embedded in a "[provider] label" column),
    Status (Pass/Fail), Score

    Generate with:
        promptfoo eval --output reports/csv/results.csv
"""

import argparse
import csv
import sys
from pathlib import Path

# Ensure Unicode output works on Windows consoles (cp1252 etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Column-name aliases - PromptFoo has varied its header names across versions.
# All comparisons are case-insensitive after normalisation.
# ---------------------------------------------------------------------------
_DESCRIPTION_ALIASES = {"description", "desc", "test", "test name", "testname"}
_PROVIDER_ALIASES = {"provider", "model", "provider label"}
_PASS_ALIASES = {"pass", "status", "success", "passed", "result"}
_SCORE_ALIASES = {"score", "metric", "grade", "value"}


def _normalise(s: str) -> str:
    return s.strip().lower()


def _find_col(headers: list[str], aliases: set[str]) -> str | None:
    """Return the first header that matches one of the aliases (case-insensitive)."""
    for h in headers:
        if _normalise(h) in aliases:
            return h
    return None


def _parse_bool(value: str) -> bool:
    """Convert various pass/fail representations to bool."""
    v = value.strip().lower()
    if v in {"true", "pass", "passed", "yes", "1", "success"}:
        return True
    if v in {"false", "fail", "failed", "no", "0", "failure", "error"}:
        return False
    # Promptfoo sometimes writes 'Pass' / 'Fail' with a capital
    if v.startswith("pass"):
        return True
    return False


def load(path: str) -> list[dict]:
    """Read the CSV and return a list of row dicts with normalised keys."""
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] File not found: {p}")
        sys.exit(1)

    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print(f"[ERROR] CSV appears to be empty: {p}")
            sys.exit(1)

        headers = list(reader.fieldnames)

        # Locate required columns
        desc_col = _find_col(headers, _DESCRIPTION_ALIASES)
        pass_col = _find_col(headers, _PASS_ALIASES)
        score_col = _find_col(headers, _SCORE_ALIASES)
        prov_col = _find_col(headers, _PROVIDER_ALIASES)

        missing = [
            name for name, col in [
                ("description", desc_col),
                ("pass/status", pass_col),
                ("score", score_col),
            ]
            if col is None
        ]
        if missing:
            print(f"[ERROR] Could not find required column(s) in {p}:")
            for m in missing:
                print(f"    - {m}")
            print(f"    Available headers: {headers}")
            print(
                "    Adjust column names in your CSV or edit the alias lists "
                "at the top of this script."
            )
            sys.exit(1)

        rows = []
        for row in reader:
            rows.append({
                "description": row.get(desc_col, "").strip(),
                "provider": row.get(prov_col, "").strip() if prov_col else "",
                "pass": _parse_bool(row.get(pass_col, "false")),
                "score": _safe_float(row.get(score_col, "0")),
            })

        return rows


def _safe_float(value: str) -> float:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return 0.0


def extract_results(rows: list[dict]) -> dict:
    """Return a dict keyed by (description, provider) -> row dict."""
    index = {}
    for r in rows:
        key = (r["description"], r["provider"])
        if key in index:
            print(
                f"    [WARN] Duplicate key (description='{key[0]}', provider='{key[1]}') "
                "- second row overwrites first. Consider adding unique descriptions."
            )
        index[key] = r
    return index


def compare(baseline_path: str, current_path: str) -> None:
    baseline_rows = load(baseline_path)
    current_rows = load(current_path)

    baseline = extract_results(baseline_rows)
    current = extract_results(current_rows)

    # regressions - tests that PASSED in baseline but FAIL in current run.
    regressions = []

    # improvements - tests that FAILED in baseline but PASS in current run.
    improvements = []

    # score_changes - same pass/fail but numeric score shifted.
    score_changes = []

    all_keys = set(baseline) | set(current)

    for key in sorted(all_keys):
        desc, provider = key
        b = baseline.get(key)
        c = current.get(key)

        if b is None:
            print(f"  [NEW] {desc} | {provider}")
            continue
        if c is None:
            print(f"  [GONE] {desc} | {provider}")
            continue

        b_pass = b["pass"]
        c_pass = c["pass"]
        b_score = round(b["score"], 2)
        c_score = round(c["score"], 2)

        if b_pass and not c_pass:
            regressions.append((desc, provider, b_score, c_score))
        elif not b_pass and c_pass:
            improvements.append((desc, provider, b_score, c_score))
        elif b_score != c_score:
            score_changes.append((desc, provider, b_score, c_score))

    # --- Summary stats (computed from CSV rows directly) ---------------------
    def _stats(rows: list[dict]) -> tuple[int, int]:
        """Return (passes, total)."""
        total = len(rows)
        passes = sum(1 for r in rows if r["pass"])
        return passes, total

    b_passes, b_total = _stats(baseline_rows)
    c_passes, c_total = _stats(current_rows)

    b_rate = (b_passes / b_total * 100) if b_total else 0
    c_rate = (c_passes / c_total * 100) if c_total else 0

    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)
    print(f"  Baseline pass rate : {b_rate:.1f}% ({b_passes}/{b_total})")
    print(f"  Current pass rate  : {c_rate:.1f}% ({c_passes}/{c_total})")
    print(f"  Change             : {c_rate - b_rate:+.1f}%")

    if regressions:
        print(f"\n  REGRESSIONS ({len(regressions)}) - tests that newly failed:")
        for desc, provider, b, c in regressions:
            label = f"{desc} | {provider}" if provider else desc
            print(f"    \u2717 {label} ({b} \u2192 {c})")

    if improvements:
        print(f"\n  IMPROVEMENTS ({len(improvements)}) - tests that newly passed:")
        for desc, provider, b, c in improvements:
            label = f"{desc} | {provider}" if provider else desc
            print(f"    \u2713 {label} ({b} \u2192 {c})")

    if score_changes:
        print(f"\n  SCORE CHANGES ({len(score_changes)}):")
        for desc, provider, b, c in score_changes:
            label = f"{desc} | {provider}" if provider else desc
            print(f"    ~ {label} ({b} \u2192 {c})")

    if not regressions and not improvements and not score_changes:
        print("\n  No changes detected between runs.")

    print("=" * 60)

    if regressions:
        print("\n[FAIL] Regressions detected. Review before release.")
        sys.exit(1)
    else:
        print("\n[PASS] No regressions detected.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two Promptfoo CSV result files."
    )
    parser.add_argument(
        "--baseline", required=True,
        help="Path to baseline CSV result (promptfoo eval --output baseline.csv)"
    )
    parser.add_argument(
        "--current", required=True,
        help="Path to current CSV result (promptfoo eval --output current.csv)"
    )
    args = parser.parse_args()
    compare(args.baseline, args.current)


if __name__ == "__main__":
    main()
