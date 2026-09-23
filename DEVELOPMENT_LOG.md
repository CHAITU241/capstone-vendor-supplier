# VendorLens AI — Development Handoff Log

This file is the short resumption context for future AI or developer sessions.
Read this file first, then open only the files relevant to the next task.
The complete product intent remains in `PROJECT_BLUEPRINT.md`.

## Current Status

- Current milestone: Phases 1-4 are implemented on the local `phase-4` branch.
- The delivered demo includes intake, protected AI extraction/RAG, compliance review, mock ERP decisions, global assistant, Langfuse tracing, Promptfoo evaluation, and Prometheus monitoring.
- Architecture intentionally favors a small demo over production complexity.
- Backend and frontend are separate applications sharing REST contracts.
- Backend credentials remain in the ignored `backend/.env` file.
- Use `PROJECT_BLUEPRINT.md` for final scope and `README.md` for the complete runbook.

## Standard Project Layout

```text
backend/app/main.py                 FastAPI setup, CORS, and error handlers
backend/app/config.py               Environment-backed application settings
backend/app/database.py             SQLAlchemy engine and session dependency
backend/app/models.py               Supplier, Document, and AuditEvent models
backend/app/schemas.py              Pydantic request and response schemas
backend/app/routers/                Health, supplier, and upload endpoints
backend/app/services/documents.py   PDF and UTF-8 text extraction
backend/app/metrics.py              Prometheus counters, histograms, and gauges
backend/app/vector_store.py         Local persistent ChromaDB client
backend/alembic/                    PostgreSQL migration environment
backend/tests/                      Focused backend unit tests
scripts/generate_mock_documents.py Reusable three-PDF supplier training document generator
sample_documents/                  Upload-ready PDFs and extraction ground truth
frontend/src/api/                   API client and shared TypeScript types
frontend/src/components/            App shell and reusable status component
frontend/src/pages/                 Dashboard, intake, and review pages
frontend/src/theme/theme.ts         Single source for all brand colors
```

## Phase 1 Changes Completed

### Backend

- Added FastAPI application with CORS for the local React origin.
- Added consistent JSON error bodies for HTTP and validation errors.
- Added PostgreSQL SQLAlchemy session setup and environment configuration.
- Added Supplier, Document, and AuditEvent database models.
- Added supplier status, document type, and processing status enums.
- Added Alembic migration `0001_phase_one` for Phase 1 PostgreSQL tables.
- Added `POST /api/suppliers`, `GET /api/suppliers`, and `GET /api/suppliers/{id}`.
- Added `POST /api/suppliers/{id}/documents` multipart upload endpoint.
- Limited uploads to PDF and UTF-8 text with a configurable 10 MB maximum.
- Sanitized displayed filenames and stored files under generated UUID names.
- Added synchronous PDF/text extraction with page markers.
- Added a clear failed state for empty, unreadable, or image-only documents.
- Added supplier creation and document outcome audit events.
- Added `/api/health` checks for PostgreSQL and local ChromaDB readiness.
- Added focused unit tests for UTF-8 text extraction behavior.

### Frontend

- Added Vite, React, TypeScript, React Router, and Material UI setup.
- Added a responsive app shell with dashboard and new-supplier navigation.
- Added a dashboard with loading, error, empty, and supplier-card states.
- Added a supplier intake form with client and API validation feedback.
- Added a supplier review screen with document upload and processing results.
- Added recent audit activity to the supplier review screen.
- Added typed API request and response contracts.
- Added a reusable status chip for supplier and document states.
- Centralized the full palette in `frontend/src/theme/theme.ts`.
- Extended Material UI typing with a custom `tertiary` palette token.

### Local Development

