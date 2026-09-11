# VendorLens AI — Project Blueprint

## Purpose

VendorLens streamlines supplier onboarding by combining document extraction, retrieval-augmented Q&A, deterministic compliance rules, and human approval in one workflow.

## Users and workflow

1. A reviewer creates a supplier case.
2. The supplier’s registration, tax, and insurance documents are uploaded.
3. The system extracts text, redacts PII, extracts structured fields, and indexes redacted chunks.
4. The reviewer asks grounded questions and sees source citations.
5. Compliance checks highlight missing, expired, invalid, or uncertain information.
6. The reviewer corrects fields and approves or rejects the supplier with an audit trail.

## Architecture

- **Frontend:** React, TypeScript, Vite, and Material UI.
- **API:** FastAPI with PostgreSQL persistence and REST endpoints.
- **AI pipeline:** PyMuPDF text extraction, regex PII redaction, OpenRouter-first structured extraction and embeddings, with Azure OpenAI used when OpenRouter is not configured.
- **Retrieval:** ChromaDB with supplier-scoped document chunks and citations.
- **Controls:** deterministic compliance rules, confidence thresholds, conflict detection, audit events, and human approval.
- **Operations:** Langfuse tracing, Promptfoo evaluation, and Prometheus metrics.

## Key boundaries

The current demo supports selectable-text PDFs and UTF-8 text files. Image-only PDFs require future OCR support. The system does not make autonomous approval decisions; AI findings remain subject to human review and deterministic checks.

## Success criteria

Reviewers should be able to trace every extracted value to a source page, receive grounded answers or a safe not-found response, understand why a field needs review, and see measurable application health and AI quality.
