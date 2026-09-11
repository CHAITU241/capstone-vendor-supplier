# Monitoring and AI Quality Runbook

Start the FastAPI backend before running any of these tools.

## 1. Langfuse — AI tracing

1. Create a free Langfuse project and copy its public key, secret key, and host into `backend/.env`.
2. Start the backend normally.
3. Use the application to process a document or ask a supplier question.
4. Open the Langfuse host and inspect the recorded generations, model, tokens, latency, and errors.

Langfuse tracing is passive; no separate local server is required.

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

Run Prometheus, start the backend, exercise the application, inspect Langfuse traces, and then run Promptfoo against the same backend.