- Added backend and frontend environment examples.
- Added root ignore rules for secrets, uploads, dependencies, builds, and caches.
- Added setup, run, check, and demo instructions to `README.md`.
- Switched setup documentation to local PostgreSQL 18 only; Docker must not be used.
- Replaced the PostgreSQL vector extension with embedded persistent ChromaDB to avoid system-level installation.
- Added root `start.sh` to migrate and boot the FastAPI and React development servers together.
- Added three realistic synthetic supplier PDFs covering registration, GST, and insurance.
- Added `sample_documents/README.md` with upload mappings and ground-truth values for future evaluations.

## Phase 1 Review Refinements Completed

### Upload and data rules

- Restored the original document types: `registration`, `tax`, and `insurance`.
- Added Alembic migration `0003_restore_three_types` to remove the unused incorporation and bank enum values.
- Enforced one document per supplier and document type in both the API and database.
- Duplicate uploads now return HTTP 409 and instruct the user to delete the existing document first.
- Added `DELETE /api/suppliers/{supplier_id}/documents/{document_id}` with supplier scoping and a `document.deleted` audit event.
- Physical deletion is restricted to files located beneath the configured upload directory.
- Made country required during supplier creation and replaced free text with a controlled frontend dropdown.

### Frontend and document pack

- Uploaded document types are removed from the upload dropdown automatically.
- Added a delete icon and confirmation dialog; the deleted type becomes immediately available for re-upload.
- Added a completion state when all three document categories are present.
- Updated the three PDFs to use realistic business wording and presentation without prominent demo banners.
- Retained a small `TRAINING SAMPLE - NOT VALID FOR OFFICIAL USE` footer to prevent accidental official use.
- Updated the sample-document mapping so every PDF has a distinct upload category.

## Latest Verification

- Verification date: 2026-08-04.
- ChromaDB 1.5.9 installed successfully in the project virtual environment.
- Local PostgreSQL connection passed against PostgreSQL 18.1 and database `vendorlens`.
- `alembic upgrade head` passed; revision is `0003_restore_three_types (head)`.
- PostgreSQL tables confirmed: `alembic_version`, `suppliers`, `documents`, and `audit_events`.
- `/api/health` returned HTTP 200 with `status: healthy`, `database: connected`, and `chroma: connected`.
- Reversible API smoke test passed supplier creation, all three upload categories, duplicate rejection, deletion, re-upload, detail, extraction, and audit events.
- All three sample PDFs passed selectable-text checks and the live Phase 1 PDF upload/extraction endpoint.
- The three-document smoke-test records were removed and left no sample supplier data in PostgreSQL.
- Smoke-test records were removed and the user's pre-test database row counts were restored exactly.
- `python -m compileall -q app tests`: passed.
- `python -m pytest -q`: 2 tests passed.
- `npm run lint`: passed.
- `npm run build`: passed; Vite transformed 947 modules.
- The installed Node.js version is 23.11.1; npm may show an engine warning for one lint dependency, but lint and build pass.

## Current API Contract

- Supplier create body: `name`, required `country`, optional `contact_email`.
- Document upload fields: `document_type` and `file`.
- Allowed document types: `registration`, `tax`, and `insurance`.
- Document delete path: `DELETE /api/suppliers/{supplier_id}/documents/{document_id}`.
- Allowed MIME types: `application/pdf` and `text/plain`.
- Document results expose metadata and status, but never raw extracted text.
- Supplier detail includes document metadata and recent audit events.
- General onboarding chat path: `POST /api/assistant/chat` with a bounded conversation message list.

## Important Decisions

- Docker Compose is now the recommended fresh-clone path; native local PostgreSQL remains supported for existing development workflows.
- Upload extraction is synchronous to keep the demo easy to run and understand.
- Local files use UUID names to prevent path traversal and filename collisions.
- Original filenames are retained only as sanitized metadata.
- ChromaDB uses `PersistentClient` at the configured `CHROMA_PATH`; no separate service is required.
- PostgreSQL remains the source of truth for business records and audit data.
- PII redaction must happen before Phase 2 sends document text to OpenAI.
- Retrieval must always filter on `supplier_id` before similarity ranking.
- AI prompts, credentials, and model routing belong only in the backend.
- Theme colors must never be duplicated outside the central theme configuration.

