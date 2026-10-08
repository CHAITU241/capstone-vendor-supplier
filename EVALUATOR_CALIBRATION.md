# Final evaluator calibration record

The active package is manifest v5 with `rag-evaluator-v3`. Reference controls calibrate the rubric; they are not live RAG results.

- Five new supplier packs, 15 PDFs, 43 pages and 50 questions are pinned with independently authored reference answers and evidence-page requirements. The full corpus is 15 suppliers / 45 PDFs / 73 pages / 150 questions.
- All 50 correct reference-answer/citation controls pass the shared rubric. Forty answerable cases each have answerless and wrong-page controls that fail. Wrong/missing evidence pages, duplicate/malformed retrieval IDs and cross-supplier IDs fail their respective components.
- Equivalent INR formatting and units pass; wrong monetary values, decimal mismatches and unqualified numbers fail. Equivalent dates, ordinals and line wrapping pass; wrong dates fail. Declared phrase alternatives accept common equivalent payment-trigger wording.
- Actual backend OCR opens the mixed documents and exercises precisely page 2. All three scanned inserts remain readable, without a poor-quality rejection status. Actual redaction/chunking yields one chunk per page and eight or nine per new supplier; mandatory evidence fits within top-k four.
- The first ten supplier records, PDF hashes, questions and extraction contracts match pinned v4 unchanged. Replay of the owner's saved 100 responses retains 99 strict passes and the genuine insurance-citation failure, with source JSON bytes unchanged. This replay is not a new model run.
- Upload/OCR, processing and Q&A timing fields are separate. Supplementary liability annotations are explicitly unscored. A mocked intake rejection yields an incomplete pipeline report with zero executed questions, no wrong-answer failures and no invented accuracy.
- Every stress answer is marked for human audit. Lexical component checks and page identity cannot guarantee correct role/value binding, scope, negation or every inferred condition. Pending review is visible in both JSON and Markdown.

Validation: 299 backend tests passed; frontend production build passed; manifest/PDF/hash/actual-OCR checks and static Compose/Docker wiring checks. All 43 new PDF pages were rendered and inspected for readable, unclipped content. Docker and provider credentials are unavailable in the authoring environment, so Docker configuration execution and the live v5 model run must be performed on the owner's machine.

The automated test suite is the repeatable calibration source (`backend/tests/test_stress_quality_evaluation.py`, the pinned v4 evaluator tests and existing backend regressions). Do not treat a passing calibration suite as 100% RAG accuracy or as proof that no future evaluator issue can exist.
