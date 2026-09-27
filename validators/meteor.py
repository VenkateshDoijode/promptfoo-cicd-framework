"""
METEOR Score Validator — SecureBank AI Assistants
Author: Venkateshwara Doijode

Computes the METEOR (Metric for Evaluation of Translation with Explicit ORdering)
score between the model's output and a human reference answer using NLTK.

METEOR improves on BLEU by:
  - Prioritising recall over precision
  - Rewarding stem and synonym matches (via WordNet)
  - Penalising fragmented matches (chunk order penalty)

Promptfoo usage:
  assert:
    - type: python
      value: file://validators/meteor.py

Test case must supply a reference answer in vars:
  vars:
    question: "..."
    reference: "The expected answer text used as the gold standard."

Score interpretation:
  0.0–0.2 : Poor match — semantically very different
  0.2–0.4 : Partial match — shares some content
  0.4–0.6 : Good match — conveys similar meaning
  0.6+    : Excellent match — semantically close to reference

METEOR scores are generally higher than BLEU for the same quality level.
A threshold of 0.4 is a reasonable bar for banking Q&A tasks.
"""

import os

import nltk
from nltk.translate.meteor_score import meteor_score


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

# Minimum METEOR score to pass the assertion.
# Override via METEOR_THRESHOLD env var.
DEFAULT_THRESHOLD = _env_float("METEOR_THRESHOLD", 0.4)

# Corpora required by this validator.
# punkt_tab supersedes punkt in NLTK 3.8+; stopwords is intentionally omitted.
_NLTK_RESOURCE_MAP = {
    "punkt_tab": "tokenizers/punkt_tab",
    "wordnet":   "corpora/wordnet",
}


def _ensure_nltk_data() -> None:
    """
    Check for required corpora in the local cache using nltk.data.find()
    (which does NOT make a network request). Only download if missing.
    This replaces the previous module-level nltk.download() loop that made
    an HTTPS round-trip on every import when the data was already cached.
    """
    for corpus, resource_path in _NLTK_RESOURCE_MAP.items():
        try:
            nltk.data.find(resource_path)
        except LookupError:
            nltk.download(corpus, quiet=True)


def _tokenize(text: str) -> list[str]:
    """Lowercase-tokenise text using NLTK word tokenizer."""
    return nltk.word_tokenize(text.lower())


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
                "METEOR: No 'reference' variable found in test vars. "
                "Add 'reference: \"<expected answer>\"' to the test case."
            ),
        }

    if not output or not output.strip():
        return {
            "pass": False,
            "score": 0.0,
            "reason": "METEOR: Model output is empty.",
        }

    try:
        _ensure_nltk_data()
        hypothesis_tokens = _tokenize(output.strip())
        reference_tokens  = _tokenize(reference.strip())

        # meteor_score expects list-of-str hypothesis and list-of-list-of-str references
        score = meteor_score(
            references=[reference_tokens],
            hypothesis=hypothesis_tokens,
        )

    except LookupError as exc:
        return {
            "pass": False,
            "score": 0.0,
            "reason": (
                f"METEOR: NLTK resource missing — {exc}. "
                "Run: python -c \"import nltk; nltk.download('punkt_tab'); nltk.download('wordnet')\""
            ),
        }

    except Exception as exc:
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"METEOR: computation failed — {exc}",
        }

    threshold = DEFAULT_THRESHOLD
    passed = score >= threshold

    reason = (
        f"METEOR score: {score:.3f} (threshold: {threshold:.2f}). "
        f"{'PASS' if passed else 'FAIL'}: output {'meets' if passed else 'does not meet'} "
        f"the minimum METEOR threshold. "
        f"(METEOR accounts for stem and synonym matches beyond exact n-gram overlap.)"
    )

    return {"pass": passed, "score": score, "reason": reason}
