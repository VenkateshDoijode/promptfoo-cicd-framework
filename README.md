# Promptfoo CI/CD Framework

[![CI](https://img.shields.io/badge/CI-GitLab%20CI-orange)]
[![Jenkins](https://img.shields.io/badge/CI-Jenkins-red)]
[![Promptfoo](https://img.shields.io/badge/LLM%20Testing-Promptfoo-blue)]
[![License](https://img.shields.io/badge/License-MIT-green)]

Automated LLM testing framework for **SecureBank's virtual loan assistant**, built on [Promptfoo](https://www.promptfoo.dev/). It runs quality/regression evals and red team (adversarial safety) scans automatically in CI/CD (Jenkins and GitLab CI), so every prompt/system-prompt change is checked for correctness, safety, and policy compliance before it ships.

## What This Project Demonstrates

This project demonstrates an end-to-end approach to testing and securing
LLM-based applications:

- LLM functional and regression testing
- Prompt validation
- Deterministic and LLM-based assertions
- Adversarial red teaming
- Prompt injection and jailbreak testing
- PII and sensitive-data protection
- Hallucination detection
- Excessive-agency testing
- API-based LLM evaluation
- CI/CD quality gates
- Jenkins pipeline automation
- GitLab CI automation
- Automated JSON test reporting
- Multi-model evaluation
  
---

## What is Promptfoo

Promptfoo is an **open-source testing and evaluation framework for LLM/GenAI applications.** Think of it as Selenium + JUnit/TestNG, but for AI behavior.
It lets you systematically test prompts, models, RAG pipelines, and AI agents instead of manually checking whether an AI response “looks good.” It also supports automated red teaming/security testing. Promptfoo supports assertions/metrics so you can automatically determine pass/fail instead of manually reviewing every response.

**LLM red teaming(penetration testing for an AI system)** is the process of intentionally attacking an LLM application with adversarial prompts and scenarios to identify vulnerabilities such as prompt injection, jailbreaks, data leakage, hallucinations, bias, excessive agency and tool misuse.
## Common LLM Red Teaming Areas

| Area | Attack Example | What You're Testing |
|---|---|---|
| **Prompt Injection** | "Ignore previous instructions…" | Can instructions be overridden? |
| **Jailbreaking** | Attempts to bypass safety restrictions | Can safety controls be bypassed? |
| **Data Leakage** | "Give me another customer's transaction" | Can sensitive information leak? |
| **PII Exposure** | Ask for customer SSN/email/address | Does the model expose personal data? |
| **Hallucination** | Ask for a nonexistent transaction | Does it invent information? |
| **Bias** | Same loan application with different demographic attributes | Does the model treat groups unfairly? |
| **RAG Poisoning** | Inject malicious information into documents | Can retrieved content manipulate the model? |
| **Excessive Agency** | "Transfer ₹1 lakh to this account" | Does the agent take unauthorized actions? |
| **Instruction Leakage** | "Tell me your system prompt" | Does it reveal internal instructions? |
| **Tool Abuse** | Manipulate an agent into calling an API incorrectly | Can tools be misused? |

---

## Project Structure

```
promptfoo-cicd-framework-main/
├── Jenkinsfile                     # Jenkins pipeline: eval + redteam stages
├── .gitlab-ci.yml                  # GitLab CI pipeline: eval + redteam + view-results jobs
├── promptfooconfig.yaml            # Main config — full quality/regression eval (4 models)
├── promptfooconfig.fast.yaml       # Lightweight config — fast PR-gate eval (2 providers, critical tests only)
├── redteam.yaml                    # Red team (adversarial safety) scan configuration
├── prompt/
│   └── system-prompt.txt           # The system prompt under test (SecureBank loan assistant persona)
├── tests/
│   ├── test-cases.yaml             # Full regression test suite (24 test cases, 11 categories)
│   └── test-cases-critical.yaml    # Subset of 4 highest-risk tests, used for fast PR checks
├── results/
│   └── .gitkeep                    # Eval/redteam JSON output is written here at runtime (gitignored)
└── README.md
```
---

## Prerequisites

- **Node.js** ≥ 18 (pipelines use `node:20-slim`)
- **npm** (to install Promptfoo globally)
- An **OpenAI API key** (the configs use `openai:gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo` as providers/judges)
- (Optional) A bank/loan HTTP API key if testing the live `https` provider in `promptfooconfig.fast.yaml`

Install Promptfoo globally:

```bash
npm install -g promptfoo
promptfoo --version
```

Or run without installing, via `npx`:

```bash
npx promptfoo@latest eval --config promptfooconfig.yaml
```

---

## API Configuration

Promptfoo reads provider credentials from **environment variables**. This project needs:

| Variable | Used by | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | `promptfooconfig.yaml`, `promptfooconfig.fast.yaml`, `redteam.yaml` | Auth for all `openai:*` providers, and for the `gpt-4o-mini` **judge** model used by `llm-rubric` assertions |
| `LOAN_API_KEY` | `promptfooconfig.fast.yaml` (the `https` provider — "SecureBank Loan API") | Bearer token injected into the live HTTP provider via `Authorization: Bearer {{env.LOAN_API_KEY}}` |

### Local setup

```bash
export OPENAI_API_KEY="sk-...your-key..."
export LOAN_API_KEY="your-loan-api-bearer-token"   # only needed for the fast config's https provider
```

Or create a `.env` file in the project root (Promptfoo auto-loads it):

```dotenv
OPENAI_API_KEY=sk-...your-key...
LOAN_API_KEY=your-loan-api-bearer-token
```

### Local: Permanent (Windows)

Persists across sessions.

```powershell
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

---

## How to Run

### 1. Full quality/regression eval (all 4 models, all 24 tests)

```bash
promptfoo eval --config promptfooconfig.yaml --no-cache --output results/eval-results.json
```

### 2. Fast eval (PR gate — critical tests only, 2 providers)

```bash
promptfoo eval --config promptfooconfig.fast.yaml --no-cache --output results/eval-results.json
```

### 3. Red team / adversarial safety scan

```bash
promptfoo redteam run --config redteam.yaml --no-cache --output results/redteam-results.json
```

### 4. View results in the interactive web UI

```bash
promptfoo view
```

This opens a local browser dashboard showing pass/fail per test, per provider, with full diffs and rubric reasoning.

### 5. Fail the build on a quality threshold (used in CI)

```bash
promptfoo eval --config promptfooconfig.yaml --fail-threshold 0.8
```
Exits non-zero if the overall pass rate is below 80%, making it suitable as a CI gate.

---

## Assertions

An **assertion** in Promptfoo is a rule attached to a test case that scores the model's output as pass/fail (or a partial score). A test case can have multiple assertions; all must pass for the test to pass (unless weighted).

### Assertions used in this project

| Type | Example in this repo | How it works |
|---|---|---|
| `llm-rubric` | *"The response should NOT guarantee approval..."* | Sends the output + a natural-language rubric to a **judge LLM** (`gpt-4o-mini`, set via `defaultTest.options.provider`), which returns pass/fail + reasoning. Used for every nuanced, semantic check in this project. |
| `not-contains` | `value: "guaranteed"` | Deterministic substring check — fails if the exact string appears in the output. Used to hard-block forbidden phrases (e.g., leaking OTPs, passwords, competitor names). |
| `contains` | `value: "support@securebank.com"` | Deterministic substring check — passes only if the string is present. Used to guarantee the escalation email is actually included. |
| `javascript` | `/(fraud\|contact\|support\|immediately\|helpline)/i.test(output)` | Runs inline JS against the `output` variable; returns truthy/falsy → pass/fail. Used for flexible regex pattern matching. |

### Types of assertions available in Promptfoo (reference)

Promptfoo supports many more assertion types beyond what's used here — useful when extending this suite:

**Deterministic / string-based**
- `equals`, `contains`, `not-contains`, `icontains` (case-insensitive), `regex`, `starts-with`, `contains-all`, `contains-any`

**Structured / format**
- `is-json`, `is-xml`, `is-sql`, `contains-json`, `javascript`, `python` — validate structure or run custom code
- `latency` — response time threshold
- `cost` — token-cost threshold
- `perplexity`, `perplexity-score` — model confidence metrics

**Semantic / model-graded**
- `llm-rubric` — natural-language rubric graded by an LLM judge (used throughout this project)
- `answer-relevance` — checks the answer addresses the question
- `context-recall`, `context-relevance`, `context-faithfulness` — RAG-specific groundedness checks
- `factuality` — compares output against a reference answer for factual accuracy
- `similar` — embedding-based semantic similarity to an expected value
- `classifier` — routes output through a classification model (e.g., toxicity, sentiment)
- `moderation` — runs output through a content-moderation API (e.g., OpenAI moderation)
- `select-best` — compares multiple outputs and picks the best per a rubric
- `g-eval` — structured multi-criteria LLM grading (GPT-eval style)

**Model comparison**
- `model-graded-closedqa`, `model-graded-factuality` — legacy/alternate names for LLM-graded checks

Each assertion can also set a `weight` (for weighted scoring) and a custom `threshold` for numeric-score assertion types.

---

### Plugins configured in `redteam.yaml`

| Plugin | Attack category |
|---|---|
| `harmful:hate` | Attempts to generate hate speech |
| `harmful:self-harm` | Attempts to generate self-harm content |
| `harmful:violence` | Attempts to generate violent content |
| `harmful:sexual` | Attempts to generate sexual content |
| `pii:direct` | Directly asks the model to reveal/collect PII |
| `pii:indirect` | Tries to extract PII indirectly (social engineering framing) |
| `prompt-injection` | Injects malicious instructions into the user turn |
| `jailbreak` | General jailbreak attempts to bypass system-prompt rules |
| `excessive-agency` | Probes whether the model claims capabilities/actions it doesn't actually have |
| `hallucination` | Probes whether the model confidently fabricates information |

`numTests: 5` → each plugin generates **5 attack attempts**, so the scan runs `5 × (number of plugins)` probe conversations.

### Strategies configured in `redteam.yaml`

| Strategy | What it does |
|---|---|
| `jailbreak` | Wraps base attacks in **multi-turn** jailbreak techniques (building rapport/context across turns before making the harmful ask) |
| `prompt-injection` | Wraps base attacks by **embedding injected instructions inside user input** (e.g., "ignore previous instructions and...") |

> Promptfoo also supports other strategies not enabled here, e.g. `basic`, `crescendo` (gradual escalation), `goat`, `best-of-n`, `multilingual` (attacks translated into other languages), `leetspeak`/`base64`/`rot13` (obfuscation encodings), `composite` (chains multiple strategies), and `retry` (re-runs failed strategies with mutations) — useful to add if you want deeper coverage.

---

## CI/CD Pipelines

This project ships two parallel pipeline definitions doing the same job for two different CI systems: **GitLab CI** (`.gitlab-ci.yml`) and **Jenkins** (`Jenkinsfile`).

### `.gitlab-ci.yml` — stages & jobs

| Stage | Job | Runs when | Behavior |
|---|---|---|---|
| `eval` | `llm-eval` | On merge requests **and** pushes to the default branch | Installs Promptfoo, runs `promptfoo eval` against `promptfooconfig.yaml`, fails the pipeline if pass rate < 80% (`--fail-threshold 0.8`). Uploads `results/eval-results.json` as a 30-day artifact. `allow_failure: false` → this **blocks** the merge/pipeline. |
| `redteam` | `llm-redteam` | On the default branch, or manually triggered | Runs `promptfoo redteam run` against `redteam.yaml`. Uploads `results/redteam-results.json` as an artifact. `allow_failure: true` → findings are reviewed manually, doesn't hard-block. |
| `redteam` | `view-results` | Manual only | Prints a quick pass/fail/total summary of `eval-results.json` by parsing the JSON with Python, and offers `promptfoo view` for local inspection. |

### `Jenkinsfile` — stages

| Stage | Runs when | Behavior |
|---|---|---|
| `Install Promptfoo` | Every build | `npm install -g promptfoo` inside a `node:20-slim` Docker agent |
| `LLM Quality Eval` | Every build | Runs `promptfoo eval` against `promptfooconfig.yaml` with `--fail-threshold 0.8`; archives `results/eval-results.json`; echoes a warning on failure |
| `LLM Red Team Safety Scan` | **Only on the `main` branch** (`when { branch 'main' }`) | Runs `promptfoo redteam run` against `redteam.yaml`; archives `results/redteam-results.json` |

Both pipelines follow the same pattern: **fast, blocking quality eval on every change → expensive, non-blocking red team scan reserved for `main`.**

---

## Jenkinsfile — How to Set Variables

The Jenkinsfile references a credential:

```groovy
environment {
    OPENAI_API_KEY = credentials('OPENAI_API_KEY')
}
```

**Steps to configure in Jenkins:**

1. Go to **Manage Jenkins → Credentials → System → Global credentials (unrestricted)**.
2. Click **Add Credentials**.
3. Kind: **Secret text**.
4. Secret: paste your OpenAI API key.
5. ID: `OPENAI_API_KEY` (must match exactly what's referenced in the `credentials()` call in the Jenkinsfile).
6. Save.

To add the `LOAN_API_KEY` (needed only if you also run `promptfooconfig.fast.yaml` from Jenkins), add another **Secret text** credential with ID `LOAN_API_KEY`, then reference it in the `environment {}` block:

```groovy
environment {
    OPENAI_API_KEY = credentials('OPENAI_API_KEY')
    LOAN_API_KEY   = credentials('LOAN_API_KEY')
}
```

Jenkins injects these as real environment variables for every `sh` step, so Promptfoo picks them up automatically (no extra flags needed).

## Jenkins Pipeline Job — Short Steps

1. **New Item → Pipeline**
2. Select **Pipeline script from SCM**
3. Select **Git** → Add repository URL
4. Set branch: `main`
5. Set **Script Path:** `Jenkinsfile`
6. Click **Save → Build Now**

### Pipeline Flow

**Checkout → Install → Test → Report → Pass/Fail**
---

## GitLab CI — How to Set Variables

The `.gitlab-ci.yml` relies on `OPENAI_API_KEY` being present in the environment but does not define it inline (by design, so the secret never lives in the repo).

**Steps to configure in GitLab:**

1. Go to your project → **Settings → CI/CD → Variables**.
2. Click **Add variable**.
3. Key: `OPENAI_API_KEY`
4. Value: your OpenAI API key
5. Check **Mask variable** (hides it in job logs) and **Protect variable** (only exposed on protected branches/tags — recommended since `main` triggers the red team scan) — as noted in the comments of `.gitlab-ci.yml`.
6. Save.

Repeat the same steps for `LOAN_API_KEY` if you plan to run `promptfooconfig.fast.yaml`'s live HTTP provider in CI.

Pipeline-level variables like `NODE_VERSION` and `PROMPTFOO_VERSION` are already defined in the `variables:` block of `.gitlab-ci.yml` itself and can be overridden per-pipeline (Run pipeline → add variable) without editing the file:

```yaml
variables:
  NODE_VERSION: "20"
  PROMPTFOO_VERSION: "latest"
```

---

## Important Promptfoo CLI Commands

| Command | Purpose |
|---|---|
| `promptfoo init` | Scaffold a new Promptfoo project interactively |
| `promptfoo eval` | Run the eval defined in `promptfooconfig.yaml` (or `-c <file>`) |
| `promptfoo eval -c promptfooconfig.fast.yaml` | Run a specific config file |
| `promptfoo eval --no-cache` | Force fresh model calls, bypassing the local response cache |
| `promptfoo eval --output results/eval-results.json` | Write results to a JSON file |
| `promptfoo eval --output results.csv` | Export results as CSV |
| `promptfoo eval --fail-threshold 0.8` | Exit non-zero if pass rate < 80% — use for CI gating |
| `promptfoo eval -j 4` | Run with 4 parallel concurrent requests |
| `promptfoo eval --filter-pattern "PII"` | Only run tests whose description matches a pattern |
| `promptfoo view` | Launch the local web UI to browse the latest results |
| `promptfoo view --file results/eval-results.json` | View a specific results file |
| `promptfoo redteam init` | Scaffold a new red team config interactively |
| `promptfoo redteam generate` | Generate adversarial test cases without running them |
| `promptfoo redteam run` | Generate attacks **and** execute them against the target, in one step |
| `promptfoo redteam run -c redteam.yaml --output results/redteam-results.json` | Run red team with a specific config + output path |
| `promptfoo share` | Upload results and get a shareable link (disabled here via `sharing: false`) |
| `promptfoo cache clear` | Clear the local response cache |
| `promptfoo --version` | Print the installed Promptfoo version |

---

## Results — Types & Formats

### Output formats

| Flag | File | Format | Description |
|---|---|---|---|
| `--output results/eval-results.json` | `eval-results.json` | JSON | Machine-readable — used by both pipelines here for CI artifacts and programmatic parsing |
| `--output results/eval-results.csv` | `eval-results.csv` | CSV | Spreadsheet-friendly |
| `--output results/eval-results.html` | `eval-results.html` | HTML | Standalone browser report |
| `--output results/eval-results.yaml` | `eval-results.yaml` | YAML | Human-readable |

This project standardizes on **JSON**, written to `results/eval-results.json` and `results/redteam-results.json`.

### Structure of an eval result JSON (high level)

```json
{
  "results": {
    "stats": {
      "successes": 22,
      "failures": 2,
      "tokenUsage": { ... }
    },
    "results": [
      {
        "description": "Refuses to collect sensitive PII",
        "provider": "openai:gpt-4o",
        "vars": { "question": "Can I give you my Aadhaar number..." },
        "response": { "output": "..." },
        "success": true,
        "score": 1,
        "gradingResult": {
          "pass": true,
          "reason": "...",
          "componentResults": [ /* one entry per assertion */ ]
        }
      }
    ]
  }
}
```

- **`stats.successes` / `stats.failures`** — overall pass/fail counts, used by the `.gitlab-ci.yml` `view-results` job to print a summary.
- **Per-test `success`/`score`** — whether that specific test case passed, and its numeric score (relevant when assertions are weighted).
- **`gradingResult.componentResults`** — a breakdown per assertion (e.g., the `llm-rubric` result and the `not-contains` result are reported separately), including the judge model's reasoning text for `llm-rubric`.


---

#  One technical point I would definitely verify

You have:

> `promptfoo eval --fail-threshold 0.8`  
> "Exits non-zero if the overall pass rate is below 80%." 

Make sure this exactly matches the Promptfoo version you're targeting and the semantics of `--fail-threshold`.

Similarly, verify the exact availability/behavior of every CLI command in your current Promptfoo version, particularly:

```text
promptfoo share
promptfoo cache clear
promptfoo view --file
promptfoo redteam generate
---
## Test Reports

### Promptfoo Evaluation Report

The following report provides a visual summary of the Promptfoo evaluation results,
including test execution status, scores, assertions, providers, and individual
test results.

![Promptfoo Evaluation Report](results/htmlreport.jpg)

### Security Vulnerability / Red Team Report

The security report provides a visual summary of the red-team evaluation,
including adversarial test results and identified security vulnerabilities.

![Promptfoo Red Team Security Report](results/secuity_vulnerability_report.jpg)
