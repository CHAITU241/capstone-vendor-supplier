# Supplier evaluation corpus

Active **manifest v5 / scoring revision 3 / evaluator `rag-evaluator-v5`**: **15 synthetic suppliers, 45 source PDFs, 73 pages, 150 RAG questions, 135 registration/tax field checks**. The final five packs form a separate **50-question stress cohort**. Their 15 PDFs contain 43 pages, including three mixed native/OCR originals with one lightly skewed, JPEG-compressed scanned page each.

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

The default run captures complete redacted generation context and an independent raw top-10 retrieval snapshot for every question. The deterministic end-to-end pass rate is scored immediately. **Precision@10 and faithfulness remain pending until semantic relevance/claim judgments exist.** To capture and judge in one run:

```bash
docker compose run --rm --build evaluation --judge
```

The judge uses backend provider credentials; no keys are copied to the evaluation container. Optionally set `EVALUATION_JUDGE_MODEL` in `backend/.env` to a different supported model/deployment, then rebuild the backend. A blank value reuses the answer model and the report identifies this potential correlation. Protocol **`rag-metric-judge-v3`** freezes exact answer spans in a document-free inventory stage, validates complete coverage/offsets, then scores required fixed claim slots against actual generation context. It cannot add document facts that the answer never asserted. Completed v2 retrieval judgments are reused with fingerprint/prompt checks. A v2-to-v3 reassessment normally needs 242 inventory/support calls and no relevance calls; a fresh assessment needs 362 calls, plus bounded retries. Judge tokens/latency stay separate from answering. Failed judgments remain pending; no invented metric values are substituted.

All inputs and verdicts needed for offline calculation are in JSON: ranked full-text chunks with hashes, supplier pool size, actual generation context, relevance labels, exact answer spans/offsets, support quotes, rationales and judge provenance. To judge an already captured report without asking new RAG questions (the source backend evaluation records must still exist):

```bash
docker compose run --rm --build evaluation \
  --judge-report /app/sample_documents/evaluation_sets/latest_results.json \
  --output /app/sample_documents/evaluation_sets/judged_results.json \
  --report-output /app/sample_documents/evaluation_sets/judged_results.md
```

To recompute scores from a judged report, with **no backend/model calls**:

```bash
docker compose run --rm --build evaluation \
  --metrics-from-report /app/sample_documents/evaluation_sets/judged_results.json \
  --output /app/sample_documents/evaluation_sets/recalculated_metrics.json \
  --report-output /app/sample_documents/evaluation_sets/recalculated_metrics.md
```

To recover an earlier partially judged report after upgrading the protocol, preserve it and write new files:

```bash
docker compose run --rm --build evaluation \
  --judge-report /app/sample_documents/evaluation_sets/latest_results_judged_v2.json \
  --output /app/sample_documents/evaluation_sets/latest_results_judged_v3.json \
  --report-output /app/sample_documents/evaluation_sets/latest_results_judged_v3.md
```

Previous assessments are archived inside the new JSON; all original answers and deterministic scores remain unchanged. Completed v2 retrieval labels are reused; only faithfulness is reassessed. Progress is checkpointed after every question. Later resumes from the v3 JSON reuse valid v3 judgments and human assessments, retrying only pending/invalid cases. Always choose distinct output paths. Progress and final status explicitly report pending/failed judgments; `run_status=completed` alone refers to the original answer run.

Old reports that contain only IDs/distances and truncated excerpts cannot retroactively supply a top-10/context snapshot. They retain pending metrics and require a new evidence-enabled run. Existing answers are never replaced by judging. See `RAG_METRICS.md` at the repository root for formulas, coverage and the short-corpus caveat: a three-chunk supplier can score at most 30% on fixed-denominator Precision@10 even when every returned chunk is relevant. Returned-chunk precision is reported alongside it. Answer generation remains top-4 by default; top-10 is a separate retrieval audit.

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

See `QUALITY_EVALUATION.md`, `EVALUATOR_CALIBRATION.md` and `RAG_METRICS.md` for the fixed rubric, fair-stress design, validations and limits. Owner live reports are not committed; no placeholder results are committed.
