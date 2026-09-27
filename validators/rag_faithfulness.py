"""
RAG Faithfulness Validator — SecureBank Loan Assistant
Author: Venkateshwara Doijode

Custom Python validator for Promptfoo that scores how faithfully the model's
response stays within the retrieved context.

Scoring logic:
  1. Extract key terms from the context
  2. Check how many key terms appear in the output
  3. Check for hallucinated numbers/percentages not in the context
  4. Check for deflection phrases that avoid answering
  5. Return a score (0.0-1.0) and detailed reason

Promptfoo calls this as:
  assert:
    - type: python
      value: file://validators/rag_faithfulness.py

The function signature must be:
  def validate(output, context) -> dict | bool
"""

import os
import re

# ------------------------------------------------------------------
# Safe environment variable readers
# ------------------------------------------------------------------

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

def _env_int(name: str, default: int) -> int:
    """Read an env var as int; raise ValueError with a clear message if invalid."""
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name} must be a valid integer, got '{raw}'. "
            "Check your env file."
        ) from None


# ------------------------------------------------------------------
# Scoring constants — override via environment variables to tune without code changes
# ------------------------------------------------------------------

DEFLECTION_PENALTY     = _env_float("RAG_DEFLECTION_PENALTY", 0.3)      # score deduction for deflection phrases
HALLUCINATION_PENALTY  = _env_float("RAG_HALLUCINATION_PENALTY", 0.2)   # score deduction per hallucinated number
LOW_COVERAGE_THRESHOLD = _env_float("RAG_LOW_COVERAGE_THRESHOLD", 0.3)  # minimum fraction of context key terms in output
LOW_COVERAGE_PENALTY   = _env_float("RAG_LOW_COVERAGE_PENALTY", 0.2)    # score deduction when coverage is below threshold
SHORT_OUTPUT_PENALTY   = _env_float("RAG_SHORT_OUTPUT_PENALTY", 0.3)    # score deduction for very short outputs
MIN_WORD_COUNT         = _env_int("RAG_MIN_WORD_COUNT", 10)             # minimum words before output is considered "too short"
PASS_THRESHOLD          = _env_float("RAG_FAITHFULNESS_THRESHOLD", 0.7)  # minimum score to pass the assertion

# Numbers considered safe (common list/step indices — not domain facts)
SAFE_NUMBERS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_numbers(text: str) -> set:
    """
    Extract numbers from text, normalised for comparison.
    Uses (?:%|\b) so percentages (8.5%) are captured correctly —
    the plain %?\b form fails because % is non-word and breaks the boundary.
    Comma separators are stripped so 20,000 and 20000 compare equal.
    """
    raw = re.findall(r'\b\d+(?:,\d+)?(?:\.\d+)?(?:%|\b)', text)
    return {n.replace(",", "") for n in raw}


def _extract_key_terms(context: str) -> list:
    """
    Extract meaningful terms from the context:
    - Numbers and percentages (e.g. 30, 8.5%, 20,000)
    - Capitalised proper nouns and product names (2+ capitalised words)
    - Domain keywords (alpha-only tokens > 6 chars, not common stopwords)
    """
    numbers = [n.replace(",", "") for n in re.findall(r'\b\d+(?:,\d+)?(?:\.\d+)?(?:%|\b)', context)]

    # Multi-word proper nouns — require at least two capitalised words to
    # avoid capturing sentence-initial common words like "The" or "Home".
    proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b', context)

    # Domain keywords — use \b\w+\b tokenisation so punctuation attached to a
    # word (e.g. "loans," or "rate.") doesn't prevent extraction or matching.
    _STOPWORDS = {
        'should', 'please', 'however', 'therefore', 'following',
        'available', 'customers', 'applicants', 'required',
    }

    tokens = re.findall(r'\b[a-zA-Z]+\b', context)
    domain_keywords = [
        word for word in tokens
        if len(word) > 6 and word.isalpha() and word.lower() not in _STOPWORDS
    ]

    return list(set(numbers + proper_nouns + domain_keywords))


