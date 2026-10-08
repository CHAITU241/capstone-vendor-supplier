# SourceSure AI Controlled Quality Evaluation

The active manifest is **version 4: 10 synthetic suppliers, 30 source PDFs, 100 RAG questions and 90 policy-field extraction checks**. The expanded live run remains pending; adding evidence does not establish a new accuracy score.

## Evidence and question coverage

| Supplier group | Suppliers | PDFs | RAG questions | Purpose |
|---|---:|---:|---:|---|
| Baseline | 5 | 15 | 50 | Native-text facts, paraphrases, dates, multi-fact answers and unsupported requests |
| OCR | 2 | 6 | 20 | Image-only originals requiring backend OCR |
| Conflicting evidence | 2 | 6 | 20 | Address, payment-term and expiry disagreements across originals |
| Broader onboarding scenarios | 1 | 3 | 10 | Vendor-master setup, AP terms, insurance diary, procurement handover and missing payment/approval evidence |
| **Total** | **10** | **30** | **100** | **80 answerable; 20 safe not-found** |

The added packs are Mallige Precision Works and Narmada Instrumentation (OCR), Aravali Process Equipment and Coromandel Sensor Systems (conflicting evidence), and Tungabhadra Industrial Services (onboarding scenarios). Each supplier has registration, tax and supplementary liability originals and ten questions.

| Question type | Count |
|---|---:|
| Direct fact | 32 |
| Paraphrased fact | 16 |
| Date interpretation | 7 |
| Multi-fact | 9 |
| Safe not-found | 20 |
| Conflict resolution | 8 |
| Scenario-based | 8 |
| **Total** | **100** |

The two scanned packs contain six one-page image-only PDFs: one grayscale raster pack and one JPEG-compressed pack with scanner margins. Their pinned `.source.txt` files are authoring transcripts for offline gold validation only; they are never uploaded or indexed as evidence. Preflight exercises the actual backend OCR routine. A live run also requires backend metadata proving OCR processed every scanned page. OCR quality scores and review flags remain visible in the report.

Each conflicting-evidence supplier has four questions that require both disagreeing values, source attribution, both source citations, conflict acknowledgement and an uncertainty/clarification guard. The originals provide no correction or authority rule; selecting one value as confirmed is unsupported. The other six questions cover facts and guarded fallback. Scenario questions cover eight answerable tasks and two unsupported requests for a bank account or approval.

## Scoring contract

A strict RAG pass requires the expected answer components, correct found/not-found decision, valid expected citations and supplier isolation. Conflict questions additionally require their declared source citations and lexical conflict/uncertainty guards. Unsupported questions must return the exact safe fallback with zero citations. Model errors remain failed cases; expected facts are authored before a run.

Extraction scores **90 current policy fields across 20 registration/tax originals**, checked within the document that supplied each field. The ten supplementary liability certificates are explicitly RAG-only because the legacy `insurance` type has no policy extraction field contract. This evaluates extraction and grounded Q&A, not full supplier approval or every category policy. Production allow-lists and RAG prompts are unchanged.

For scanned supplementary evidence with no extraction field contract, upload quality uses visual/readability checks; inapplicable field confidence and coverage are recorded as null. Poor scans remain rejected and review-quality scans retain attention flags. Registration/tax field quality gates remain in force.

## Run on the Docker machine

From the repository root, with `backend/.env` configured for the AI provider:

```bash
git pull --ff-only origin supplier-rag-feature
docker compose up -d --build backend
docker compose run --rm --build evaluation --validate-only
docker compose run --rm --build evaluation
```

The evaluation container includes Python dependencies and English Tesseract OCR. Compose mounts the corpus and reports, waits for backend health and uses `http://backend:8000/api`; provider credentials stay in the backend. If reviewer demo login is disabled, export both `EVALUATION_REVIEWER_EMAIL` and `EVALUATION_REVIEWER_PASSWORD` before running. Never commit credentials.

Direct Python, with backend requirements and Tesseract installed:

```bash
PYTHONPATH=backend python scripts/run_quality_evaluation.py --validate-only
PYTHONPATH=backend python scripts/run_quality_evaluation.py --base-url http://127.0.0.1:8000/api
```

Preflight checks exact counts/cohorts, policy coverage, question assertions, manifest/ground-truth consistency, PDF and transcript hashes, native readability, image-only scan structure and actual OCR extraction. A normal run creates ten fresh evaluation supplier records and verifies uploaded original hashes. Processing uses `refresh=true` and requires every original to be processed freshly. Existing suppliers and reviewer decisions are preserved; each report records the new supplier IDs.

Transcript hashing accepts Windows CRLF-to-LF line-ending conversion only; changed source content still fails. Git pins `.source.txt` checkouts to LF, and the generator writes LF explicitly. PDF checksums remain byte-exact.

## Reports and audit trail

A completed live run writes these files in the host repository:

- `sample_documents/evaluation_sets/latest_results.json`
- `sample_documents/evaluation_sets/latest_results.md`

Existing latest reports are copied byte-for-byte into `results_archive/<timestamp_uuid>/` before replacement. Preflight and unit tests do not publish placeholder scores. An interrupted run does not publish a new final report. Until a version-4 live run completes, an existing latest report still describes its recorded manifest version and question count.

JSON retains run/manifest provenance, original hashes and metadata, supplier IDs, expected/actual field values, processing diagnostics, question answers and gold assertions, citation excerpts, retrieved chunk IDs/distances, model/prompt versions, tokens and latency. Markdown reports strict end-to-end and component accuracies, failures by component, per-type/per-supplier/per-cohort results, OCR execution evidence, average/P50/P95/max latency, usage, extraction mismatches and limitations. Q&A tokens are separated from extraction/indexing usage.

The pinned `baseline_manifest_v3.json` preserves the original five supplier records and PDF hashes. `scripts/generate_evaluation_documents.py` regenerates that baseline only; `scripts/generate_extended_evaluation_documents.py` regenerates the expanded package and active manifest. Regeneration is optional and does not run the model. The runner can read the pinned baseline via `--manifest sample_documents/evaluation_sets/baseline_manifest_v3.json`.

## Interpretation and remaining limits

This is a controlled synthetic English corpus. The scan cases exercise OCR, including compression, but do not cover severe blur, skew, handwriting or every scanner defect. Broader questions are authored onboarding scenarios, not independently sampled real user traffic. Documents remain one page each; conflicting evidence now spans separate originals rather than pages within one file.

Answer matching, source attribution and conflict guards are lexical checks, not a semantic judge. Citation checks verify expected document/page/retrieved-chunk identity; they do not prove every excerpt entails every claim. Isolation checks are structural/name checks, not exhaustive adversarial leakage testing. Real held-out supplier documents, independent question labels and multi-page evidence remain future calibration work. Results from different manifest versions are not a like-for-like model improvement. Monetary cost should come from provider/Langfuse records rather than token-based estimates.
