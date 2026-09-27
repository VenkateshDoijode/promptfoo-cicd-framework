"""
BLEU Score Validator — SecureBank AI Assistants
Author: Venkateshwara Doijode

Measures n-gram overlap between the model's output and a human reference answer
using SacreBLEU (corpus-level BLEU, sentence-level sBLEU).

Promptfoo usage:
  assert:
    - type: python
      value: file://validators/bleu.py
      threshold: 0.3   # optional — overrides DEFAULT_THRESHOLD below

Test case must supply a reference answer in vars:
  vars:
    question: "..."
    reference: "The expected answer text used as the gold standard."

Score interpretation:
  0.0–0.05 : Very low overlap — likely off-topic or wrong answer
  0.05–0.15: Some relevant content but phrasing diverges significantly
  0.15–0.3 : Good overlap — acceptable paraphrase for Q&A tasks
  0.3+     : High overlap — near-identical or very close to reference

Note: BLEU is strict about exact n-gram matches. For free-form chatbot
and Q&A tasks a score of 0.15 is the recommended minimum — paraphrases
of correct answers typically score 0.10–0.25. Use ROUGE or METEOR if
you want to reward semantically equivalent but differently-worded answers.
"""

import os

from sacrebleu.metrics import BLEU


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

# Minimum sentence-level BLEU to consider the assertion passed.
# Lower than the standard MT threshold (0.3) because Q&A outputs are
# often correct paraphrases that don't exactly match the reference wording.
# Override via BLEU_THRESHOLD env var.
DEFAULT_THRESHOLD = _env_float("BLEU_THRESHOLD", 0.15)

_bleu = BLEU(effective_order=True)   # sentence-level, skips empty n-gram orders


def validate(output: str, context: dict) -> dict:
    """
    Promptfoo calls this with:
      output  = model response text
      context = dict with keys: vars, prompt, provider, test, etc.

    Returns:
      dict with keys: pass (bool), score (float 0–1), reason (str)
    """
    reference = context.get("vars", {}).get("reference", "")

    if not reference:
        return {
            "pass": False,
            "score": 0.0,
            "reason": (
                "BLEU: No 'reference' variable found in test vars. "
                "Add 'reference: \"<expected answer>\"' to the test case."
            ),
        }

    if not output or not output.strip():
        return {
            "pass": False,
            "score": 0.0,
            "reason": "BLEU: Model output is empty.",
        }

    try:
        # sacrebleu expects hypothesis and a list of reference strings
        result = _bleu.sentence_score(
            hypothesis=output.strip(),
            references=[reference.strip()],
        )
    except Exception as exc:
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"BLEU: computation failed — {exc}",
        }

    # sentence_score returns a BLEUScore with .score in 0-100 range
    raw_score = result.score / 100.0
    threshold = DEFAULT_THRESHOLD

    passed = raw_score >= threshold
    reason = (
        f"BLEU score: {raw_score:.3f} (threshold: {threshold:.2f}). "
        f"Precision breakdown — {result.precisions[0]:.1f}% 1-gram, "
        f"{result.precisions[1]:.1f}% 2-gram, "
        f"{result.precisions[2]:.1f}% 3-gram, "
        f"{result.precisions[3]:.1f}% 4-gram. "
        f"{'PASS' if passed else 'FAIL'}: output {'meets' if passed else 'does not meet'} "
        f"the minimum BLEU threshold."
    )

    return {"pass": passed, "score": raw_score, "reason": reason}
