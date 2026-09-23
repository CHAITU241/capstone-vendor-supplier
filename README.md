# VendorLens AI

VendorLens is an AI-assisted supplier onboarding application. It turns registration, tax, and insurance documents into an auditable review workflow while keeping the final approval decision with a human reviewer.

## What it does

- Creates supplier cases and accepts one document in each required category.
- Extracts native PDF/text content and uses page-selective local Tesseract OCR for scanned PDFs, PNGs and JPEGs; records OCR provenance, redacts PII before AI calls, and stores supplier-scoped ChromaDB embeddings.
- Uses OpenRouter when configured, with Azure OpenAI as the configuration fallback, for structured extraction, embeddings, and cited document Q&A.
- Shows confidence, source pages, conflicts, compliance checks, and editable fields.
- Validates and creates supplier master records through a separate mock ERP MCP service, with idempotent retries and retrieval.

## Architecture

```text
React + Material UI
        |
     FastAPI
        |
Document text extraction -> PII redaction -> OpenRouter or Azure AI
        |                                  |
   PostgreSQL                         ChromaDB
        |                                  |
Compliance rules + audit trail -> human decision -> ERP handoff
```

## Mock ERP MCP boundary

Docker Compose runs `mock-erp-mcp` as a separate stateless JSON-RPC service. The portal invokes named MCP tools; an LLM never controls supplier creation.

- `validate_supplier_record` checks required master data, category mappings, and duplicate tax/bank references.
- `create_supplier_record` runs only after explicit reviewer approval and uses the portal supplier reference as an idempotency key.
- `get_supplier_record` and `list_supplier_records` prove that approved records are independently retrievable from the downstream supplier master.

Every call stores a sanitized tool-attempt audit with status, latency, attempt number, and error code. Raw tax and bank values are not copied into the integration audit log. If the ERP is unavailable, approval remains incomplete and the reviewer can retry safely.

The authenticated admin portal summarizes AI runs, tokens, model/prompt usage, latency, RAG grounding, OCR, and ERP tool health. Langfuse adds correlated, privacy-safe workflow traces and cost analysis; Promptfoo evaluates answer quality; Prometheus exposes application metrics.

## Run with Docker (recommended for a fresh clone)

1. Copy `backend/.env.example` to `backend/.env`.
2. Add either an OpenRouter key or the existing Azure OpenAI settings.
3. Run `docker compose up --build -d` from the repository root.
4. Open `http://localhost:5173`.

See [DOCKER_SETUP.md](DOCKER_SETUP.md) for the complete first-clone guide, verification commands, data-volume behavior, and troubleshooting.

## Run natively

1. Configure `backend/.env` with PostgreSQL and ChromaDB settings, then configure either OpenRouter or Azure OpenAI as described below.
2. Start the API: `cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.
3. Start the UI in another terminal: `cd frontend; npm run dev`.
4. Open the Vite URL shown in the terminal.

See [MONITORING_SETUP.md](MONITORING_SETUP.md) for the three monitoring and evaluation tools.

## AI provider selection

Set `OPENROUTER_API_KEY` to route document extraction, embeddings, supplier Q&A, and the general assistant through OpenRouter. OpenRouter model IDs are configured independently with `OPENROUTER_EXTRACTION_MODEL`, `OPENROUTER_ANSWER_MODEL`, and `OPENROUTER_EMBEDDING_MODEL`.

When `OPENROUTER_API_KEY` is empty or absent, the backend uses the existing Azure `OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and Azure deployment-name settings. Restart FastAPI after changing provider settings because the client is cached for the process lifetime.

Provider selection is configuration-based. A failed OpenRouter request does not retry through Azure, which prevents an outage, invalid key, or quota failure from silently sending supplier data to a different provider.

The default OpenRouter embedding model is the same `text-embedding-3-small` family used by Azure. If you select an embedding model with a different vector size, recreate the local Chroma data and reprocess every supplier before asking document questions.
