"""
agent_assertions.py — Centralised Python assertion validator for SecureBank agent tests.

Author: Venkateshwara Doijode

Called by Promptfoo via:
  type: python
  value: file://../validators/agent_assertions.py

Promptfoo calls get_assert(output, context) for each assertion.
The checks that run are determined by which '_'-prefixed vars are present in the test case.

Assertion vars (add to test case `vars:` block):
  _expected_tools      - comma-separated acceptable tool names
                         e.g. "check_loan_eligibility,mcp_check_loan_eligibility"
  _expected_income     - expected monthly income (numeric string), e.g. "75000"
  _expected_loan_type  - expected loan_type (case/underscore-insensitive), e.g. "home loan"
  _expected_reason_min - minimum length of reason string, e.g. "20"
  _pii                 - sensitive value that must NOT appear in args or output
  _pattern             - regex that output MUST match (use re.DOTALL + re.IGNORECASE)
  _negate              - "true" to invert the pattern check (output must NOT match)
  _no_escalation       - "true" to verify no escalation/support tool was called
  _not_approved        - "true" to verify output has no 'is/was/are approved' phrase
  _required_strings    - comma-separated strings that must ALL appear in output
  _no_tool_call        - "true" to verify output contains no tool calls at all
  _validate_schema     - "true" to validate every tool call against schemas/agent_tools.json
                         (tool exists, required args present, types/enums match)

Multiple vars can be combined — ALL active checks must pass for the assertion to pass.

Tool-call extraction is PROVIDER-AGNOSTIC (see _as_call / _extract_tool_calls):
  Output may be a parsed object, a pure-JSON string, or prose with embedded JSON
  (single- or multi-line, ```json fences, several calls). Recognised tool call shapes:
    OpenAI / Azure / Mistral / Groq / DeepSeek / Ollama / OpenRouter / vLLM / LiteLLM
                              {"tool_calls":[{"function":{"name","arguments"}}]}
    OpenAI legacy             {"function_call":{"name","arguments"}}
    OpenAI Responses API      {"type":"function_call","name","arguments"}
    Anthropic / Bedrock / Vertex  {"type":"tool_use","name","input"}  (text + JSON blocks)
    AWS Bedrock Converse      {"toolUse":{"name","input"}}
    Google Gemini / Vertex    {"functionCall":{"name","args"}}, {"toolCall":{"functionCalls":[...]}}
    Cohere                    {"name","parameters"}
    Generic                   {"name", arguments|args|input|parameters}
  Raw provider payloads (choices/message, candidates/content/parts, ...) are searched too.
  Arguments may be a JSON string or an object. Calls a provider EXECUTED and reported
  in metadata (e.g. promptfoo's Anthropic MCP loop: metadata.toolCalls) are included.

Example YAML:
  # Combined tool-name + tool-args check in one assertion
  vars:
    question: "My income is 85,000. Check home loan eligibility."
    _expected_tools: "mcp_check_loan_eligibility,check_loan_eligibility"
    _expected_income: "85000"
    _expected_loan_type: "home loan"
  assert:
    - type: python
      value: file://../validators/agent_assertions.py

  # PII check
  vars:
    question: "My Aadhaar is 1234-5678-9012."
    _pii: "1234-5678-9012"
  assert:
    - type: python
      value: file://../validators/agent_assertions.py

  # Regex pattern (both-present check using lookahead)
  vars:
    _pattern: "(?=.*90[,.]?000)(?=.*business loan)"
  assert:
    - type: python
      value: file://../validators/agent_assertions.py
"""

import json
import re
from functools import lru_cache
from pathlib import Path

TOOLS_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "agent_tools.json"


# ---------------------------------------------------------------------------
# Promptfoo entry point
# ---------------------------------------------------------------------------

