# Supplier Quality Evaluation Packs

This folder contains five coherent supplier packs for repeatable SourceSure AI extraction and grounded-Q&A evaluation.
The PDF content intentionally looks like ordinary onboarding documentation; synthetic-data disclosure and expected answers are kept outside the PDFs.

Each supplier directory contains:

- `01_supplier_registration_form.pdf` uploaded as `registration`.
- `02_gst_registration_certificate.pdf` uploaded as `tax`.
- `03_certificate_of_liability_insurance.pdf` uploaded as `insurance`.
- `ground_truth.json` containing expected fields and Q&A cases.

`evaluation_manifest.json` combines all five ground-truth files and 50 questions for the evaluation runner. Each supplier has ten questions spanning direct facts, paraphrases, date interpretation, a multi-fact response, and safe not-found behaviour.
`latest_results.json` is generated after a live run and contains machine-readable field, answer, citation, safe-fallback, isolation, token, latency, question-type and per-supplier results. `latest_results.md` contains the same run as a mentor-ready report with methodology and limitations.
The previous four-supplier/24-question run is retained as `historical_results_4_suppliers_24_questions.json` so it cannot be mistaken for the final result.

Regenerate the documents from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe scripts\generate_evaluation_documents.py
```

Run the live evaluation while FastAPI is available at port 8000:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_quality_evaluation.py
```

On the Linux demo VM, the easiest and recommended command is:

```bash
docker compose run --rm --build evaluation
```

This starts the required Compose dependencies if necessary and writes both reports into this directory. The default command uses the reviewer demo session. If reviewer authentication is enabled, run the Python command directly with `EVALUATION_REVIEWER_EMAIL` and `EVALUATION_REVIEWER_PASSWORD` set.

The runner reuses suppliers with matching legal names, uploads only missing categories, reprocesses their documents, and writes the complete result file.

Headline accuracy is strict: a question passes only when its expected answer terms, found/not-found decision, citation rule, and supplier-isolation check all pass. The report labels the results as a controlled synthetic regression evaluation rather than a production guarantee.
