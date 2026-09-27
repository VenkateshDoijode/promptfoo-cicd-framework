"""
BERTScore Validator — SecureBank AI Assistants
Author: Venkateshwara Doijode

Computes BERTScore between the model's output and a human reference answer.
BERTScore uses contextual embeddings from a pre-trained BERT model to measure
semantic similarity — it captures meaning beyond exact word overlap.

Unlike BLEU/ROUGE/METEOR, BERTScore rewards paraphrases and penalises
factually incorrect statements even when surface phrasing is similar.

Promptfoo usage:
  assert:
    - type: python
      value: file://validators/bert_score.py

Test case must supply a reference answer in vars:
  vars:
    question: "..."
    reference: "The expected answer text used as the gold standard."

Configuration (edit constants below to tune):
  MODEL_TYPE        : HuggingFace model used for embeddings. Defaults to
                       'distilbert-base-uncased' (fast, small). For higher
                       accuracy use 'roberta-large' (slower, larger download).
  DEFAULT_THRESHOLD: Minimum F1 score to pass. BERTScore F1 for high-quality
                       paraphrases typically falls in the 0.85–0.95 range.

Score interpretation (F1):
  < 0.80    : Semantically different — possible hallucination or wrong topic
  0.80–0.88 : Partially relevant — some semantic overlap
  0.88–0.93 : Good semantic match — paraphrase of the reference
  0.93+     : Very close — near-identical meaning

Network / proxy requirements:
  The first run downloads the BERT model weights (~250 MB for distilbert).
  Subsequent runs use the local cache at ~/.cache/huggingface/hub/.

If your environment uses a corporate SSL proxy (common in enterprise networks),
set one of these environment variables before running promptfoo:

  Windows PowerShell:
    $env:REQUESTS_CA_BUNDLE = "C:\\path\\to\\corporate-ca-bundle.pem"
    $env:HF_DATASETS_TRUST_REMOTE_CODE = "true"

  Linux / Mac:
    export REQUESTS_CA_BUNDLE=/path/to/corporate-ca-bundle.pem

Alternatively, pre-download the model on a machine with unrestricted internet,
copy the cache to ~/.cache/huggingface/hub/, and point HF to offline mode:
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:HF_DATASETS_OFFLINE = "1"
"""

import os
import bert_score as _bert_score_lib


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


# Model used for embedding — override via BERT_MODEL_TYPE env var.
# Default: distilbert-base-uncased (fast, ~250 MB)
# Alternative: roberta-large (more accurate, ~1.3 GB)
MODEL_TYPE = os.environ.get("BERT_MODEL_TYPE", "distilbert-base-uncased")

# Minimum BERTScore F1 to pass the assertion.
# Override via BERT_SCORE_THRESHOLD env var.
DEFAULT_THRESHOLD = _env_float("BERT_SCORE_THRESHOLD", 0.85)


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
                "BERTScore: No 'reference' variable found in test vars. "
                "Add 'reference: \"<expected answer>\"' to the test case."
            ),
        }

    if not output or not output.strip():
        return {
            "pass": False,
            "score": 0.0,
            "reason": "BERTScore: Model output is empty.",
        }

    try:
        # bert_score.score returns (P, R, F1) as lists of tensors
        P, R, F1 = _bert_score_lib.score(
            cands=[output.strip()],
            refs=[reference.strip()],
            model_type=MODEL_TYPE,
            verbose=False,
        )

        precision = float(P[0])
        recall    = float(R[0])
        f1        = float(F1[0])

    except Exception as exc:
        err_str = str(exc)
        hint = ""
        if "SSL" in err_str or "certificate" in err_str.lower():
            hint = (
                " This looks like a corporate SSL proxy issue. "
                "Set REQUESTS_CA_BUNDLE to your CA bundle path, or "
                "pre-download the model and set TRANSFORMERS_OFFLINE=1."
            )
        elif "couldn't connect" in err_str or "connection" in err_str.lower():
            hint = (
                " Unable to reach HuggingFace. Check your network, or "
                "pre-download the model and set TRANSFORMERS_OFFLINE=1."
            )
        return {
            "pass": False,
            "score": 0.0,
            "reason": (
                f"BERTScore: computation failed — {exc}.{hint}"
            ),
        }

    threshold = DEFAULT_THRESHOLD
    passed = f1 >= threshold

    reason = (
        f"BERTScore (model: {MODEL_TYPE}) — "
        f"F1: {f1:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f} "
        f"(threshold: {threshold:.2f}). "
        f"{'PASS' if passed else 'FAIL'}: semantic similarity "
        f"{'meets' if passed else 'does not meet'} the minimum threshold."
    )

    return {"pass": passed, "score": f1, "reason": reason}
