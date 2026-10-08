# SourceSure AI final controlled evaluation

The active corpus is **v5: 15 synthetic suppliers, 45 PDFs, 73 pages and 150 RAG questions**. It scores 135 source-scoped registration/tax fields across 30 originals. The 15 supplementary liability originals are RAG-only. The final five suppliers provide a separately reported 50-question stress cohort; the first ten suppliers and their evidence/questions remain pinned unchanged.

## Final stress design

| Supplier | Category | Evidence challenge | PDF pages |
|---|---|---|---:|
| Dakshin Freight Services | Logistics | Transit, storage and subcontractor limits with different bases; approved-carrier condition | 9 |
| Amrutha Meal Services | Food services | Original schedule, renewal and amendment with explicit issue/effective dates and precedence | 9 |
| Varsha Facilities Services | Facilities | Native pages plus three moderately skewed/compressed scanned inserts; helpdesk versus housekeeping; permit condition | 8 |
| Chitra Industrial Components | Manufacturing | Registered office, plant, pickup depot and insurer claims address; trading/legal names; territory exclusion | 8 |
| Udaya Equipment Maintenance | Maintenance | Acknowledgement versus repair guarantees; limit versus deductible; mandatory permit/fire-watch and electrical exclusions | 9 |

Each new supplier has ten questions: two straightforward controls, three harder retrieval/disambiguation cases, two synthesis cases, one conditional or date-sensitive case and two unsupported requests. This contributes **10 direct, 15 stress retrieval, 10 stress synthesis, 5 stress conditional and 10 safe not-found cases**.

| Full-suite question type | Count |
|---|---:|
| Direct fact | 42 |
| Paraphrased fact | 16 |
| Date interpretation | 7 |
| Multi-fact | 9 |
| Safe not-found | 30 |
| Conflict resolution | 8 |
| Scenario-based | 8 |
| Stress retrieval | 15 |
| Stress synthesis | 10 |
| Stress conditional | 5 |
| Total | 150 |

The set contains 120 answerable and 30 unsupported questions. At the default 500-token chunk size, the new packs produce eight or nine chunks per supplier, while retrieval returns at most four. Questions require no more than three distinct evidence pages, so the mandatory evidence fits within top-k. Pages contain coherent task evidence and administrative context, rather than arbitrary filler or deliberately unreadable scans. Sources, questions, reference answers and the original citation-page contracts were authored before the live run. Scoring revision 2 corrects six contracts after inspecting saved responses; this calibration is documented and is not a held-out evaluation. The aim is to test difficult supported answers, without choosing a desired score or weakening ground truth after failures.

Supported registration, tax and supplementary liability upload slots are used. Category labels describe the test scenarios; the suite does not claim complete category-specific onboarding or compliance. Intake rejections and processing failures are reported separately from RAG answer failures.

## Evaluator contract

`rag-evaluator-v4` uses the same pure scoring function for live evaluation and offline reassessment. A strict automatic RAG pass requires expected answer components, dates and applicable currency amounts; correct information-found decision; valid allowed citations and every required evidence-page group; and supplier-owned retrieved/cited chunk IDs. Existing conflict cases retain source-attributed values, mandatory source citations, conflict acknowledgement and uncertainty guards. Safe-not-found requires the exact guarded fallback with no citations.

Dates accept equivalent calendar formats, ordinals and PDF line wrapping. Currency-qualified INR amounts accept Indian/international comma grouping, lakh/crore/million equivalents and rupee symbols; wrong amounts and unqualified numbers fail. Common equivalent payment-trigger phrases are declared in the gold. Revision 2 also accepts a standalone currency-qualified amount for the original-aggregate single-value question and explicit coverage denials for the two decision-only conditions. It rejects wrong monetary bases, affirmative coverage, uncertain decisions and contradictory coverage assertions. Source names and financial roles remain distinct. Extra corroborating citations are allowed only on declared pages containing relevant facts; required primary evidence remains mandatory.

Stress citation rules check clause pages, rather than treating any page of the correct file as sufficient. The API returns only the first 280 characters of each cited chunk as a UI excerpt, so the evaluator does not demand every answer fact appear in that truncated excerpt. Document, page, retrieved-chunk and supplier identity are checked; full claim entailment is audited against originals.

**Every stress response requires human review, including automatic passes.** The JSON contains a review queue with reference, observed answer, page requirements and gold rationale. Markdown includes the checklist. Audit attribution of roles and values, date-sensitive precedence, all conditions/exclusions and absence claims. An automatic component score is not a completed semantic audit; the report marks reviews pending until separately documented. Preserve the automatic score and publish an audited stress score separately, linked to the original run identity/hash. Do not reinterpret lexical matching as proof of semantic correctness.

## Timing and scope