## Phase 2 Starting Checklist

1. Add `ai_runs` and extracted-field models plus a new Alembic migration.
2. Add deterministic PII detection and typed placeholder redaction.
3. Add versioned prompt files and OpenAI client configuration.
4. Add schema-validated document classification and field extraction using `gpt-4o-mini`.
5. Add deterministic token-aware chunking and `text-embedding-3-small` embeddings.
6. Store vectors and chunk metadata in ChromaDB and implement supplier-filtered retrieval.
7. Add a cited Q&A endpoint and a “not found” response path.
8. Extend the review UI with extracted fields, sources, and document Q&A.
9. Add tests proving PII redaction and cross-supplier retrieval isolation.

## Phase 2 Implementation Status (2026-08-04)

### Completed backend work

- Added Alembic revision `0004_phase_two_ai_rag`; the local database is at this head revision.
- Added `ExtractedField` and `AiRun` persistence, supplier relationships, run types/statuses, token counts, latency, retrieval counts, errors, and details.
- Added deterministic typed-placeholder redaction for GSTIN, PAN, CIN, email, phone, and bank-account patterns before any AI call.
- Added page-local token-aware chunking with a 500-token target and 75-token overlap.
- Added Azure OpenAI structured extraction and grounded-answer services using Pydantic schemas and Chat Completions parsing.
- Added `text-embedding-3-small` embedding calls and local Chroma storage with mandatory `supplier_id` filtering.
- Added versioned extraction and RAG prompts, citation validation, and the exact information-not-found fallback.
- Added `POST /api/suppliers/{id}/process` and `POST /api/suppliers/{id}/questions`.
- Document deletion now clears stale extracted fields and supplier vectors before allowing replacement/reprocessing.
- AI failures persisted in PostgreSQL/audit data are sanitized so provider errors cannot retain credential fragments or document content.

### Completed frontend work

- Added processing/reprocessing controls gated on all three ready document categories.
- Added source-linked extracted-field cards with confidence and human-review indicators.
- Added supplier document Q&A with citations, not-found presentation, and run model/token/latency metrics.
- Extended the typed API client and error handling for both project and standard FastAPI error bodies.

### Azure OpenAI configuration

- `OPENAI_API_KEY` holds the Azure key and remains ignored by Git.
- `AZURE_OPENAI_ENDPOINT` holds the Azure resource or compatible gateway root URL.
- `AZURE_OPENAI_API_VERSION` defaults to `2024-10-21`.
- `OPENAI_EXTRACTION_MODEL`, `OPENAI_ANSWER_MODEL`, and `OPENAI_EMBEDDING_MODEL` are Azure deployment names.
- The dedicated `AzureOpenAI` client supplies the Azure endpoint, API version, and `api-key` authentication convention.

### Phase 2 verification so far

- Backend compilation passed.
- Backend tests passed: 7 tests covering Phase 1 extraction plus redaction, chunking, and cross-supplier retrieval isolation.
- Frontend TypeScript check and production build passed; Vite transformed 948 modules.
- `alembic current` reports `0004_phase_two_ai_rag (head)`.
- FastAPI health passed with PostgreSQL and Chroma connected; the frontend responded on port 5173.
- Live smoke supplier `f4c06ad6-e6df-4eae-b231-6ae2d66ee7b7` was created and all three PDFs uploaded successfully.
- The Azure endpoint/authentication configuration was corrected by the user and live processing now succeeds.
- Do not mark Phase 2 complete or commit/merge it until the documented answer-quality misses below are resolved or explicitly accepted for the demo.

### Exact next step

1. Confirm whether `AZURE_OPENAI_ENDPOINT` is a standard Azure resource URL or a company gateway.
2. For a gateway, obtain its documented authentication header and route convention; do not probe the secret across guessed schemes.
3. Restart FastAPI after changing `.env`, then reprocess the existing smoke supplier instead of creating another row.
4. Verify extracted fields, Chroma chunks, cited insurance-expiry answer, and the not-found answer.
5. Remove or deliberately retain the smoke supplier, run final tests/build/lint, and commit the verified checkpoint on `feature/phase-2` without merging.

