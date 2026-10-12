"""
compare_runs_csv.py - Compare two Promptfoo CSV result files to detect regressions.
Author: Venkateshwara Doijode

Usage:
    python analysis/compare_runs_csv.py \
        --baseline reports/csv/regression_prod_20250101.csv \
        --current  reports/csv/regression_prod_20250102.csv

Output:
    - Tests that newly failed (regressions)
    - Tests that newly passed (improvements)
    - Tests that changed score
    - Overall pass rate change

Expected CSV columns (Promptfoo default export):
    Description, Provider, Status (Pass/Fail), Score

Generate with:
    promptfoo eval --output reports/csv/results.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Ensure Unicode output works on Windows consoles (cp1252 etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Column-name aliases - Promptfoo has varied its header names across versions.
# ---------------------------------------------------------------------------
_DESC_ALIASES  = {"description", "desc", "test", "test name", "testname"}
_PASS_ALIASES  = {"pass", "status", "success", "passed", "result"}
_SCORE_ALIASES = {"score", "metric", "grade", "value"}
_PROV_ALIASES  = {"provider", "model", "provider label"}

# Promptfoo pass/fail cell values considered a passing result
_PASS_VALUES   = {"true", "pass", "passed", "yes", "1", "success"}

_SEPARATOR_WIDTH = 60


def _find_col(cols: list[str], aliases: set[str]) -> str | None:
    """Return first column header matching an alias (case-insensitive)."""
    return next((c for c in cols if c.strip().lower() in aliases), None)


def load(path: str) -> pd.DataFrame:
    """Read CSV and return a normalised DataFrame with columns:
    description, provider, pass (bool), score (float)."""
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] File not found: {p}")
        sys.exit(1)

    df = pd.read_csv(p, encoding="utf-8-sig")
    cols = list(df.columns)

    desc_col  = _find_col(cols, _DESC_ALIASES)
    pass_col  = _find_col(cols, _PASS_ALIASES)
    score_col = _find_col(cols, _SCORE_ALIASES)
    prov_col  = _find_col(cols, _PROV_ALIASES)

    missing = [n for n, c in [("description", desc_col),
                               ("pass/status", pass_col),
                               ("score",       score_col)] if c is None]
    if missing:
        print(f"[ERROR] Missing column(s) in {p}: {missing}")
        print(f"        Available headers: {cols}")
        sys.exit(1)

    df = df.rename(columns={desc_col: "description", pass_col: "pass", score_col: "score"})
    df["provider"]    = df[prov_col].fillna("").astype(str) if prov_col else ""
    # L1: strip whitespace from description - trailing spaces cause missed matches in join
    df["description"] = df["description"].astype(str).str.strip()
    df["pass"]        = df["pass"].astype(str).str.strip().str.lower().isin(_PASS_VALUES)
    df["score"]       = pd.to_numeric(df["score"], errors="coerce").fillna(0.0).round(2)

    # L2: use fillna("") so NaN descriptions (null cells) also trigger this warning
    if df["description"].fillna("").eq("").any():
        print("[WARN] Rows with empty description found - may collide during comparison.")

    return df[["description", "provider", "pass", "score"]]


def compare(baseline_path: str, current_path: str) -> None:
    b_df = load(baseline_path)
    c_df = load(current_path)

    b = b_df.set_index(["description", "provider"])
    c = c_df.set_index(["description", "provider"])

    merged = b.join(c, how="outer", lsuffix="_b", rsuffix="_c")

    # New / removed tests
    for (desc, prov), _ in merged[merged["pass_b"].isna()].iterrows():
        print(f"  [NEW]  {desc} | {prov}")
    for (desc, prov), _ in merged[merged["pass_c"].isna()].iterrows():
        print(f"  [GONE] {desc} | {prov}")

    # C4: outer join promotes bool columns to float64/object when NaN is introduced.
    # After dropna() the NaN rows are gone but dtype stays promoted - ~float64 crashes.
    # Cast back to bool explicitly before any boolean operations.
    both = merged.dropna().copy()
    both["pass_b"] = both["pass_b"].astype(bool)
    both["pass_c"] = both["pass_c"].astype(bool)

    regressions  = both[ both["pass_b"] & ~both["pass_c"]]
    improvements = both[~both["pass_b"] &  both["pass_c"]]
    score_chg    = both[(both["pass_b"] == both["pass_c"]) &
                        (both["score_b"] != both["score_c"])]

    b_passes, b_total = int(b_df["pass"].sum()), len(b_df)
    c_passes, c_total = int(c_df["pass"].sum()), len(c_df)
    b_rate = b_passes / b_total * 100 if b_total else 0
    c_rate = c_passes / c_total * 100 if c_total else 0

    print("\n" + "=" * _SEPARATOR_WIDTH)
    print("COMPARISON SUMMARY")
    print("=" * _SEPARATOR_WIDTH)
    print(f"  Baseline pass rate : {b_rate:.1f}%  ({b_passes}/{b_total})")
    print(f"  Current pass rate  : {c_rate:.1f}%  ({c_passes}/{c_total})")
    print(f"  Change             : {c_rate - b_rate:+.1f}%")

    def _label(desc: str, prov: str) -> str:
        return f"{desc} | ({prov})" if prov else desc

    if not regressions.empty:
        print(f"\n  REGRESSIONS ({len(regressions)}) - tests that newly failed:")
        for (desc, prov), row in regressions.iterrows():
            print(f"    \u2717 {_label(desc, prov)}  ({row.score_b} \u2192 {row.score_c})")

    if not improvements.empty:
        print(f"\n  IMPROVEMENTS ({len(improvements)}) - tests that newly passed:")
        for (desc, prov), row in improvements.iterrows():
            print(f"    \u2713 {_label(desc, prov)}  ({row.score_b} \u2192 {row.score_c})")

    if not score_chg.empty:
        print(f"\n  SCORE CHANGES ({len(score_chg)}):")
        for (desc, prov), row in score_chg.iterrows():
            print(f"    ~ {_label(desc, prov)}  ({row.score_b} \u2192 {row.score_c})")

    if regressions.empty and improvements.empty and score_chg.empty:
        print("\n  No changes detected between runs.")

    print("=" * _SEPARATOR_WIDTH)

    if not regressions.empty:
        print("\n[FAIL] Regressions detected. Review before release.")
        sys.exit(1)
    else:
        print("\n[PASS] No regressions detected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two Promptfoo CSV result files.")
    parser.add_argument("--baseline", required=True, help="Path to baseline CSV result")
    parser.add_argument("--current",  required=True, help="Path to current CSV result")
    args = parser.parse_args()
    compare(args.baseline, args.current)


if __name__ == "__main__":
    main()
