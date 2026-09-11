# Supplier Quality Evaluation Packs

This folder contains four coherent supplier packs for repeatable VendorLens extraction and grounded-Q&A evaluation.
The PDF content intentionally looks like ordinary onboarding documentation; synthetic-data disclosure and expected answers are kept outside the PDFs.

Each supplier directory contains:

- `01_supplier_registration_form.pdf` uploaded as `registration`.
- `02_gst_registration_certificate.pdf` uploaded as `tax`.
- `03_certificate_of_liability_insurance.pdf` uploaded as `insurance`.
- `ground_truth.json` containing expected fields and Q&A cases.

`evaluation_manifest.json` combines all four ground-truth files for the evaluation runner.
`latest_results.json` is generated after a live run and contains detailed field, answer, citation, isolation, token, and latency results.

Regenerate the documents from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe scripts\generate_evaluation_documents.py
```

Run the live evaluation while FastAPI is available at port 8000:

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_quality_evaluation.py
```

The runner reuses suppliers with matching legal names, uploads only missing categories, reprocesses their documents, and writes the complete result file.
