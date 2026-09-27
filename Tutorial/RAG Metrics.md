# RAG Metrics in Promptfoo

RAG (Retrieval-Augmented Generation) passes retrieved documents to the LLM alongside the user's question. The model must
answer using only the retrieved context — not its training data.

```text
User question → Retrieve context → LLM prompt (context + question) → Grounded answer
```

The retrieved context is passed as a variable and injected into the prompt:

```yaml
prompts:
  - |
    Use only the following context to answer the question.
    Context: {{context}}
    Question: {{question}}

providers:
  - id: openai:gpt-4o
    config:
      temperature: 0
      seed: 42

tests:
  - file://tests/rag-test-cases.yaml
```

---

## RAG Metrics

### Context Relevance

Was the right document retrieved for the question?

```yaml
- description: "Retrieved context matches the question topic"
  vars:
    question: "What is the maximum tenure for a home loan?"
    context: |
      SecureBank Home Loan Terms: Home loans are available for 5 to 30 years.
      The maximum tenure is 30 years for applicants below 40 years of age.
  assert:
    - type: context-relevance
      # PASS: context is about home loan tenure
      # FAIL: context is about personal loan terms (wrong document retrieved)
```

---

### Faithfulness

Are all claims in the answer supported by the retrieved context?

```yaml
- description: "Answer does not add facts outside the context"
  vars:
    question: "What documents are required for a personal loan?"
    context: |
      Required: Government-issued photo ID, last 3 months salary slips,
      last 6 months bank statements, and address proof.
  assert:
    - type: context-faithfulness
      # PASS: "You need a photo ID, salary slips, bank statements, and address proof."
      # FAIL: "You also need your PAN card and a credit report." (not in context)
```

---

### Groundedness

Stricter than faithfulness — every fact must have an explicit source in the context. The model must not add plausible but
unverified information.

```yaml
- description: "Answer is fully grounded in retrieved context"
  vars:
    question: "What is the processing fee for a personal loan?"
    context: |
      A one-time processing fee of 1.5% of the loan amount is charged at disbursement.
      No hidden charges apply.
  assert:
    - type: llm-rubric
      value: "The answer must only contain facts explicitly stated in the context.
             No fees or policies outside the context are permitted."
      # PASS: "The processing fee is 1.5%, charged at disbursement."
      # FAIL: "The processing fee is 1.5%, plus stamp duty may apply." (stamp duty not in context)
    - type: context-faithfulness
```

### Answer Relevance

Does the answer actually address the user's question?

```yaml
- description: "Answer addresses the question asked"
  vars:
    question: "Can I prepay my home loan without a penalty?"
    context: |
      Floating rate customers may prepay at any time without penalty.
      Fixed rate loans attract a 2% prepayment fee.
  assert:
    - type: answer-relevance
      # PASS: "Yes, no penalty applies if you are on a floating rate."
      # FAIL: "Please visit your nearest branch for details." (deflects, not relevant)
```

### Retrieval Quality

Combines relevance (right document?) and recall (enough information?) to assess the full retrieval step.

```yaml
- description: "Retrieval quality — home loan tenure"
  vars:
    question: "What is the maximum tenure for a home loan at SecureBank?"
    context: |
      Home loans are available for 5 to 30 years.
      The maximum tenure is 30 years for applicants below 40 years of age.
  assert:
    - type: context-relevance
      # PASS: correct document retrieved
      # FAIL: personal loan document returned instead
    - type: context-recall
      # PASS: context contains the 30-year limit and age condition
      # FAIL: context only says "tenures are flexible" — insufficient
```

### Citation Accuracy

Does the model correctly attribute its answer to the source document?

```yaml
- description: "Model cites the correct policy document"
  vars:
    question: "What is the prepayment fee for a fixed rate home loan?"
    context: |
      Source: SecureBank Home Loan Policy v3.2 (March 2025)
      Fixed rate loans attract a prepayment penalty of 2% of the outstanding principal.
  assert:
    - type: llm-rubric
      value: "The response must reference 'SecureBank Home Loan Policy' as its source."
      # PASS: "According to the SecureBank Home Loan Policy, the fee is 2%."
      # FAIL: "Based on RBI guidelines, the fee is 2%." (wrong source)
      # FAIL: "The prepayment fee is 2%." (no citation)
    - type: javascript
      value: "/SecureBank Home Loan Policy/i.test(output)"
    - type: contains
      value: "2%"
```

---

### Factuality

Is the answer factually consistent with a known reference answer?

```yaml
- description: "Home loan rate is factually correct"
  vars:
    question: "What is the starting interest rate for a home loan?"
    context: |
      Home loan rates start from 8.5% p.a. for salaried customers with credit score above 750.
  assert:
    - type: factuality
      value: "The starting rate is 8.5% per annum for eligible salaried customers."
      # PASS: "Home loans start at 8.5% p.a. for eligible applicants."
      # FAIL: "Home loans start at 8.0% per annum." (wrong rate)
```

---

## All Together

```yaml
- description: "Full RAG validation — personal loan documents"
  vars:
    question: "What documents do I need for a personal loan?"
    context: |
      Required: Government-issued photo ID, last 3 months salary slips,
      last 6 months bank statements, and address proof.
  assert:
    - type: context-relevance
    - type: context-recall
    - type: context-faithfulness
    - type: answer-relevance
    - type: factuality
      value: "Required documents include a photo ID, salary slips, bank statements, and address proof."
    - type: not-contains
      value: "I don't have access to"
```

## Limitations

| Limitation | Alternative |
|------------|-------------|
| Retrieval latency | APM tools (Datadog, OpenTelemetry) |
| Vector embedding quality | Embedding benchmarks (MTEB) |
| Document ranking | Test retrieval layer separately |
| Native vector DB integration | Pass retrieved context via `vars` |

## Run

```bash
promptfoo eval --config promptfooconfig.yaml \
  --output results/rag-eval.json \
  --fail-threshold 0.85
```