## Phase 2 Live Answer-Quality Check (2026-08-04)

- Reprocessed smoke supplier `f4c06ad6-e6df-4eae-b231-6ae2d66ee7b7` successfully with all three PDFs.
- Processing produced 20 stored field rows and 3 Chroma chunks in 12.8 seconds using 2,823 input and 667 output tokens.
- Boundary redaction detected 2 GSTINs, 2 PANs, 1 CIN, 1 email, and 1 phone before Azure OpenAI calls.
- Legal-name question passed with the exact expected name and registration/GST citations.
- Registered-address question passed with the expected full address and a registration citation.
- Deliberately absent bank-balance question passed with the exact not-found answer and zero citations.
- Insurance-expiry question failed answer quality: it returned not-found instead of `31 MAR 2027`.
- Retrieval for the insurance question was correct: it selected the insurance PDF at distance `0.5875`, and the indexed chunk contains `01 APR 2026 - 31 MAR 2027`.
- The insurance miss is therefore in answer interpretation/citation generation rather than vector retrieval.
- Extraction correctly produced `insurance_expiry_date = 31 MAR 2027` with confidence `1.0`, but unrelated documents also produced literal string values such as `"null"`; these are currently stored as review fields.
- Overall answer-quality score for this quick deterministic evaluation: `3/4` (`75%`).

### Recommended next fixes

1. Normalize model strings such as `"null"`, `"none"`, and empty values to Python `None` before persistence.
2. Consolidate repeated extracted fields across documents instead of displaying every document-level candidate equally.
3. Strengthen the RAG prompt or evidence formatting so a policy-period end date is interpreted as the insurance expiry date.
4. Add the four live questions as a repeatable evaluation dataset with expected answer terms, source documents, found/not-found flags, and latency metrics.

## Phase 2 Multi-Supplier Quality Improvements (2026-08-04)

### Implemented fixes

- Added null-like value normalization before extracted-field persistence.
- Added canonical supplier-field selection across documents with authoritative source preferences and conflict review flags.
- Reduced duplicated document-level fields to at most one source-linked field per supported field name.
- Added extraction prompt v3 to return contact names without roles and preserve true JSON null behavior.
- Added answer prompt v3 with explicit policy-period expiry semantics and short exact citation labels.
- Replaced model-facing UUID chunk IDs with `chunk_1`, `chunk_2`, and similar labels while preserving real Chroma IDs in API citations and audit details.
- Increased `RAG_MAX_DISTANCE` from `0.65` to `0.72`; the local ignored `.env` and `.env.example` were both updated.
- Added model citation intent to AI-run details for future failure diagnosis.
- Added three unit tests for null normalization, exact duplicate consolidation, and conflicting authoritative-source selection.

### New evaluation corpus and tooling

- Added four new supplier directories under `sample_documents/evaluation_sets/`.
- Added 12 realistic text-native PDFs: registration, GST, and insurance documents for each supplier.
- PDF content contains no mock, demo, training, or synthetic banner text; disclosure remains in the adjacent README/ground truth.
- Added per-supplier `ground_truth.json` files and aggregate `evaluation_manifest.json`.
- Added `scripts/generate_evaluation_documents.py` for reproducible PDF/ground-truth generation.
- Added `scripts/run_quality_evaluation.py` for idempotent supplier reuse, missing-document upload, reprocessing, field checks, Q&A checks, citation checks, isolation checks, tokens, and latency.
- Added `QUALITY_EVALUATION.md` and generated `latest_results.json`.

### Live evaluation results