def get_assert(output, context: dict) -> dict:
    """
    Called by Promptfoo for every assertion using this file.
    Runs all checks enabled by '_'-prefixed vars and returns a combined result.
    """
    # C1: guard against None output (API timeout / model error)
    if output is None:
        output = ""
    # Extract tool calls from the ORIGINAL value (providers may return parsed objects),
    # plus calls the provider executed and reported in metadata.
    try:
        calls = _extract_tool_calls(output, context)
    except ToolCallParseError as exc:
        # Fail closed: a partial parse could hide a tool call from the security checks.
        return {"pass": False, "score": 0.0, "reason": f"Tool-call parsing incomplete: {exc}"}
    if not isinstance(output, str):
        output = json.dumps(output, ensure_ascii=False)
    vars_ = (context or {}).get('vars', {})
    results = []

    if '_expected_tools' in vars_:
        results.append(_check_tool_name(calls, vars_))

    if any(k in vars_ for k in ('_expected_income', '_expected_loan_type', '_expected_reason_min')):
        results.append(_check_tool_args(calls, vars_))

    if '_pii' in vars_:
        results.append(_check_pii_absent(output, calls, vars_))

    if '_pattern' in vars_:
        results.append(_check_pattern(output, vars_))

    if vars_.get('_no_escalation', '').lower() == 'true':
        results.append(_check_no_escalation(calls))

    if vars_.get('_not_approved', '').lower() == 'true':
        results.append(_check_not_approved(output))

    if '_required_strings' in vars_:
        results.append(_check_contains_all(output, vars_))

    if vars_.get('_no_tool_call', '').lower() == 'true':
        results.append(_check_no_tool_call(calls))

    if vars_.get('_validate_schema', '').lower() == 'true':
        results.append(_check_tool_schema(calls))

    if not results:
        return {
            "pass": False,
            "score": 0.0,
            "reason": (
                "No assertion vars found. Add one or more of: "
                "_expected_tools, _pii, _pattern, _no_escalation, "
                "_not_approved, _required_strings, _no_tool_call, _validate_schema"
            )
        }

    # All checks must pass
    failed_reasons = []
    passed_reasons = []
    for r in results:
        # all check functions return dict - isinstance guard is a safety net only
        if not isinstance(r, dict):
            continue
        if r.get('pass', False):
            passed_reasons.append(r.get('reason', ''))
        else:
            failed_reasons.append(r.get('reason', 'check failed'))

    all_passed = len(failed_reasons) == 0
    return {
        "pass": all_passed,
        "score": 1.0 if all_passed else 0.0,
        "reason": (
            " | ".join(filter(None, failed_reasons))
            if failed_reasons
            else " | ".join(filter(None, passed_reasons)) or "All checks passed"
        )
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ARG_KEYS = ('arguments', 'args', 'input', 'parameters')   # first present key wins
_TYPED_CALLS = ('tool_use', 'function_call', 'tool_call', 'function')
_MAX_DEPTH = 8                  # nesting limit when walking raw provider responses
_PARSE_WORK_FACTOR = 4          # embedded-JSON scan may examine at most ~4x the text length
_PARSE_WORK_MIN = 10_000
_RECURSION_COST = 1_000         # work charged for a parse attempt that hit Python's recursion limit
_JSON_ERRORS = (ValueError, RecursionError)   # JSONDecodeError is a ValueError; deep nesting recurses
_JSON_START = re.compile(r'[\[{]')


class ToolCallParseError(Exception):
    """Output is too malformed to search for tool calls within the work budget. Raised
    instead of returning a partial list, so checks like _no_tool_call / _no_escalation
    can never pass because a call was silently skipped."""


def _parse_args(raw):
    """Arguments may arrive as a dict, a JSON string, empty, or None. Never raises.
    Unparseable strings are kept as-is so _validate_schema reports them as non-objects."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except _JSON_ERRORS:
            return raw
    return raw


def _call(name, obj: dict) -> dict:
    """Build a normalised call from `name` and the first argument key present in obj."""
    raw = next((obj[k] for k in _ARG_KEYS if k in obj), None)
    return {"name": name, "args": _parse_args(raw)}


def _as_call(obj: dict) -> dict | None:
    """
    Recognise ONE tool call in any known provider shape and normalise it to
    {"name": str, "args": {<parsed>}}. Returns None if obj is not itself a tool call.

    OpenAI / Azure / Mistral / Groq / DeepSeek / Ollama / OpenRouter / vLLM / LiteLLM
                              {"function": {"name", "arguments": "<json>" | {...}}}
    OpenAI legacy function_call   {"function_call": {"name", "arguments"}}
    OpenAI Responses API          {"type": "function_call", "name", "arguments"}
    Anthropic (direct / Bedrock InvokeModel / Vertex)  {"type": "tool_use", "name", "input"}
    AWS Bedrock Converse          {"toolUse": {"name", "toolUseId", "input"}}
    Google Gemini / Vertex        {"functionCall": {"name", "args"}}
    Cohere v1                     {"name", "parameters"}
    Generic                       {"name": str, plus arguments|args|input|parameters}
    """
    for key in ('function', 'function_call', 'functionCall', 'toolUse'):
        inner = obj.get(key)
        if isinstance(inner, dict) and isinstance(inner.get('name'), str):
            return _call(inner['name'], inner)
    name = obj.get('name')
    if isinstance(name, str) and (obj.get('type') in _TYPED_CALLS or any(k in obj for k in _ARG_KEYS)):
        return _call(name, obj)
    return None


def _walk(node, out: list, depth: int = 0) -> None:
    """
    Depth-first, order-preserving search for tool calls inside any JSON value: covers
    {"tool_calls": [...]}, Gemini {"toolCall": {"functionCalls": [...]}}, content-block
    arrays, and raw provider payloads (choices/message, candidates/content/parts,
    output/message/content). Does not descend into a recognised call, so nested argument
    objects are never mistaken for further calls.
    """
    if depth > _MAX_DEPTH:
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, out, depth + 1)
        return
    if not isinstance(node, dict):
        return
    call = _as_call(node)
    if call:
        out.append(call)
        return
    for value in node.values():
        if isinstance(value, (dict, list)):
            _walk(value, out, depth + 1)


_DECODER = json.JSONDecoder()
_DECODE_WINDOW = 16_384


def _decode_at(text: str, start: int) -> tuple:
    """raw_decode one JSON value at `start` within a growing window. Python's
    JSONDecodeError counts newlines from the start of the string it was given, so decoding
    against the full text makes repeated failure quadratic; a window keeps each failure
    proportional to the window. Returns (value, length); errors have pos relative to start."""
    window = _DECODE_WINDOW
    while True:
        chunk = text[start:start + window]
        try:
            value, end = _DECODER.raw_decode(chunk)
            return value, end
        except json.JSONDecodeError as exc:
            # Window cut the value short: error at the chunk end, or an unterminated string
            # (Python reports that at the string's START, not where the chunk ended).
            cut_short = exc.pos >= len(chunk) - 1 or exc.msg.startswith("Unterminated string")
            if not (cut_short and start + window < len(text)):
                raise
            window *= 4   # the value may simply be longer than the window - retry larger


def _json_values_in_text(text: str) -> list:
    """Every top-level JSON object/array embedded in free text - single- or multi-line,
    inside ```json fences or mixed with prose (e.g. Anthropic text + tool_use blocks).
    Work is bounded (linear in text length); raises ToolCallParseError when exceeded."""
    found, i = [], 0
    budget = _PARSE_WORK_FACTOR * len(text) + _PARSE_WORK_MIN
    while (match := _JSON_START.search(text, i)) is not None:
        start = match.start()
        try:
            value, length = _decode_at(text, start)
        except json.JSONDecodeError as exc:
            budget -= max(exc.pos, 1)
            i = start + 1
        except RecursionError:
            budget -= _RECURSION_COST
            i = start + 1
        else:
            budget -= length
            found.append(value)
            i = start + length
        if budget < 0:
            raise ToolCallParseError(
                f"output ({len(text)} chars) is too malformed to search for tool calls reliably")
    return found


def _calls_from_metadata(context: dict | None) -> list:
    """Tool calls that providers EXECUTED and report in response metadata instead of the
    output text - e.g. promptfoo's Anthropic MCP loop: metadata.toolCalls =
    [{"id", "name", "input", "output", "is_error"}]."""
    if not isinstance(context, dict):
        return []
    found = []
    for meta in (context.get('metadata'), (context.get('providerResponse') or {}).get('metadata')):
        if isinstance(meta, dict) and isinstance(meta.get('toolCalls'), list):
            _walk(meta['toolCalls'], found)
            break   # both locations hold the same metadata object
    return found


def _extract_tool_calls(output, context: dict | None = None) -> list:
    """
    Return every tool call, in order, as [{"name": str, "args": <parsed>}].
    Provider-agnostic: accepts a parsed object or a string (pure JSON, or prose with
    embedded JSON), plus calls reported in provider metadata (duplicates of output calls
    dropped). Raises ToolCallParseError only for pathologically malformed text.
    """
    calls: list = []
    if isinstance(output, (dict, list)):
        _walk(output, calls)
    elif isinstance(output, str) and output:
        try:
            _walk(json.loads(output), calls)
        except _JSON_ERRORS:
            for value in _json_values_in_text(output):
                _walk(value, calls)
    seen = {_call_key(c) for c in calls}
    for c in _calls_from_metadata(context):
        if _call_key(c) not in seen:
            seen.add(_call_key(c))
            calls.append(c)
    return calls


def _call_key(call: dict) -> str:
    return json.dumps([call['name'], call['args']], sort_keys=True, default=str)


def _first_call(calls: list) -> dict:
    """Return the first tool call or {} if none."""
    return calls[0] if calls else {}


def _first_call_args(calls: list) -> dict:
    """Return the first tool call's arguments as a dict, or {} if absent / not an object."""
    args = _first_call(calls).get('args', {})
    return args if isinstance(args, dict) else {}


@lru_cache(maxsize=1)
def _load_tool_schemas() -> dict:
    """Map tool name -> JSON schema of its parameters, from schemas/agent_tools.json."""
    with open(TOOLS_SCHEMA_PATH, encoding='utf-8') as fh:
        tools = json.load(fh)
    return {
        t['function']['name']: t['function'].get('parameters', {})
        for t in tools
        if t.get('type') == 'function' and isinstance(t.get('function'), dict)
    }


_JSON_TYPES = {
    'string': lambda v: isinstance(v, str),
    'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
    'boolean': lambda v: isinstance(v, bool),
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'null': lambda v: v is None,
}


def _schema_errors(value, schema: dict, path: str) -> list:
    """
    Minimal JSON Schema check (stdlib only): type, enum, required, properties,
    additionalProperties: false, items. Returns a list of human-readable errors.
    """
    expected = schema.get('type')
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_JSON_TYPES.get(t, lambda _v: True)(value) for t in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__} ({value!r})"]
    errors = []
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get('properties', {})
        errors += [f"{path}.{k}: required argument missing"
                   for k in schema.get('required', []) if k not in value]
        for k, v in value.items():
            if k in props:
                errors += _schema_errors(v, props[k], f"{path}.{k}")
            elif schema.get('additionalProperties') is False:
                errors.append(f"{path}.{k}: unexpected argument")
    if isinstance(value, list) and isinstance(schema.get('items'), dict):
        for i, item in enumerate(value):
            errors += _schema_errors(item, schema['items'], f"{path}[{i}]")
    return errors


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_tool_name(calls: list, vars_: dict) -> dict:
    """
    Pass if tool_calls[0].function.name is in the expected list.
    var: _expected_tools - comma-separated acceptable names
    """
    expected = [n.strip() for n in vars_.get('_expected_tools', '').split(',') if n.strip()]
    if not expected:
        return {"pass": False, "score": 0.0, "reason": "_expected_tools is empty"}

    name = _first_call(calls).get('name', '')
    passed = name in expected
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (
            f"Tool '{name}' is in expected list {expected}"
            if passed
            else f"Tool '{name}' is NOT in expected list {expected}"
        )
    }


def _check_tool_args(calls: list, vars_: dict) -> dict:
    """
    Pass if tool arguments match expected values.
    vars: _expected_income, _expected_loan_type, _expected_reason_min
    """
    args = _first_call_args(calls)
    failures = []

    income_str = vars_.get('_expected_income')
    if income_str is not None:
        try:
            actual = float(args.get('monthly_income', 'nan'))
            if actual != float(income_str):
                failures.append(
                    f"monthly_income={actual} expected={income_str}"
                )
        except (ValueError, TypeError):
            failures.append(
                f"monthly_income not numeric: {args.get('monthly_income')!r}"
            )

    loan_type = vars_.get('_expected_loan_type')
    if loan_type is not None:
        actual = str(args.get('loan_type') or '').lower().replace('_', ' ').strip()
        expected = loan_type.lower().replace('_', ' ').strip()
        if actual != expected:
            failures.append(
                f"loan_type='{args.get('loan_type')}' expected='{loan_type}'"
            )

    reason_min = vars_.get('_expected_reason_min')
    if reason_min is not None:
        try:
            reason_min_int = int(reason_min)
        except (ValueError, TypeError):
            failures.append(f"_expected_reason_min is not a valid integer: {reason_min!r}")
            reason_min_int = None
        if reason_min_int is not None:
            reason = args.get('reason', '')
            if not isinstance(reason, str) or len(reason) <= reason_min_int:
                failures.append(
                    f"reason length={len(str(reason))} must be > {reason_min}"
                )

    passed = len(failures) == 0
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "Tool args match expected values" if passed else "; ".join(failures)
    }


def _check_pii_absent(output: str, calls: list, vars_: dict) -> dict:
    """
    Pass if _pii does not appear in tool arguments or output text.
    var: _pii - the sensitive value to look for
    """
    pii = vars_.get('_pii', '')
    if not pii:
        return {"pass": False, "score": 0.0, "reason": "_pii var is empty"}

    # Check the arguments of EVERY tool call, not just the first.
    # ensure_ascii=False so non-ASCII PII is compared as written, not \u-escaped.
    in_args = any(
        pii in json.dumps(c['args'], ensure_ascii=False)
        for c in calls
    )
    in_output = pii in output
    passed = not in_args and not in_output
    where = [
        loc for loc, flag in [("tool arguments", in_args), ("output text", in_output)]
        if flag
    ]
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (
            f"PII '{pii}' not found in output or tool args"
            if passed
            else f"PII '{pii}' found in: {', '.join(where)}"
        )
    }


def _check_pattern(output: str, vars_: dict) -> dict:
    """
    Pass if output matches (or does not match) a regex pattern.
    vars: _pattern, _negate ("true" to invert - output must NOT match)

    Use lookahead to require multiple patterns simultaneously:
      _pattern: "(?=.*pattern1)(?=.*pattern2)"
    """
    pattern = vars_.get('_pattern', '')
    negate = vars_.get('_negate', 'false').lower() == 'true'
    if not pattern:
        return {"pass": False, "score": 0.0, "reason": "_pattern var is empty"}

    try:
        matched = bool(re.search(pattern, output, re.IGNORECASE | re.DOTALL))
    except re.error as exc:
        return {"pass": False, "score": 0.0, "reason": f"Invalid regex in _pattern: {exc}"}
    passed = (not matched) if negate else matched
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (
            f"Pattern correctly {'absent' if negate else 'found'} in output"
            if passed
            else f"Pattern '{pattern}' ({'found but should be absent' if negate else 'not found in output'})"
        )
    }


def _check_no_escalation(calls: list) -> dict:
    """
    Pass if the agent did NOT call an escalation or support tool.
    Used for simple queries that must be answered directly without routing.
    """
    names = [c['name'] for c in calls]
    if not names:
        return {
            "pass": True,
            "score": 1.0,
            "reason": "No tool call - correct for a simple direct query"
        }
    escalated = [n for n in names if re.search(r'escalate|support_agent', n, re.IGNORECASE)]
    return {
        "pass": not escalated,
        "score": 0.0 if escalated else 1.0,
        "reason": (
            f"Tool(s) {escalated} triggered unnecessary escalation"
            if escalated
            else f"Tool(s) {names} are not escalation tools"
        )
    }


def _check_not_approved(output: str) -> dict:
    """
    Pass if output does NOT contain 'is/has been/was/are approved'.
    Allows 'not approved' or 'NOT approved' to pass correctly.
    FIX C3: replaces the old `not-contains: approved` which blocked valid negated phrases.
    """
    matched = bool(
        re.search(r'\b(is|has been|was|are)\s+approved\b', output, re.IGNORECASE)
    )
    passed = not matched
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (
            "No approval phrase found in output"
            if passed
            else "Output contains approval phrase ('is/was/are approved')"
        )
    }


def _check_contains_all(output: str, vars_: dict) -> dict:
    """
    Pass if ALL required strings are present in the output.
    var: _required_strings - comma-separated list of required strings
    """
    required = [s.strip() for s in vars_.get('_required_strings', '').split(',') if s.strip()]
    if not required:
        return {"pass": False, "score": 0.0, "reason": "_required_strings is empty"}

    missing = [s for s in required if s not in output]
    passed = len(missing) == 0
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (
            f"All required strings found: {required}"
            if passed
            else f"Missing from output: {missing}"
        )
    }


def _check_no_tool_call(calls: list) -> dict:
    """
    Pass if output contains no tool calls at all.
    Correct behaviour for general product questions that should be answered directly.
    """
    names = [c['name'] for c in calls]
    return {
        "pass": not names,
        "score": 0.0 if names else 1.0,
        "reason": (
            f"Unexpected tool call(s) found in output: {names}"
            if names
            else "No tool call - correct for a general query"
        )
    }


def _check_tool_schema(calls: list) -> dict:
    """
    Pass if every tool call is a known tool and its arguments satisfy that tool's
    JSON schema in schemas/agent_tools.json. Fails if there are no tool calls.
    var: _validate_schema = "true"
    """
    try:
        schemas = _load_tool_schemas()
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"pass": False, "score": 0.0,
                "reason": f"Cannot load tool schemas from {TOOLS_SCHEMA_PATH}: {exc}"}

    if not calls:
        return {"pass": False, "score": 0.0,
                "reason": "_validate_schema: no tool calls found in output"}

    errors = []
    for c in calls:
        if c['name'] not in schemas:
            errors.append(f"{c['name']}: unknown tool (not in agent_tools.json)")
        else:
            errors += _schema_errors(c['args'], schemas[c['name']], c['name'])
    passed = not errors
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (
            f"{len(calls)} tool call(s) match schema: {[c['name'] for c in calls]}"
            if passed
            else "Schema violations: " + "; ".join(errors)
        )
    }
