# SourceSure AI Phase 2 Quality Evaluation

## Scope

This evaluation checks structured extraction, supplier-scoped retrieval, grounded answers, citations, not-found handling, and latency against five supplier document packs.
Each supplier has a registration form, GST registration certificate, and liability insurance certificate.
The documents contain different identities, addresses, contacts, commercial terms, activities, insurers, and policy dates.

The evaluation corpus is under `sample_documents/evaluation_sets/`.
Machine-readable ground truth is in `evaluation_manifest.json`. A live run creates `latest_results.json` and `latest_results.md`; the earlier 24-question evidence is retained as `historical_results_4_suppliers_24_questions.json`.

## Quality Fixes Evaluated

- Null-like strings such as `"null"`, `"none"`, and `"N/A"` are discarded before persistence.
- Exact document-level duplicates collapse into one canonical supplier field.
- Conflicting non-null candidates retain the preferred authoritative source and are flagged for review.
- Contact-name extraction requests only a person's name, without role or department text.
- Registration is preferred for identity, address, contact, and payment fields.
- Tax documentation is preferred for tax identifiers.
- Insurance documentation is preferred for insurer and expiry fields.
- Model-facing citation labels use stable short values such as `chunk_1`; real Chroma IDs remain internal.
- The supplier-scoped cosine-distance cutoff is `0.72` to avoid excluding relevant small-document chunks.
- The answer prompt explicitly treats the end of a policy-period range as the insurance expiry date.
- Model citation intent and validated citation output are retained in AI-run details for diagnosis.

## Evaluation Cases

Four suppliers were evaluated with nine expected canonical fields each, for 36 field checks.
The current final corpus contains ten questions per supplier (50 total):

1. Four direct factual questions: legal name, payment terms, insurer, and business activity.
2. Two paraphrased questions: trading name and registered address.
3. One date-interpretation question: liability insurance expiry.
4. One multi-fact question: insurer and expiry together.
5. Two deliberately unsupported questions: bank balance and external credit rating.

An answerable case passes only when expected answer terms, `information_found`, and an expected source citation all match.
The absent case passes only when the exact guarded not-found answer is returned with zero citations.
Citation excerpts are also checked for names belonging to other evaluation suppliers.

## Baseline Run

The first live run after canonical-field consolidation produced:

- Field accuracy: 35/36 (`97.2%`).
- End-to-end Q&A accuracy: 12/24 (`50%`).
- Citation accuracy for accepted answers: `100%`.
- Supplier-isolation accuracy: `100%`.
- Not-found accuracy: `25%` under the full case expectations.

The failures had two main causes:

- Relevant registration chunks near the old `0.65` distance limit were excluded for some payment/activity questions.
- Long UUID-based chunk IDs were unreliable model outputs; valid answers without an exactly validated citation were intentionally converted to not-found responses.

One contact name also included its job role and failed strict field comparison.

## Historical 24-question run

After the citation-label, cutoff, and extraction-prompt changes:

| Metric | Result |
|---|---:|
| Suppliers | 4 |
| PDFs | 12 |
| Canonical field checks | 36/36 (`100%`) |
| Q&A checks | 24/24 (`100%`) |
| Citation accuracy | `100%` |
| Not-found accuracy | `100%` |
| Supplier-isolation accuracy | `100%` |
| Average question latency | 2,035 ms |
| Maximum question latency | 2,439 ms |
| Total processing latency | 50,267 ms |
| Processing input/output tokens | 9,195 / 2,726 |
| Q&A input/output tokens | 16,434 / 677 |

Per-supplier results were 9/9 fields and 6/6 questions for Kaveri Flow Controls, Norwood Clinical Systems, Prithvi Sustainable Packaging, and Eastbridge Logistics.

The original Asteron pack was reprocessed as a regression case.
It passed legal name, registered address, insurance expiry, and absent bank-balance questions (`4/4`).
The previously failing expiry question returned `31 MAR 2027` with the insurance document citation.
Asteron produced eight canonical fields because its original PDFs do not explicitly state every supported field; missing values are no longer represented by literal `"null"` rows.

## Final 50-question run

The codebase is ready for the final run using five suppliers, 15 documents and 50 questions. Run it after configuring the final OpenRouter credentials. The runner creates both `latest_results.json` and the presentation-ready `latest_results.md`; do not reuse the historical 24-question figures as the final result.

## Reproduce

Start FastAPI with valid OpenRouter configuration, then run from the repository root:

```bash
docker compose run --rm --build evaluation
```

The equivalent direct Python commands are:

```powershell
.\backend\.venv\Scripts\python.exe scripts\generate_evaluation_documents.py
.\backend\.venv\Scripts\python.exe scripts\run_quality_evaluation.py
```

The runner reuses suppliers with matching names, uploads missing document categories, reprocesses documents, replaces their Chroma chunks, executes all questions, and overwrites `latest_results.json` and `latest_results.md`.

## Interpretation and Limitations

The final result demonstrates the intended demo behavior on a controlled positive corpus, but it is not a production-quality guarantee.
All documents are one-page, text-native PDFs with consistent English labels and coherent values.
The next evaluation expansion should include scanned PDFs/OCR, multi-page documents, conflicting values, missing categories, expired policies, malformed identifiers, paraphrased questions, and a larger held-out corpus.
