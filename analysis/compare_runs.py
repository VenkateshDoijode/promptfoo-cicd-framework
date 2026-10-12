"""
compare_runs.py - Compare two Promptfoo JSON result files to detect regressions.
Author: Venkateshwara Doijode

Usage:
    python analysis/compare_runs.py \
        --baseline reports/json/regression_prod_20250101.json \
        --current  reports/json/regression_prod_20250102.json

Output:
    - Tests that newly failed (regressions)
    - Tests that newly passed (improvements)
    - Tests that changed score
    - Overall pass rate change
"""

import argparse
import json
import sys
from pathlib import Path

_SEPARATOR_WIDTH = 60

# FIX: ensure Unicode output works on Windows consoles (cp1252 etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] File not found: {p}")
        sys.exit(1)
    # FIX: explicit encoding - without this, Windows cp1252 locale crashes
    # when test descriptions contain non-ASCII characters (e.g. Hindi, symbols)
    with open(p, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            print(f"[ERROR] Invalid JSON in {p}: {exc}")
            print("        The file may be truncated (CI job killed mid-write). "
                  "Re-run the evaluation to regenerate it.")
            sys.exit(1)


def extract_results(data: dict) -> dict:
    """Return a dict keyed by (description, provider_label) → result dict."""
    index = {}
    # FIX: Promptfoo JSON structure nests results twice: { "results": { "results": [...] } }
    # The outer key is the top-level object; the inner key is the actual test result array.
    # L3: guard - if future Promptfoo stores "results" as a list (not dict), .get() would
    # raise AttributeError. Treat any non-dict value as an empty container.
    results_outer = data.get("results", {})
    if not isinstance(results_outer, dict):
        print(f"  [WARN] Unexpected 'results' type: {type(results_outer).__name__}. Expected dict.")
        return index
    for r in results_outer.get("results", []):
        # provider can be a dict {"id": "...", "label": "..."} or a plain string
        # depending on the promptfoo version and config. Guard with isinstance
        # to avoid AttributeError: 'str' object has no attribute 'get'.
        provider = r.get("provider", {})
        provider_label = provider.get("label", "") if isinstance(provider, dict) else str(provider)
        key = (r.get("description", ""), provider_label)
        if key in index:
            print(
                f"  [WARN] Duplicate key (description='{key[0]}', provider='{key[1]}') "
                "- second result overwrites first. Consider adding unique descriptions."
            )
        index[key] = r
    return index


def compare(baseline_path: str, current_path: str) -> None:
    baseline_data = load(baseline_path)
    current_data  = load(current_path)

    baseline = extract_results(baseline_data)
    current  = extract_results(current_data)

    # regressions - tests that PASSED in baseline but FAIL in current run.
    #   Indicates a breaking change. CI/CD pipeline will block on these.
    regressions = []

    # improvements - tests that FAILED in baseline but PASS in current run.
    #   Indicates a fix or model improvement. Informational only.
    improvements = []

    # score_changes - tests where pass/fail status is the same but the numeric
    #   score shifted. Useful for tracking gradual quality drift.
    score_changes = []

    all_keys = set(baseline) | set(current)

    for key in sorted(all_keys):
        desc, provider = key
        b = baseline.get(key)
        c = current.get(key)

        if b is None:
            print(f"  [NEW]  {desc} | {provider}")
            continue
        if c is None:
            print(f"  [GONE] {desc} | {provider}")
            continue

        b_pass = bool(b.get("success", False))
        c_pass = bool(c.get("success", False))
        # L4: score may be None ("score": null) or a string → float() + fallback to 0
        b_score = round(float(b.get("score") or 0), 2)
        c_score = round(float(c.get("score") or 0), 2)

        if b_pass and not c_pass:
            # Was passing, now failing → regression
            regressions.append((desc, provider, b_score, c_score))
        elif not b_pass and c_pass:
            # Was failing, now passing → improvement
            improvements.append((desc, provider, b_score, c_score))
        elif b_score != c_score:
            # Pass/fail unchanged but score drifted → score change
            score_changes.append((desc, provider, b_score, c_score))

    # Summary
    b_results_outer = baseline_data.get("results", {})
    c_results_outer = current_data.get("results", {})
    b_stats = b_results_outer.get("stats", {}) if isinstance(b_results_outer, dict) else {}
    c_stats = c_results_outer.get("stats", {}) if isinstance(c_results_outer, dict) else {}
    # L5: warn when stats block is absent - older Promptfoo versions omit it
    if not b_stats or not c_stats:
        print("  [WARN] 'stats' block missing from one or both result files. "
              "Pass rate totals may show 0/0. Re-run with a supported Promptfoo version.")
    b_passes = b_stats.get("successes", 0)
    c_passes = c_stats.get("successes", 0)
    b_total  = b_passes + b_stats.get("failures", 0)
    c_total  = c_passes + c_stats.get("failures", 0)
    b_rate   = (b_passes / b_total * 100) if b_total else 0
    c_rate   = (c_passes / c_total * 100) if c_total else 0

    print("\n" + "=" * _SEPARATOR_WIDTH)
    print("COMPARISON SUMMARY")
    print("=" * _SEPARATOR_WIDTH)
    # FIX: show raw counts (passes/total) - matches compare_runs_csv.py output format
    print(f"  Baseline pass rate : {b_rate:.1f}%  ({b_passes}/{b_total})")
    print(f"  Current pass rate  : {c_rate:.1f}%  ({c_passes}/{c_total})")
    print(f"  Change             : {c_rate - b_rate:+.1f}%")

    if regressions:
        print(f"\n  REGRESSIONS ({len(regressions)}) - tests that newly failed:")
        for desc, provider, b_sc, c_sc in regressions:
            # FIX: use escaped Unicode \u2717 - direct chars crash Windows cp1252
            label = f"{desc} | {provider}" if provider else desc
            print(f"    \u2717 {label}  ({b_sc} \u2192 {c_sc})")

    if improvements:
        print(f"\n  IMPROVEMENTS ({len(improvements)}) - tests that newly passed:")
        for desc, provider, b_sc, c_sc in improvements:
            label = f"{desc} | {provider}" if provider else desc
            print(f"    \u2713 {label}  ({b_sc} \u2192 {c_sc})")

    if score_changes:
        print(f"\n  SCORE CHANGES ({len(score_changes)}):")
        for desc, provider, b_sc, c_sc in score_changes:
            label = f"{desc} | {provider}" if provider else desc
            print(f"    ~ {label}  ({b_sc} \u2192 {c_sc})")

    if not regressions and not improvements and not score_changes:
        print("\n  No changes detected between runs.")

    print("=" * _SEPARATOR_WIDTH)

    if regressions:
        print("\n[FAIL] Regressions detected. Review before release.")
        sys.exit(1)
    else:
        print("\n[PASS] No regressions detected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two Promptfoo result files.")
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON result")
    parser.add_argument("--current", required=True, help="Path to current JSON result")

    args = parser.parse_args()
    compare(args.baseline, args.current)


if __name__ == "__main__":
    main()
