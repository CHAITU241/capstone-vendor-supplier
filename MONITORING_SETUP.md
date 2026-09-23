# Monitoring and AI Quality Runbook

Start the FastAPI backend before running any of these tools.

## 1. Langfuse — AI tracing

1. Create a Langfuse project and copy its public key, secret key, host, and dashboard URL into `backend/.env`.
2. Set `LANGFUSE_RELEASE` to the deployed Git commit or submission tag. Keep `LANGFUSE_CAPTURE_CONTENT=false`; VendorLens sends operational metadata, not supplier document text.
3. Start the backend normally and sign in through **Administrator** on the landing page.
4. Open **AI observability** to verify that AI and Langfuse configuration are ready.
5. Process a document, ask a supplier question, ask the reviewer assistant, and validate an ERP record.
6. Use **Open Langfuse** from the admin portal to inspect the correlated traces, models, tokens, latency, scores, and errors.

Langfuse tracing is passive; no separate local server is required. Telemetry failures never block onboarding. Supplier IDs are hashed for grouping, filenames are excluded, and OpenRouter model names are normalized for Langfuse pricing lookup while the full provider model remains metadata.

### Recommended `VendorLens AI Operations` dashboard

Create these widgets in Langfuse after the first live run:

- Total generations, input/output tokens, and model cost.
- P50/P95 latency grouped by observation name.
- Calls and errors grouped by model and feature.
- Tokens/cost grouped by model and prompt version.
- `processing_success`, `document_success_rate`, `grounding_guard`, `citation_guard`, `text_extraction_success`, and `tool_success` scores.
- Traces grouped by release and filtered to the current submission tag.

Expected trace families are `document.text_extraction`, `supplier.document.processing`, `supplier.document.rag`, `supplier.assistant.conversation`, `reviewer.assistant.conversation`, and `erp.mcp.*`. Extraction, embedding, and answer generations appear as children where the workflow performs them.

If cost is blank, confirm that the normalized model name matches a Langfuse model definition. Add a project model definition for the OpenRouter price if necessary; token tracking does not depend on price configuration.

## 2. Promptfoo — answer evaluation

1. Install or run the CLI without admin rights:

   ```powershell
   npx promptfoo@latest --version
   ```

2. From the directory containing `promptfooconfig.yaml`, run:

   ```powershell
    PROMPTFOO_BASE_URL=http://localhost:8000 npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache -o results/latest.json
    
   npx promptfoo view
   ```

3. Open the local Promptfoo URL shown in the terminal. Review grounding, citations, supplier isolation, not-found behavior, and failures.

The backend and its AI environment variables must be available while the evaluation runs.

## 3. Prometheus — application health

1. Download the Prometheus binary and keep it in a user-writable folder.
2. From the folder containing both `prometheus.exe` and `prometheus.yml`, start it with:

   ```powershell
   .\prometheus.exe --config.file=.\prometheus.yml
   ```

3. Open `http://localhost:9090`.
4. Generate traffic in VendorLens, then query `up` and metrics beginning with `vendorlens_`.

Prometheus scrapes the FastAPI `/metrics` endpoint. Use it to inspect request counts, errors, latency, AI calls, and dependency health.

## Suggested order

Start the backend, verify the admin AI-observability page, exercise the application, inspect Langfuse traces, then use Prometheus for runtime health and Promptfoo for the deterministic quality gate.
