"""
compare_runs.py — Compare two Promptfoo JSON result files to detect regressions.
Author: Venkateshwara Doijode

Usage:
    python scripts/compare_runs.py \
        --baseline reports/json/regression_prod_20250101.json \
        --current reports/json/regression_prod_20250102.json

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


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] File not found: {p}")
        sys.exit(1)
    with open(p) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            print(f"[ERROR] Invalid JSON in {p}: {exc}")
            print(
                "  The file may be truncated (CI job killed mid-write). "
                "Re-run the evaluation to regenerate it."
            )
            sys.exit(1)


def extract_results(data: dict) -> dict:
    """Return a dict keyed by (description, provider_label) → result dict."""
    index = {}
    for r in data.get("results", []):
        # provider can be a dict {"id": "...", "label": "..."} or a plain string
        # depending on the promptfoo version and config.
        # to avoid AttributeError: 'str' object has no attribute 'get'.
        provider = r.get("provider", {})
        provider_label = provider.get("label", "") if isinstance(provider, dict) else str(provider)
        key = (r.get("description", ""), provider_label)
        if key in index:
            print(
                f"  [WARN] Duplicate key (description='{key[0]}', provider='{key[1]}') "
                f"— second result overwrites first. Consider adding unique descriptions."
            )
        index[key] = r
    return index


def compare(baseline_path: str, current_path: str) -> None:
    baseline_data = load(baseline_path)
    current_data = load(current_path)

    baseline = extract_results(baseline_data)
    current  = extract_results(current_data)

    # regressions  — tests that PASSED in baseline but FAIL in current run.
    #                Indicates a breaking change. CI/CD pipeline will block on these.
    regressions = []

    # improvements — tests that FAILED in baseline but PASS in current run.
    #                Indicates a fix or model improvement. Informational only.
    improvements = []

    # score_changes — tests where pass/fail status is the same but the numeric
    #                score shifted. Useful for tracking gradual quality drift.
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

        b_pass = b.get("success", False)
        c_pass = c.get("success", False)
        b_score = round(b.get("score", 0), 2)
        c_score = round(c.get("score", 0), 2)

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
    b_stats = baseline_data.get("results", {}).get("stats", {})
    c_stats = current_data.get("results", {}).get("stats", {})
    b_total = b_stats.get("successes", 0) + b_stats.get("failures", 0)
    c_total = c_stats.get("successes", 0) + c_stats.get("failures", 0)
    b_rate = (b_stats.get("successes", 0) / b_total * 100) if b_total else 0
    c_rate = (c_stats.get("successes", 0) / c_total * 100) if c_total else 0

    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)
    print(f"  Baseline pass rate : {b_rate:.1f}%")
    print(f"  Current  pass rate : {c_rate:.1f}%")
    print(f"  Change              : {c_rate - b_rate:+.1f}%")

    if regressions:
        print(f"\n  REGRESSIONS ({len(regressions)}) — tests that newly failed:")
        for desc, provider, b, c in regressions:
            print(f"    ✗ {desc} | {provider}   ({b} → {c})")

    if improvements:
        print(f"\n  IMPROVEMENTS ({len(improvements)}) — tests that newly passed:")
        for desc, provider, b, c in improvements:
            print(f"    ✓ {desc} | {provider}   ({b} → {c})")

    if score_changes:
        print(f"\n  SCORE CHANGES ({len(score_changes)}):")
        for desc, provider, b, c in score_changes:
            print(f"    ~ {desc} | {provider}   ({b} → {c})")

    if not regressions and not improvements and not score_changes:
        print("\n  No changes detected between runs.")

    print("\n" + "=" * 60)

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