| Measurement | Includes | Excludes |
|---|---|---|
| Upload HTTP | Transfer, native reading/OCR, upload validation and persistence | Subsequent indexing and Q&A |
| Processing HTTP / recorded processing | Redaction, chunks, embeddings, model extraction and API overhead as applicable | OCR already performed during upload; subsequent Q&A |
| Q&A HTTP | Retrieval, answer model and application overhead | Initial upload/OCR and indexing |

OCR-only duration is not separately instrumented. The report never calls OCR-pack Q&A latency the time needed to read a newly uploaded scan. P50/P95 use nearest rank; Q&A tokens are reported separately from processing usage. Provider billing remains the authority for monetary cost.

The field denominator is **135 registration/tax policy fields**, not full supplier compliance. Supplementary liability model policy annotations can contain inconsistent missing-field, duration or fictional-evidence statements; they remain visible as **unscored diagnostics**. They establish neither scored insurance compliance nor supplier approval. Production model prompts, allow-lists and human approval gates are unchanged by this evaluation commit.

## Execute and record

```bash
git pull --ff-only origin supplier-rag-feature
docker compose up -d --build backend
docker compose run --rm --build evaluation --validate-only
docker compose run --rm --build evaluation
```

Configure the provider in `backend/.env`. Reviewer-demo authentication is used unless both reviewer credential environment variables are supplied. The evaluation image contains Python dependencies, the script and English Tesseract; Compose mounts corpus/reports and targets the healthy backend over its internal network.

The host report paths are `sample_documents/evaluation_sets/latest_results.json` and `sample_documents/evaluation_sets/latest_results.md`. Existing report bytes are archived before replacement. Validation-only and calibration tests never write model scores. Upload failures yield an **incomplete** report with unexecuted RAG questions and a nonzero CLI status; skipped questions are not scored as wrong model answers. A crash during Q&A leaves the previous final report intact rather than publishing a fabricated complete run.

For the new cohort alone, use `--cohort stress` and explicit `stress_results.json`/`stress_results.md` paths as shown in the corpus README. Core and stress results are separately grouped in addition to overall, per-type, per-supplier and per-cohort metrics. Scores across different manifest/evaluator versions do not establish like-for-like model improvement.

Fresh runs create new suppliers marked `is_evaluation=true`, verify uploaded original hashes and require complete forced processing refresh. Evaluation suppliers are excluded from the reviewer worklist and its displayed counts. Their records, originals and ID-based evaluation APIs remain available; owner administration retains the records. Migration `0022_evaluation_suppliers` marks existing evaluator-created rows only when the exact pinned name/contact pair, India country and absent portal account/category match. Similar names or example-domain contacts alone are not sufficient. Rebuild/start the backend after pulling so the startup migration removes existing test records from the reviewer list. The runner stops if the backend does not acknowledge the marker. OCR preflight exercises the actual backend extraction routine; live verification requires the declared scanned page numbers and `ocr`/`mixed` method metadata. Scanned authoring transcripts validate gold only and are never uploaded. PDF checksums are exact; transcript checksums tolerate only Windows newline conversion.

The pinned v4 manifest permits offline reassessment of the captured 100-question owner run with explicit `--manifest sample_documents/evaluation_sets/baseline_manifest_v4.json`. It cannot supply answers to the new v5 questions. Source hashes, model observations, retrieval, tokens and latencies remain unchanged during reassessment; outputs must be distinct from the source/live latest files.

## Closure status and limits

The owner's complete 150-question live run has been reassessed with scoring revision 2: **145/150 (96.67%) strict automatic accuracy**, including **47/50 (94%) stress**. Exactly six evaluator false negatives were corrected; five failures remain. No model calls or source observations changed. All 50 stress semantic reviews remain pending. See `EVALUATOR_CALIBRATION.md` for the exact rules, provenance and retained failures.

This is a bounded controlled stress evaluation, not an absolute production guarantee. It covers multi-page English evidence, moderate skew/compression, mixed OCR, explicit temporal precedence, address roles and conditions. It does not cover severe scan damage, handwriting, exhaustive injection/leakage attacks, arbitrary citation entailment or independently sampled real-world supplier records. A final live run plus review of all 50 stress answers closes the evaluation; a lower genuine model score is an acceptable finding.

## Reassess the saved 150-question run

After pulling this commit, use distinct output paths to preserve the original JSON and live-latest reports:

```bash
docker compose run --rm --build evaluation \
  --rescore /app/sample_documents/evaluation_sets/latest_results.json \
  --output /app/sample_documents/evaluation_sets/rescored_results_v4.json \
  --report-output /app/sample_documents/evaluation_sets/rescored_results_v4.md
```

This command scores the saved observations against the current rubric; it does not request new model answers. The JSON and Markdown outputs appear in the mounted host evaluation directory. Keep the original report with the corrected report for project records. The active v5 corpus must match every original document hash and question identity in the source run.
