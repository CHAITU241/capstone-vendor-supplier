# VendorLens Promptfoo evaluation

This evaluation exercises the running VendorLens API, not a separate copy of
the prompts or a direct Azure OpenAI client. It therefore measures the actual
redaction boundary, ChromaDB retrieval, grounded answer prompt, citations,
global assistant prompt, API latency, and token counts.

## Prerequisites

- Node.js 20 or newer and npm/npx.
- The FastAPI backend running on `http://localhost:8000`.
- A processed supplier containing the three required documents.
- The existing Kaveri evaluation supplier, or a supplier with the same name
  and equivalent document facts.

The default RAG cases use **Kaveri Flow Controls Private Limited** because its
expected values are already versioned in
`sample_documents/evaluation_sets/evaluation_manifest.json`. To evaluate a
different supplier, replace `supplier_name` and expected values in
`promptfooconfig.yaml`, or set `PROMPTFOO_SUPPLIER_ID` and remove the
`supplier_name` values from the RAG cases.

## Run locally without admin access

From this directory, use `npx`; it downloads Promptfoo to the npm cache and
does not require a global installation:

```powershell
$env:PROMPTFOO_BASE_URL = "http://localhost:8000"
npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache -o results/latest.json
```

For a specific supplier ID:

```powershell
$env:PROMPTFOO_SUPPLIER_ID = "<processed-supplier-uuid>"
npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache -o results/latest.json
```

The first run may download the Promptfoo package. Use `npx promptfoo@latest
view` to open the local results viewer after an evaluation, or inspect the
JSON report under `evals/promptfoo/results/`.

## What is checked

### Supplier-scoped RAG

- JSON response contract and `information_found` flag.
- Expected answer terms for legal name, payment terms, and insurance expiry.
- At least one citation from an expected document for answerable questions.
- Exact guarded not-found behavior with zero citations for absent data.
- No terms from the other evaluation suppliers in the active supplier answer.
- RAG latency under the five-second demo target.

### Global onboarding assistant

- The three required uploads are stated: registration, tax, and insurance.
- The assistant explains process, human review, compliance, and approval flow.
- Sensitive credential and bank-value requests are refused without disclosure.
- Supplier-specific questions are redirected to the cited document Q&A panel.
- Assistant latency under the five-second demo target.

## Interpreting the score

Every assertion returns component scores in Promptfoo. A test passes only when
all of its deterministic checks pass. A failed case is useful evidence: open
the JSON result, inspect the returned answer/citations, and decide whether the
problem is retrieval, grounding, prompt wording, or an expected-value issue.

This is a deterministic regression suite, not a guarantee of production
quality. Add paraphrases, missing fields, expired policies, conflicting
documents, and multi-page/scanned PDFs as the evaluation corpus grows. If a
model-graded check is added later, label it probabilistic and keep these
programmatic checks as the deployment gate.

## Files

- `promptfooconfig.yaml` — providers, prompts, and nine demo cases.
- `api_provider.py` — shared HTTP provider and token/latency metadata mapping.
- `rag_provider.py` — supplier-scoped `/questions` provider entry point.
- `assistant_provider.py` — global `/assistant/chat` provider entry point.
- `assertions.py` — deterministic JSON, citation, isolation, boundary, and
  latency assertions.
- `results/` — ignored local Promptfoo output.
