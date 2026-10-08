# Supplier evaluation corpus

Active **manifest v5 / evaluator `rag-evaluator-v3`**: **15 synthetic suppliers, 45 source PDFs, 73 pages, 150 RAG questions, 135 registration/tax field checks**. The final five packs form a separate **50-question stress cohort**. Their 15 PDFs contain 43 pages, including three mixed native/OCR originals with one lightly skewed, JPEG-compressed scanned page each.

| Group | Suppliers | PDFs | Questions |
|---|---:|---:|---:|
| Core: native facts, OCR, conflicting originals and onboarding scenarios | 10 | 30 | 100 |
| Stress: multi-page clauses, temporal precedence, mixed OCR, address roles and cover conditions | 5 | 15 | 50 |
| Total | 15 | 45 | 150 |

Each supplier contributes registration, tax and supplementary liability originals. Registration contributes five policy fields; tax contributes four. **Insurance is RAG-only.** Model policy annotations on those supplementary files are retained as unscored diagnostics; they do not establish insurance compliance. Field accuracy does not establish full supplier compliance or approval.

From the repository root:

```bash
git pull --ff-only origin supplier-rag-feature
docker compose up -d --build backend
docker compose run --rm --build evaluation --validate-only
docker compose run --rm --build evaluation
```

The full live run writes host files:

- `sample_documents/evaluation_sets/latest_results.json`
- `sample_documents/evaluation_sets/latest_results.md`

Provider credentials belong in `backend/.env`. If reviewer demo login is disabled, export both `EVALUATION_REVIEWER_EMAIL` and `EVALUATION_REVIEWER_PASSWORD`. Compose mounts this directory into `/app/sample_documents/evaluation_sets`, waits for backend health and connects over the Compose network. Rebuild the backend before running the evaluator.

To run only the new stress cohort, preserving the full-suite latest files:

```bash
docker compose run --rm --build evaluation --cohort stress \
  --output sample_documents/evaluation_sets/stress_results.json \
  --report-output sample_documents/evaluation_sets/stress_results.md
```

Validation-only performs no model calls and writes no scores. A live run creates fresh supplier records and preserves existing suppliers. Existing report bytes are archived in `results_archive/<timestamp_uuid>/` before replacement. An upload rejection or document-processing failure is reported as an incomplete pipeline run with unexecuted questions, not as a wrong RAG answer. Accuracy from an incomplete run covers only executed questions.

The JSON/Markdown reports separate **upload HTTP (includes text/OCR extraction and validation)**, **processing/indexing**, and **Q&A** latency. Isolated OCR duration is not instrumented; OCR-pack Q&A latency excludes the work of reading a newly uploaded scan.

All 50 stress answers have authored references, source-page rules and a mandatory human-review checklist in the reports. The automatic score checks components and page identity. Audit role/value attribution, temporal precedence, conditions/exclusions and every cited claim against the originals before describing an audited stress result. Calibration-test passes are evaluator tests, never model accuracy.

The first ten packs are pinned unchanged in `baseline_manifest_v4.json`; the first five also remain pinned in `baseline_manifest_v3.json`. To reassess a saved v4 live report offline, use `--manifest sample_documents/evaluation_sets/baseline_manifest_v4.json --rescore <source.json>` with distinct explicit output/report paths. Original observations and source hashes are preserved. An active v5 manifest cannot score a saved v4 run as though the new questions had executed.

Optional intentional regeneration (no model calls):

```bash
python scripts/generate_stress_evaluation_documents.py
```

It preserves the pinned ten packs and writes only the five new packs plus active manifest. Keep PDF hashes, transcripts, per-supplier ground truth and the combined manifest together. Authoring transcripts are never uploaded or indexed. Their checksum tolerates only Windows CRLF-to-LF conversion; PDF hashes remain byte-exact.

See `QUALITY_EVALUATION.md` and `EVALUATOR_CALIBRATION.md` for the fixed rubric, fair-stress design, validations and limits. Live v5 results remain pending execution; no placeholder results are committed.
