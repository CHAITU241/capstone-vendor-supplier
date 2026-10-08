# Supplier Quality Evaluation Packs

Five synthetic supplier packs; three PDFs and ten RAG questions per pack. The active manifest is version 3.

| Original | Extraction scope | RAG scope |
|---|---|---|
| `01_supplier_registration_form.pdf` | Five current registration-policy fields | Included |
| `02_gst_registration_certificate.pdf` | Four tax-policy fields, with separate PAN and GSTIN | Included |
| `03_certificate_of_liability_insurance.pdf` | Explicitly excluded: legacy type has no policy extraction contract | Included |

The evaluation therefore covers **45 source-scoped extraction checks**, **15 RAG originals**, and **50 questions** with a 20/10/5/5/10 direct/paraphrased/date/multi-fact/not-found split. It does not score complete onboarding approval or OCR.

From the repository root:

```bash
docker compose up -d --build backend
docker compose run --rm --build evaluation --validate-only
docker compose run --rm --build evaluation
```

Configure OpenRouter in `backend/.env`. If reviewer demo login is disabled, export both `EVALUATION_REVIEWER_EMAIL` and `EVALUATION_REVIEWER_PASSWORD` first. The service passes those variables to the runner.

The validator checks PDF hashes/readability, policy schema coverage, exact question counts and ground-truth consistency before any API calls. Each live run creates five fresh supplier records and forces processing refresh. Existing cases are left intact; supplier IDs identify runs even when display names repeat.

Reports are written to `latest_results.json` and `latest_results.md` in this directory, mounted onto the host. Previous latest reports are preserved in `results_archive/<timestamp_uuid>/`. No live report is written by validation-only mode or by tests.

Historical evidence:

- `historical_results_4_suppliers_24_questions.json`: the older 24-question run.
- `historical_results_manifest_v2_50_questions.json` and `.md`: the actual version-2 run with 45/50 RAG passes; JSON bytes preserved unchanged.
- `historical_manifest_v2.json`: the version-2 expectations. Its obsolete extraction score is not comparable with version 3.

`evaluation_manifest.json` combines each supplier's `ground_truth.json` and pins PDF hashes. To regenerate the corpus intentionally, use the backend Python environment:

```bash
python scripts/generate_evaluation_documents.py
```

Regeneration changes PDF bytes and manifest hashes, so keep PDFs, all ground-truth files and the combined manifest together. Read `QUALITY_EVALUATION.md` for methodology and limitations. Genuine wrong answers, missing fields, incorrect dates and bad citations remain failures.