- Initial multi-supplier baseline: 35/36 fields (`97.2%`) and 12/24 Q&A cases (`50%`).
- Root causes were the strict `0.65` retrieval cutoff, unreliable model copying of UUID citation IDs, and one contact-name role suffix.
- Final v3 evaluation: 36/36 fields, 24/24 Q&A cases, 100% citation accuracy, 100% not-found accuracy, and 100% supplier-isolation accuracy.
- Average question latency was 2,035 ms; maximum was 2,439 ms.
- Four-supplier processing used 9,195 input and 2,726 output tokens; Q&A used 16,434 input and 677 output tokens.
- Original Asteron regression passed 4/4, including the previously failing insurance-expiry answer with the correct insurance citation.
- Backend test suite now passes 10 tests.

### Runtime note

- The user's Uvicorn reload process became unresponsive during the second evaluation attempt and was replaced with a clean non-reload backend on port 8000.
- The backend and existing frontend remain available; restart FastAPI manually with `--reload` when interactive reload logs are needed.

## Phase 3 Compliance and Human Review (2026-08-04)

### Branch and database

- Phase 3 work is on `feature/phase-3`, created from verified Phase 2 commit `d23b1cf`.
- Added Alembic revision `0005_phase_three_compliance`; the local PostgreSQL database is at this head revision.
- Added persisted `ComplianceResult` records with one unique result per supplier and rule.
- Added supplier decision reason, decision timestamp, and mock ERP supplier reference fields.
- Added pass, fail, and needs-review compliance statuses.

### Deterministic compliance rules

- `document_completeness`: registration, tax, and insurance documents must all be ready.
- `insurance_expiry`: a parseable insurance expiry must be later than the current date.
- `contact_email`: a valid reviewed contact email must be present.
- `supplier_name_match`: the canonical supplier name must appear in every uploaded document; mismatches require review.
- `redaction_boundary`: every document must have redacted text and a redaction summary from Phase 2 processing.
- `field_review`: extracted fields cannot retain unresolved `needs_review` flags.
- Each rule stores an explainable message and non-sensitive evidence in PostgreSQL.

### Human review and decisions

- Added `PATCH /api/suppliers/{supplier_id}/fields/{field_id}` for reviewer corrections.
- Corrections set reviewer confidence to 100%, clear the field review flag, create an audit event without storing old/new sensitive values, and invalidate stale compliance results.
- Added GET and POST compliance endpoints for persisted results and explicit reruns.
- Added confirmed approval and rejection endpoints.
- Approval reruns every deterministic check inside the decision workflow and returns HTTP 409 unless every result passes.
- Rejection requires a reason of at least 10 characters and stores it in the supplier decision and audit history.
- Finalized suppliers are locked against document changes, field corrections, and AI reprocessing in the demo workflow.

### Mock ERP boundary (superseded by the MCP integration below)

- Added a deterministic local `MockERPService` used only after a valid human approval.
- Successful approval creates a stable `ERP-...` supplier reference and separate `erp.supplier.created` and `supplier.approved` audit events.
- This was the initial Phase 3 implementation and is retained here as historical context. It was replaced by the persistent mock ERP MCP integration below.

### Persistent mock ERP MCP integration

- Replaced the approval-time local ERP function with a separately deployed MCP JSON-RPC service.
- Added persistent ERP supplier-master records that can be independently listed and retrieved.
- Added preflight validation for required ERP fields, India scope, category mappings, duplicate tax references, and duplicate bank accounts.
- Added idempotent creation keyed by the stable `SUP-...` supplier reference, so timeouts and retries cannot create duplicates.
- Added sanitized ERP tool-attempt records with operation, status, latency, retry count, and error code.
- ERP unavailability leaves the supplier unapproved and returns a safe retry message instead of a stack trace.
- The reviewer workspace now displays ERP validation results before enabling approval and provides a read-only mock ERP supplier-master screen.
- Verification passed with 65 backend tests, Python compilation, frontend lint, and a production frontend build.

### Frontend

