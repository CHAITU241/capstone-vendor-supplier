# Evaluator calibration and latest saved-run reassessment

Active corpus: manifest v5, scoring revision 2, `rag-evaluator-v4`. The corpus contains 15 suppliers, 45 PDFs / 73 pages, 150 questions and 135 registration/tax field checks. The separate stress cohort contains five suppliers and 50 questions. Calibration controls are tests of the grader, not model accuracy.

## Scoring corrections

The owner-provided live run `a76c7315-b13a-4d78-8d87-cf72a0df3723`, captured at `2026-10-08T07:38:39.818420+00:00`, was reassessed without model/API calls. Original JSON SHA-256: `6aa89e5ae84120f7d25911664a26c519d2626147abd85aa2e9a02645f6d2fdf2`.

| Case | Corrected grading rule | Guard retained |
|---|---|---|
| Dakshin `transit_limit` | Allow insurance page 3 for the requested storage/transit distinction | Transit page 2 remains required; unrelated pages fail |
| Amrutha `before_e2_effective` | Allow page 3 for the applicable E1 limit alongside E2 page 4 | E2 page 4, correct INR 30 lakh and 1 August 2027 remain required |
| Chitra `pickup_depot` | Allow tax page 2 corroborating the pickup location | Registration page 2 and the correct depot/address remain required |
| Amrutha `original_aggregate` | Accept a standalone currency-qualified INR 20 lakh answer | Wrong values, unqualified numbers and answers labelling another financial basis fail; explanatory answers retain annual/aggregate assertions |
| Varsha `height_without_permit` | Accept an unambiguous coverage denial without repeating the condition supplied in the question | Clause page 3 remains required; affirmative, uncertain and contradictory coverage statements fail |
| Udaya `permit_without_watch` | Same decision-only rule for this direct coverage question | Clause page 3 and an unambiguous denial remain required |

This is post-run evaluator calibration, not a held-out result. Exactly six contracts changed. Supplier identities, question wording/types, answerability, expected monetary values/dates, required primary sources, required citation-page groups, all PDF hashes and the first ten supplier records are unchanged. The original contract is preserved in `sample_documents/evaluation_sets/evaluation_manifest_v5_scoring_v1.json`. The authoring generator reproduces revision 2; no PDF regeneration was needed.

## Latest findings

The corrected **automatic strict score is 145/150 (96.67%)**, including **47/50 (94%) stress** and 98/100 core. Answer accuracy is 146/150 (97.33%), citation accuracy 118/120 (98.33%), found/not-found decisions 149/150 (99.33%), safe fallback 29/30 (96.67%), and supplier isolation 150/150. Source-scoped field checks remain 135/135.

Five cases remain failed:

- Coromandel insurer/expiry: conflicting registration evidence is additionally cited without explaining the discrepancy.
- Tungabhadra insurance diary: the requested insurer is omitted.
- Amrutha recall limit: the response substitutes a product-liability aggregate for an unsupported recall limit instead of falling back safely.
- Varsha operating site/property: the property sublimit is omitted and the relevant insurance clause is not cited.
- Chitra claims routing: `Claims Desk 2` becomes `Claims Desk at 2`, potentially changing a desk identifier into a street number. This ambiguity remains failed and requires human adjudication; no broad alias was added.

Observed Q&A latency remains average 2,780 ms, P50 2,754 ms, P95 3,952 ms and maximum 5,011 ms. Q&A token use remains 118,984. Model/prompt remain `openai/gpt-4o-mini` / `rag-answer-v3`. This is correction of scoring on the same run, not evidence of model improvement.

## Verification and limits

Regression controls exercise the six actual response forms, monetary equivalents, incorrect monetary bases/values, affirmative or uncertain coverage claims, missing primary evidence, unrelated extra pages and all five retained failures. Existing independently authored controls cover all 50 stress cases, answerless/wrong-page variants, cross-supplier evidence, malformed retrieval and incomplete intake. Preflight validates all 45 PDFs and actual OCR through the backend extractor.

All answers, citations, retrieved IDs/distances, processing observations, latency and token usage are preserved in the separate offline reassessment. The source and live-latest reports are protected against overwrite. The Markdown report records scoring revision, source identity and each changed component.

All 50 stress cases remain in the **pending human semantic audit** queue, including automatic passes. Exact page identity and lexical decisions cannot prove every role/value binding, negation or inferred condition. The ambiguous routing case must not be silently converted into a pass. Supplementary insurance policy annotations remain unscored diagnostics; registration/tax extraction accuracy establishes neither insurance compliance nor supplier approval. OCR-pack Q&A latency excludes initial document upload/OCR.

Docker and provider credentials are unavailable in this authoring environment. No new live evaluation is claimed or required for a scoring-only correction. Run the documented offline reassessment locally against the saved JSON, or a fresh full evaluation if new model observations are wanted.

Validation for this commit: **351 backend tests passed** (including 52 new regression cases); full manifest/PDF/hash/actual-OCR preflight passed; whitespace checks passed. Frontend and production RAG code are unchanged.