def _check_deflection(output: str) -> str | None:
    """Return the deflection phrase if found, else None."""
    deflection_phrases = [
        "please visit your nearest branch",
        "i don't have access to",
        "i cannot provide",
        "i am unable to answer",
        "please contact us",
        "i don't know",
    ]
    lower_output = output.lower()
    for phrase in deflection_phrases:
        if phrase in lower_output:
            return phrase
    return None


# ------------------------------------------------------------------
# Main validator
# ------------------------------------------------------------------

def validate(output: str, context: dict) -> dict:
    """
    Promptfoo calls this function with:
      output  = the model's response text
      context = dict with keys: vars, prompt, provider, test, etc.

    Returns:
      dict with keys: pass (bool), score (float 0-1), reason (str)
    """
    # Guard: empty model output
    if not output or not output.strip():
        return {
            "pass": False,
            "score": 0.0,
            "reason": "RAG Faithfulness: model output is empty.",
        }

    # Retrieve the retrieved context from test vars
    retrieved_context = context.get("vars", {}).get("context", "")

    if not retrieved_context:
        return {
            "pass": False,
            "score": 0.0,
            "reason": "No context variable found in test vars — cannot assess faithfulness."
        }

    issues = []
    score = 1.0

    # ------------------------------------------------------------------
    # Check 1 — Deflection: model avoided answering
    # ------------------------------------------------------------------
    deflection = _check_deflection(output)
    if deflection:
        issues.append(f"Deflection phrase detected: '{deflection}'")
        score -= DEFLECTION_PENALTY

    # ------------------------------------------------------------------
    # Check 2 — Hallucinated numbers: numbers in output not in context
    # ------------------------------------------------------------------
    context_numbers = _extract_numbers(retrieved_context)
    output_numbers = _extract_numbers(output)
    hallucinated_numbers = output_numbers - context_numbers
    hallucinated_numbers -= SAFE_NUMBERS

    if hallucinated_numbers:
        issues.append(
            f"Hallucinated numbers not in context: {', '.join(sorted(hallucinated_numbers))}"
        )
        score -= HALLUCINATION_PENALTY * len(hallucinated_numbers)

    # ------------------------------------------------------------------
    # Check 3 — Key term coverage: how many context terms appear in output
    # ------------------------------------------------------------------
    key_terms = _extract_key_terms(retrieved_context)
    if key_terms:
        # Normalise output (strip comma separators from numbers) before matching.
        # Use word-boundary lookbehind/ahead so "interest" does not match inside
        # "disinterested", and (?<!\w)/(?!\w) correctly handles terms ending in %
        # where a trailing \b would fail (% is non-word, so no boundary with space).
        normalised_output = re.sub(r'(\d),(\d)', r'\1\2', output.lower())
        matched = [
            t for t in key_terms
            if re.search(r'(?<!\w)' + re.escape(t.lower()) + r'(?!\w)', normalised_output)
        ]
        coverage = len(matched) / len(key_terms)

        if coverage < LOW_COVERAGE_THRESHOLD:
            issues.append(
                f"Low context coverage: only {len(matched)}/{len(key_terms)} key terms "
                f"from context appear in output ({coverage:.0%})"
            )
            score -= LOW_COVERAGE_PENALTY

    # ------------------------------------------------------------------
    # Check 4 — Empty or very short output
    # ------------------------------------------------------------------
    word_count = len(output.split())
    if word_count < MIN_WORD_COUNT:
        issues.append(f"Output too short ({word_count} words) — likely incomplete answer.")
        score -= SHORT_OUTPUT_PENALTY

    # ------------------------------------------------------------------
    # Clamp score between 0.0 and 1.0
    # ------------------------------------------------------------------
    score = max(0.0, min(1.0, score))
    passed = score >= PASS_THRESHOLD

    if issues:
        reason = f"Faithfulness score: {score:.2f}. Issues found: {'; '.join(issues)}"
    else:
        reason = f"Faithfulness score: {score:.2f}. Output stays within the retrieved context."

    return {
        "pass": passed,
        "score": score,
        "reason": reason
    }