- Added editable extracted-field dialogs with source-page validation.
- Added a compliance panel with pass/fail/review chips and rule explanations.
- Removed the Recent Activity card from the supplier review workspace; backend audit-event persistence remains unchanged.
- Added explicit rerun-check controls and approval readiness messaging.
- Added approval and rejection confirmation dialogs, including required rejection reason input.
- Final decisions display the mock ERP reference or rejection reason and lock mutation controls.

### Verification

- `alembic current` reports `0005_phase_three_compliance (head)`.
- Backend compile and OpenAPI contract checks passed for all five new routes.
- Backend suite passes 15 tests, including happy-path rules, expiry failure, name mismatch, unresolved field, invalid email, and deterministic mock ERP reference.
- Frontend TypeScript, ESLint, and production build passed; Vite transformed 952 modules.
- In-process API smoke passed: approval initially blocked, reviewer correction saved, stale checks invalidated, rerun became approval-ready, approval created an ERP reference, rejection recorded a reason, and all temporary records were removed.
- Existing evaluation suppliers currently have five passing rules and one `field_review` result requiring contact-name confirmation; this is expected human-review behavior.
- Backend port 8000 remains stopped so the user can start FastAPI manually. Frontend port 5173 remains available.

### Manual verification after Phase 3 checkpoint commit

1. Start FastAPI manually and open an existing processed evaluation supplier.
2. Correct or confirm its contact-name field using the edit button.
3. Run compliance checks and confirm all six explanations pass.
4. Approve a dedicated demo supplier and verify its ERP reference, or reject a disposable supplier with a reason.
5. After UI confirmation, merge `feature/phase-3` into the selected integration branch; do not merge it into `main` before review.

## General Supplier Onboarding Assistant (2026-08-05)

### Backend

- Added `POST /api/assistant/chat` for general supplier onboarding guidance.
- Added a versioned `supplier-assistant-v1` prompt and structured answer parsing through the existing Azure OpenAI answer deployment.
- The endpoint accepts only bounded user/assistant conversation messages and returns the answer model, prompt version, token counts, and latency.
- This assistant does not receive a supplier ID and does not access uploaded documents, extracted fields, compliance results, PostgreSQL records, or ChromaDB retrieval.
- Added validation for a user question as the final message and a maximum conversation size; provider errors remain sanitized at the API boundary.

### Frontend

- Added a globally mounted bottom-right floating help icon in `AppShell` that opens a responsive “Supplier onboarding assistant” popover with message bubbles, reset-chat control, and response metrics on every route.
- Tuned the assistant prompt with explicit VendorLens context so document-requirement questions lead with the three required uploads: registration, tax, and insurance.
- The existing “Ask about this supplier” panel remains document-grounded and cited; the new assistant is explicitly labeled as general guidance.

### Verification

- Backend compilation, frontend TypeScript, and ESLint checks pass.
- Added focused assistant contract tests for message forwarding, input validation, and oversized conversation rejection.

## Langfuse AI Tracing (2026-08-05)

### Backend integration

- Added `langfuse==4.14.2` to the backend requirements and installed it in the existing backend virtual environment.
- Added optional Langfuse settings: enabled flag, public/secret keys, base URL, release, and explicit content-capture opt-in.
- Added a failure-safe tracing wrapper around document extraction, embeddings, document-grounded answers, and the global onboarding assistant.
- Each generation records operation name, model, latency, token usage, and safe output metadata.
- Tracing is metadata-only by default; raw prompts, evidence, document text, and answers are excluded unless `LANGFUSE_CAPTURE_CONTENT=true` is explicitly chosen.
- Missing keys, SDK initialization errors, and telemetry export failures do not interrupt the application.
- Langfuse events are flushed during FastAPI shutdown.

### Local setup

