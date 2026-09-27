#!/usr/bin/env bash
# run_eval.sh — Run a Promptfoo evaluation with environment-specific settings.
# Author: Venkateshwara Doijode
#
# Usage:
#   ./scripts/run_eval.sh <env> <config> <testfile(s)> [threshold] [repeat] [concurrency] [filter] [delay] [--failing-only]
#
# Arguments:
#   env            dev | uat | prod
#   config         Path to provider config  e.g. configs/claude.yaml
#   testfile(s)    One or more test files (YAML, CSV, JSON or XLSX)
#                    Single:    testcases/loan_assistant.yaml
#                    Multiple:  testcases/loan_assistant.yaml,assertions/regression.yaml  (comma-separated, no spaces)
#
#   threshold      Fail threshold 0.0-1.0 (optional, overrides env default)
#   repeat         Repeat count (optional, overrides env default)
#   concurrency    Max parallel API calls (optional)
#   filter         Run only test cases matching this pattern/regex (optional, use "" to skip)
#   delay          Delay in ms between API calls — avoids rate limits (optional)
#   --failing-only Re-run only previously failed test cases (optional flag)
#
# Examples:
#   ./scripts/run_eval.sh dev configs/claude.yaml testcases/loan_assistant.yaml
#   ./scripts/run_eval.sh dev configs/claude.yaml testcases/loan_assistant.yaml,assertions/regression.yaml
#   ./scripts/run_eval.sh uat configs/claude.yaml compliance/business_rules.yaml
#   ./scripts/run_eval.sh prod configs/claude.yaml testcases/loan_assistant.yaml 0.9 5
#   ./scripts/run_eval.sh dev configs/claude.yaml testcases/loan_assistant.yaml 0.8 1 10
#   ./scripts/run_eval.sh dev configs/claude.yaml testcases/loan_assistant.yaml 0.8 1 4 "approval" 500
#   ./scripts/run_eval.sh dev configs/claude.yaml testcases/loan_assistant.yaml 0.8 1 4 "" 0 --failing-only

set -euo pipefail

ENV=${1:?"Usage: $0 <env> <config> <testfile(s)> [threshold] [repeat] [concurrency] [filter] [delay] [--failing-only]"}
CONFIG=${2:?"Usage: $0 <env> <config> <testfile(s)> [threshold] [repeat] [concurrency] [filter] [delay] [--failing-only]"}
TEST_FILES_RAW=${3:?"Usage: $0 <env> <config> <testfile(s)> [threshold] [repeat] [concurrency] [filter] [delay] [--failing-only]"}
THRESHOLD_ARG=${4:-}
REPEAT_ARG=${5:-}
CONCURRENCY_ARG=${6:-}
FILTER_ARG=${7:-}
DELAY_ARG=${8:-}
FAILING_ONLY=${9:-}

ENV_FILE="environments/${ENV}.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] Environment file not found: $ENV_FILE"
  exit 1
fi

# Load environment variables from the env file
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

echo "[INFO] Loaded environment: $ENV_FILE"

# Validate required env vars are present after sourcing (with a clear error message)
: "${FAIL_THRESHOLD:?FAIL_THRESHOLD must be defined in $ENV_FILE}"
: "${DEFAULT_REPEAT:?DEFAULT_REPEAT must be defined in $ENV_FILE}"

# Use arg overrides or fall back to env file values
THRESHOLD=${THRESHOLD_ARG:-${FAIL_THRESHOLD}}
REPEAT=${REPEAT_ARG:-${DEFAULT_REPEAT}}
OUTPUT_BASE=${OUTPUT_DIR:-reports/json}

# Validate REPEAT is a non-negative integer before it reaches the arithmetic comparison.
# A non-integer value (e.g. "1.0" or "twice") causes an opaque bash arithmetic error.
if ! [[ "$REPEAT" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] REPEAT must be a positive integer, got: '$REPEAT'"
  echo "  Set DEFAULT_REPEAT in $ENV_FILE or pass an integer as argument 5."
  exit 1
fi

# Split comma-separated test files into an array
IFS=',' read -ra TEST_FILES <<< "$TEST_FILES_RAW"

# Build timestamped output filename — first file name, or "combined" for multiple
if [[ ${#TEST_FILES[@]} -eq 1 ]]; then
  TEST_NAME=$(basename "${TEST_FILES[0]}" | sed 's/\.[^.]*$//')
else
  TEST_NAME="combined"
fi
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT="${OUTPUT_BASE}/${TEST_NAME}_${ENV}_${TIMESTAMP}.json"

mkdir -p "$OUTPUT_BASE"

# Build command as an array to avoid eval and shell-injection risk.
CMD_ARGS=(
  promptfoo eval
  --config "$CONFIG"
  --output "$OUTPUT"
  --fail-threshold "$THRESHOLD"
  --no-cache
)

for f in "${TEST_FILES[@]}"; do
  CMD_ARGS+=(--tests "$f")
done

if [[ "$REPEAT" -gt 1 ]]; then
  CMD_ARGS+=(--repeat "$REPEAT")
fi

if [[ -n "$CONCURRENCY_ARG" ]]; then
  CMD_ARGS+=(--max-concurrency "$CONCURRENCY_ARG")
fi

if [[ -n "$FILTER_ARG" ]]; then
  CMD_ARGS+=(--filter-pattern "$FILTER_ARG")
fi

if [[ -n "$DELAY_ARG" ]]; then
  CMD_ARGS+=(--delay "$DELAY_ARG")
fi

if [[ "$FAILING_ONLY" == "--failing-only" ]]; then
  CMD_ARGS+=(--filter-failing)
fi

echo "[INFO] Running: ${CMD_ARGS[*]}"
# Temporarily suspend set -e so the exit code is captured before the script
# exits. Without this, a non-zero promptfoo exit triggers set -e immediately
# and the [FAIL] message (which prints the output file path) is never reached.
set +e
"${CMD_ARGS[@]}"
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 0 ]]; then
  echo "[PASS] Eval passed. Results: $OUTPUT"
else
  echo "[FAIL] Eval failed. Results: $OUTPUT"
  exit $EXIT_CODE
fi
