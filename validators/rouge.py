"""
ROUGE Score Validator — SecureBank AI Assistants
Author: Venkateshwara Doijode

Computes ROUGE-1, ROUGE-2, and ROUGE-L F1 scores between the model's output
and a human reference answer. ROUGE is especially suited for summarisation and
information-extraction tasks where recall of key content matters.

Promptfoo usage:
  assert:
    - type: python
      value: file://validators/rouge.py

Test case must supply a reference answer in vars:
  vars:
    question: "..."
    reference: "The expected answer text used as the gold standard."

Score interpretation (ROUGE-L F1):
  0.0-0.2  : Poor coverage of reference content
  0.2-0.4  : Partial coverage - some key phrases present
  0.4-0.6  : Good coverage - most key content included
  0.6+     : High coverage - output closely mirrors the reference

The returned score is ROUGE-L F1 (longest-common-subsequence based).
ROUGE-1 and ROUGE-2 values are included in the reason for diagnostics.
"""

import os

from rouge_score import rouge_scorer


def _env_float(name: str, default: float) -> float:
    """Read an env var as float; raise ValueError with a clear message if invalid."""
    raw = os.environ.get(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name} must be a valid number, got '{raw}'. "
            "Check your env file."
        ) from None


# Minimum ROUGE-L F1 score to pass the assertion.
# Override via ROUGE_THRESHOLD env var.
DEFAULT_THRESHOLD = _env_float("ROUGE_THRESHOLD", 0.3)

_scorer = rouge_scorer.RougeScorer(
    ["rouge1", "rouge2", "rougeL"],
    use_stemmer=True,
)


def validate(output: str, context: dict) -> dict:
    """
    Promptfoo calls this with:
        output  = model response text
        context = dict with keys: vars, prompt, provider, test, etc.

    Returns:
        dict with keys: pass (bool), score (float 0-1), reason (str)
    """
    reference = context.get("vars", {}).get("reference", "")

    if not reference:
        return {
            "pass": False,
            "score": 0.0,
            "reason": (
                "ROUGE: No 'reference' variable found in test vars. "
                "Add 'reference: \"<expected answer>\"' to the test case."
            ),
        }

    if not output or not output.strip():
        return {
            "pass": False,
            "score": 0.0,
            "reason": "ROUGE: Model output is empty.",
        }

    try:
        scores = _scorer.score(
            target=reference.strip(),
            prediction=output.strip(),
        )
    except Exception as exc:
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"ROUGE: computation failed - {exc}",
        }

    r1_f = scores["rouge1"].fmeasure
    r2_f = scores["rouge2"].fmeasure
    rl_f = scores["rougeL"].fmeasure
    r1_p = scores["rouge1"].precision
    r1_r = scores["rouge1"].recall

    threshold = DEFAULT_THRESHOLD
    passed = rl_f >= threshold

    reason = (
        f"ROUGE scores - "
        f"ROUGE-1 F1: {r1_f:.3f} (P: {r1_p:.3f}, R: {r1_r:.3f}), "
        f"ROUGE-2 F1: {r2_f:.3f}, "
        f"ROUGE-L F1: {rl_f:.3f} (threshold: {threshold:.2f}). "
        f"{'PASS' if passed else 'FAIL'}: ROUGE-L {'meets' if passed else 'does not meet'} "
        f"the minimum threshold."
    )

    return {"pass": passed, "score": rl_f, "reason": reason}
