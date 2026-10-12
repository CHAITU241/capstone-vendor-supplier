# Latest evaluator calibration and evidence metrics

Active corpus: manifest v5, scoring revision 3, `rag-evaluator-v5`. It contains 15 suppliers, 45 PDFs / 73 pages, 150 questions and 135 registration/tax field checks. Calibration tests assess the grader, never model accuracy.

## Latest live run and semantic judge calibration

Owner run `819334ef-a531-4626-bed6-67bd4c616df6` (2026-10-08 11:52:05 UTC) records 145/150 deterministic passes, 99/100 core and 46/50 stress. All 150 questions executed and all 45 documents were ready. Answer checks are 147/150, citations 117/120, decisions 149/150, safe fallback 29/30, isolation 150/150 and selected fields 135/135. These observations remain unchanged.

The first captured-run GPT-4.1 assessment yielded 88 structurally accepted and 33 rejected judgments. At that stage, full Precision@10 and faithfulness were pending; subset means could not establish full-suite results. Twenty-six rejections concerned missing/duplicate/incorrect candidate IDs and seven concerned quotations outside the exact context text. Inspection of accepted labels found a faithfulness rationale using an audit-only Varsha clause and a clarification inference rejected merely because it was not explicitly stated.

Protocol **`rag-metric-judge-v2`** isolates input scopes into separate calls, requires every candidate verdict by schema, maps short IDs back to original chunk IDs in code, and retries invalid outputs with feedback at most three times per stage. Inferences quote their premises; finite-context absence audits every actual context chunk. Exact identity/text checks remain strict. Replaced v1 assessments are archived, current valid v2/human assessments can be resumed, and failures/known usage are retained. New tests exercise these real failure classes; tests do not establish the semantic correctness of future LLM judgments. The subsequent v2 run completed all 121 eligible judgments. Its 120 answerable cases record 205 relevant chunks, Precision@10 17.08% and macro returned-chunk precision 45.06%. Relevance can be retained with its provenance; its unanchored faithfulness denominator is superseded by the v3 correction below. Human calibration remains separate.

## Historical deterministic grading corrections

The earlier owner live run was `e5aa6ed4-d4e3-4e8d-8762-591150096673`, captured at `2026-10-08T08:53:30.673632+00:00`. Source JSON SHA-256: `ebdf5b012cb26f74d6ff90f032f93ccb6e886de0cc0fec6c094c518b6e870410`.

| Case | Correction | Guard retained |
|---|---|---|
| Coromandel `conflict_review_note` | Recognise “these discrepancies necessitate clarification” as an explicit need for clarification | Both conflicting addresses and payment terms, both source citations, conflict acknowledgement and refusal to choose an unsupported winner remain required; negated necessity fails |
| Dakshin `dock_and_payment` | Permit tax page 2, which correctly corroborates the warehouse address | Registration pages 2 and 3 remain mandatory; tax page 1 or corroboration without primary evidence fails |

Only the Dakshin gold contract changes between scoring revisions 2 and 3. No supplier identities, questions, answerability, expected values, original bytes or primary evidence requirements change. Prior contracts are preserved in `evaluation_manifest_v5_scoring_v1.json` and `evaluation_manifest_v5_scoring_v2.json`; the authoring generator reproduces the active contract. The pinned first ten suppliers remain unchanged. The Coromandel correction is a lexical guard change, not a gold-answer edit.

## Same-run corrected findings

Offline reassessment of the recorded observations gives **145/150 (96.67%) end-to-end pass rate**, **98/100 core**, **47/50 (94%) stress**. Answer accuracy stays **147/150 (98%)**; citation accuracy becomes **117/120 (97.5%)**; decisions stay **148/150 (98.67%)**; safe fallback stays **29/30 (96.67%)**; isolation stays **150/150**; field checks stay **135/135**. Exactly two automatic pass decisions change. No model rerun or change to observed answers, citations, retrieval, latency or tokens is represented by this correction.

Five failed cases remain:

- Aravali and Coromandel insurer/expiry: the answer additionally cites a registration original with a conflicting expiry date without explaining it. These are not valid corroborating citations.
- Amrutha recall limit: a product-liability aggregate is incorrectly substituted for an absent recall-expense limit.
- Varsha operating site/property: the response abstains although the originals contain the requested site and sublimit.
- Chitra claims routing: “Claims Desk 2” becomes “Claims Desk at 2”, potentially moving a desk identifier into the street address. This ambiguity remains failed pending human judgment.

All 50 stress cases still require human semantic audit. Lexical components and page identity are not complete claim entailment or a production guarantee. The source/live latest files remain protected against offline overwrite; generated reassessments need separate paths.

## Reproducible additional metrics

Default evaluation now captures full redacted generation context and a separate raw top-ten retrieval audit, without changing the answer-generation top-k or making a second embedding call. Optional `--judge` records semantic relevance labels and atomic claim support with exact quotations, model/provider/prompt identity, context hashes and separate usage/latency. `--metrics-from-report` calculates metrics from those saved observations and judgments with no backend/model calls. Missing or invalid judgments remain pending; a partial mean is never promoted to a complete suite score. The old JSON cannot reconstruct missing top-ten results or exact context and needs a new evidence-enabled run for these metrics.

The deterministic scorer and optional semantic judge are different assessments. The model-based judge is not an independently completed human audit. Faithfulness is actual-context support, not a synonym for answer correctness. Fixed-denominator Precision@10 is limited by short supplier pools; returned precision is also shown. See `RAG_METRICS.md` for the complete contract and commands in the corpus README.

Docker and provider credentials are unavailable in this authoring environment. Local tests, source/PDF preflight, same-run offline reassessment and report recomputation can be verified without them. No live semantic scores or placeholder reports are committed.

Validation: **392 backend tests passed**; frontend production build passed; all 45 PDF/hash/actual-OCR preflight and Compose YAML/wiring checks passed. Docker execution and credentialed live semantic judging remain pending owner execution.


## Answer inventory correction: v3

The completed v2 report exposed an additional contract defect: an observed answer `INR 40,00,000` to the recall-expense question was assigned four claims, three describing document facts the answer never asserted. Those extra supported claims diluted the unsupported monetary assertion to 75%. This does not establish a valid faithfulness score.

Protocol v3 first partitions the observed answer into exact spans in a request with no document access. Code validates complete ordered coverage and stores offsets. A second request scores required fixed claim fields against the actual context and cannot create or rewrite claims. The scalar case has one claim, so an unsupported verdict produces 0/1; no final suite score is inferred from this regression fixture. Completed v2 relevance is reused with its provenance; original answers, deterministic results and prior judgments are preserved. Checkpoints permit retrying incomplete cases without repeating accepted v3 calls.

Calibration should still inspect address component inference, claim boundaries, insurance bases and the claims-routing wording. Structural tests establish the data contract, not semantic infallibility. No reference-answer tuning or automatic promotion of ambiguous verdicts is applied.
