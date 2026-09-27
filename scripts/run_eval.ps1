# run_eval.ps1 — Run a Promptfoo evaluation with environment-specific settings (Windows).
# Author: Venkateshwara Doijode
#
# Usage:
#   .\scripts\run_eval.ps1 -Env dev -Config configs\claude.yaml -TestFile testcases\loan_assistant.yaml
#   .\scripts\run_eval.ps1 -Env dev -Config configs\claude.yaml -TestFile testcases\loan_assistant.yaml,testcases\fraud_assistant.yaml
#   .\scripts\run_eval.ps1 -Env uat -Config configs\claude.yaml -TestFile assertions\regression.yaml -Threshold 0.8
#
# Parameters:
#   -Env          dev | uat | prod
#   -Config       Path to provider config YAML
#   -TestFile     One or more test files (comma-separated for multiple)
#   -Threshold    Fail threshold 0-1.0 (optional, overrides env default)
#   -Repeat       Repeat count (optional, overrides env default)
#   -Concurrency  Max parallel API calls (optional)
#   -Filter       Run only test cases matching this pattern/regex (optional)
#   -Delay        Delay in ms between API calls (avoids rate limits optional)
#   -FailingOnly  Re-run only previously failed test cases (optional switch)

param(
    [Parameter(Mandatory)][string]$Env,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string[]]$TestFile,
    [string]$Threshold,
    [string]$Repeat,
    [string]$Concurrency,
    [string]$Filter,
    [string]$Delay,
    [switch]$FailingOnly
)

$EnvFile = "environments\$Env.env"

if (-not (Test-Path $EnvFile)) {
    Write-Error "[ERROR] Environment file not found: $EnvFile"
    exit 1
}

# Load environment variables from the .env file.
# The value regex strips trailing inline comments (KEY=value # comment → value)
# so a developer can annotate env files without corrupting loaded values.
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match "^\s*([^#\s][^=]*?)\s*=\s*(.+)\s*$") {
        $val = ($matches[2] -split '\s#')[0].Trim()
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $val, "Process")
    }
}

Write-Host "[INFO] Loaded environment: $EnvFile"

# Use arg overrides or fall back to env file values (both must be set in the env file)
$FailThreshold = if ($Threshold) { $Threshold } else { $env:FAIL_THRESHOLD }
$RepeatCount   = if ($Repeat)    { $Repeat }    else { $env:DEFAULT_REPEAT }
$OutputBase    = if ($env:OUTPUT_DIR) { $env:OUTPUT_DIR } else { "reports\json" }   # ?? requires PS 7.1

# Validate required values are present — fail loudly rather than silently
if (-not $FailThreshold) {
    Write-Error "[ERROR] FAIL_THRESHOLD is not set. Define it in $EnvFile or pass -Threshold."
    exit 1
}
if (-not $RepeatCount) {
    Write-Error "[ERROR] DEFAULT_REPEAT is not set. Define it in $EnvFile or pass -Repeat."
    exit 1
}

# Build timestamped output filename — use first file name, or "combined" for multiple
$TestName = if ($TestFile.Count -eq 1) {
    [System.IO.Path]::GetFileNameWithoutExtension($TestFile[0])
} else {
    "combined"
}
$Timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputFile = "$OutputBase\${TestName}_${Env}_${Timestamp}.json"

New-Item -ItemType Directory -Force -Path $OutputBase | Out-Null

# Build the promptfoo argument list as an array.
# Using & promptfoo @PromptfooArgs instead of Invoke-Expression eliminates
# command-injection risk: paths with spaces are passed as single tokens, and
# metacharacters (;, &, |) inside argument values are never interpreted by the shell.
$PromptfooArgs = @(
    "eval",
    "--config", $Config,
    "--output", $OutputFile,
    "--fail-threshold", $FailThreshold,
    "--no-cache"
)

foreach ($f in $TestFile) {
    $PromptfooArgs += "--tests", $f
}

# RepeatCount validation: TryParse protects against non-numeric strings that
# would throw an InvalidCastException even with the short-circuit -and guard.
$repeatInt = 0
if ($RepeatCount -and [int]::TryParse($RepeatCount, [ref]$repeatInt) -and $repeatInt -gt 1) {
    $PromptfooArgs += "--repeat", $RepeatCount
}

if ($Concurrency) {
    $PromptfooArgs += "--max-concurrency", $Concurrency
}

if ($Filter) {
    $PromptfooArgs += "--filter-pattern", $Filter
}

if ($Delay) {
    $PromptfooArgs += "--delay", $Delay
}

if ($FailingOnly) {
    $PromptfooArgs += "--filter-failing"
}

Write-Host "[INFO] Running: promptfoo $($PromptfooArgs -join ' ')"
& promptfoo @PromptfooArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "[PASS] Eval passed. Results: $OutputFile"
} else {
    Write-Error "[FAIL] Eval failed. Results: $OutputFile"
    exit $LASTEXITCODE
}