- Copy the Langfuse project credentials into the ignored `backend/.env`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_BASE_URL`.
- Keep `LANGFUSE_CAPTURE_CONTENT=false` for supplier data unless redacted content logging has been approved.
- Restart FastAPI after changing the environment and verify the first trace in the Langfuse project dashboard.

### Verification

- Backend suite passes 22 tests, including optional tracing and content-capture safety tests.
- Backend `compileall` and tracing import smoke checks pass without Langfuse credentials.

## Promptfoo AI Evaluation (2026-08-05)

### Evaluation integration

- Added a local `evals/promptfoo/` suite that calls the running FastAPI API rather than Azure OpenAI directly.
- Added separate Promptfoo providers for supplier-scoped RAG (`/api/suppliers/{id}/questions`) and the global onboarding assistant (`/api/assistant/chat`).
- Supplier lookup supports either `PROMPTFOO_SUPPLIER_ID` or an exact `PROMPTFOO_SUPPLIER_NAME`; the default cases use the processed Kaveri evaluation supplier.
- Provider responses expose API token counts, latency, model, prompt version, retrieval count, and information-found metadata to Promptfoo.
- Added deterministic Python assertions for JSON contracts, expected answer terms, source citations, guarded not-found behavior, cross-supplier isolation, assistant guidance, sensitive-data boundaries, and the five-second demo latency target.
- Added nine demo cases covering legal name, payment terms, insurance expiry, absent bank balance, supplier isolation, required documents, workflow guidance, sensitive requests, and supplier-specific assistant boundaries.
- Results and HTML exports are ignored under `evals/promptfoo/results/`.

### Local setup and verification

- Promptfoo is intentionally not added as a global dependency; run it with `npx promptfoo@latest` so it installs in the user npm cache without administrator access.
- Run from `evals/promptfoo` with `npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache -o results/latest.json` while FastAPI is running.
- Python provider/assertion compilation and assertion smoke checks pass.
- Promptfoo CLI download could not complete in the development sandbox because the npm request timed out; run the documented command locally once network access is available.

## Prometheus Monitoring (2026-08-05)

### Backend integration

- Added `prometheus-client==0.25.0` to the backend requirements and installed it in the existing backend virtual environment.
- Mounted the official Prometheus ASGI exposition app at `GET /metrics/`.
- Added bounded-label HTTP request counters, latency histograms, and in-progress request gauges.
- Added AI operation/model success-error counts, latency histograms, and input/output token counters around extraction, embeddings, supplier Q&A, and the global assistant.
- Added processing outcomes, RAG found/not-found and retrieved-chunk metrics, compliance status counts, supplier decision counts, and PostgreSQL/ChromaDB dependency gauges.
- UUIDs, supplier IDs, filenames, questions, document contents, and PII are never metric labels.

### Local Prometheus setup

- Added `monitoring/prometheus/prometheus.yml` targeting `127.0.0.1:8000/metrics/`.
- Added `monitoring/prometheus/download-prometheus.ps1` to fetch the latest official Windows binary into the ignored local directory without administrator access.
- Added `monitoring/prometheus/start-prometheus.ps1` for an extracted user-level Prometheus binary; data and binaries are ignored by Git.
- Added `monitoring/README.md` with no-Docker setup, PromQL examples, and the local UI address.

### Verification

- Prometheus metrics module compiles and the `/metrics/` endpoint is verified after restarting FastAPI.

## OpenRouter Provider Priority (2026-08-28)

- Added OpenRouter configuration for structured document extraction, embeddings, supplier-scoped Q&A, and the global onboarding assistant.
- A non-empty `OPENROUTER_API_KEY` selects OpenRouter for every AI operation; otherwise the existing Azure OpenAI configuration is used.
- Added separate OpenRouter model settings because OpenRouter uses model slugs while Azure uses deployment names.
- OpenRouter defaults preserve the existing model families: `openai/gpt-4o-mini` for structured chat and `openai/text-embedding-3-small` for embeddings.
- OpenRouter structured requests require a route that supports all requested JSON-schema parameters.
- Provider selection happens only during backend client creation. Provider request failures do not silently reroute supplier content to Azure.
- AI-run model metadata, token metrics, Langfuse generations, chunk tokenization, and embedding metadata now use the active provider's model names.
- Added focused provider-selection tests covering OpenRouter priority, Azure fallback, active models, endpoint normalization, and incomplete configuration.
- Backend compilation passed and the full backend suite passes 28 tests.
- Restart FastAPI after changing provider settings because the settings and AI client are process-cached.

## Docker Compose Application Stack (2026-08-28)

- Added a root multi-stage `Dockerfile` with separate FastAPI and React/Nginx targets.
- Added `compose.yaml` for PostgreSQL 18, the backend, and the frontend, with dependency health gates and automatic Alembic migrations.
- The frontend uses same-origin `/api` requests through Nginx; AI processing receives a five-minute proxy read timeout.
- PostgreSQL, uploads, and embedded Chroma data use separate named volumes.
- PostgreSQL 18 data is mounted at `/var/lib/postgresql`, matching the official image's version-specific `PGDATA` layout.
- Added a root `.dockerignore` that excludes local environment files and credentials from the build context.
- Added `DOCKER_SETUP.md` with fresh-clone provider setup, startup, verification, daily commands, persistence, reset warnings, ports, and troubleshooting.
- Static Compose YAML parsing passed, backend compilation and all 28 tests passed, and frontend lint and production build passed with 954 transformed modules.
- Docker was not available in the development environment, so an actual image build and live Compose smoke test remain to be run on a Docker-enabled machine.

## Admin AI Observability and Correlated Langfuse Tracing (2026-09-23)

- Added Administrator as the third landing-page workspace while retaining separately authenticated, admin-only access.
- Added an admin AI-observability dashboard with configurable time windows, run success, tokens, P95 latency, model/operation/prompt usage, RAG grounding, OCR coverage, ERP tool health, and privacy-safe recent runs.
- Added correlated Langfuse workflow traces for OCR/text extraction, document processing, supplier RAG, supplier/reviewer assistants, and MCP ERP tools.
- Added hashed telemetry subjects, assistant/workflow sessions, provider/model/prompt/release metadata, and quality scores for processing, grounding, citations, OCR, and ERP tool success.
- Removed original filenames from extraction telemetry and the LLM extraction prompt; only the file extension and document type are retained.
- Normalized OpenRouter model slugs for Langfuse pricing lookup while preserving the complete provider model in metadata.
- Added `LANGFUSE_DASHBOARD_URL` for the admin-only deep link and documented the recommended VendorLens dashboard widgets.
- Verification: 77 backend tests passed; frontend production build passed; frontend lint completed with zero errors and two pre-existing warnings.

## Demo Authentication Flow (2026-09-24)

- Supplier authentication now defaults to **Sign in** unless the user explicitly selects **Create account**.
- Removed the hidden admin link from the supplier sign-in page; reviewer and administrator entry now live only on the three-workspace landing page.
- Added independent `REVIEWER_AUTH_ENABLED` and `ADMIN_AUTH_ENABLED` runtime flags. Both default to `false` for one-click demo access; either role can independently require its configured email and password.
- Added a reviewer credential endpoint/page and an admin demo-session endpoint while retaining role-protected reviewer and admin APIs.
- Replaced the browser's single active login with separate supplier, reviewer, and administrator sessions. Entering a staff workspace no longer discards the supplier login.
- Updated Docker and demo documentation to match the current staff entry and OCR behavior.
- Verification: 79 backend tests passed; frontend production build passed; frontend lint completed with zero errors and two pre-existing warnings.

## Resume Commands

Preferred combined command from the repository root:

```bash
bash start.sh
```

Manual commands:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
uvicorn app.main:app --reload
```

```powershell
cd frontend
npm run dev
```

## Update Rule

After each meaningful implementation session, update this file with:

- The latest completed milestone.
- New or changed APIs, models, configuration, and commands.
- Important architectural decisions and their reason.
- Verification commands and known failures.
- The exact next implementation checklist.
