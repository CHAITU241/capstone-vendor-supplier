# Reproducible retrieval precision and faithfulness

The deterministic end-to-end RAG pass rate remains separate from these semantic metrics. Neither answer-term matching nor source/page validity proves relevance or claim entailment.

## Capture and assess

Every normal evaluation question requests evaluation-only evidence capture. The answering path still queries the configured top-k (default four) and distance threshold (default 0.72), embeds the question once and answers once. After answering, a separate query with the **same embedding** captures raw supplier-filtered top ten candidates without the distance cutoff. The audit is not given to the answer model. HTTP Q&A latency includes audit overhead, recorded separately in `retrieval_audit_latency_ms`; backend recorded Q&A time ends before the audit. Judge calls are post-hoc and excluded from both Q&A timing and Q&A token totals.

Full-text capture and the reviewer-authenticated judging endpoint accept only `is_evaluation=true` suppliers. Normal supplier responses do not acquire full-context snapshots. Original texts are the redacted indexed chunks, including actual OCR output; authoring transcripts are never substituted. The report also retains the exact formatted generation evidence string.

`--judge` uses the backend's existing provider. Protocol **`rag-metric-judge-v3`** has three isolated stages: relevance sees only the question and raw candidates; claim inventory sees only the question and observed answer; support assessment sees the question, observed answer, frozen inventory and actual generation context. No claim stage receives gold answers or authoring transcripts, and support never receives audit-only chunks. `EVALUATION_JUDGE_MODEL` can select another supported model/deployment; otherwise the answer model is reused and disclosed.

The inventory contains **exact answer substrings**, not model-written claim paraphrases. Code verifies they partition the entire observed answer in order, with no additions, omissions, overlap or non-whitespace gaps, and records exact character offsets. A scalar such as `INR 40,00,000` stays a single answer span interpreted through the question. The support response has a required field for each frozen claim and cannot add, remove or rewrite claims. This prevents true contextual facts that were never stated in the answer from diluting an unsupported claim. Semantic segmentation and entailment remain LLM judgments; these structural safeguards do not establish their correctness.

Relevance uses required candidate fields and backend-owned ID mapping. Each model stage has at most three attempts, a 60-second request timeout and no hidden SDK retries. Invalid schemas, answer partitions, IDs and non-verbatim support quotes are rejected with feedback. Provider failures stop the assessment. Rejected outputs, reasons, known tokens and stage latency are retained; unrecorded usage is explicitly counted. A fresh full assessment normally uses 120 relevance calls plus 121 inventory and 121 support calls, **362 calls**, excluding retries. With completed v2 relevance available, the v3 upgrade needs **242 faithfulness-stage calls** and no new retrieval judgments.

`--judge-report` assesses saved captured runs without re-answering and requires their backend records. Completed v2/v3 relevance is reused only when the evidence fingerprint, stage prompt hash and labels validate; original relevance provenance is retained. Older LLM faithfulness inventories are marked pending, not advertised as final scores. Prior assessments are archived in `metric_judgment_history`. Accepted v3 and human assessments are retained on resume. If reassessment fails, valid previous retrieval labels remain available and failed attempts/usage are recorded separately.

The source file is never overwritten. Separate output files are checkpointed after every attempted question; resume from the partially completed output with new output filenames. Historical usage is retained once, not charged again as current calls. `--metrics-from-report` recalculates saved labels without API/model requests. Compose may wait for its backend dependency, but recalculation itself does not contact it.

Judging is opt-in because it makes additional billable calls. Without it, evidence remains available and scores remain pending. A reviewer may supply human judgments using the same schema and `method=human_review`, a named reviewer and assessment time. Do not describe LLM labels as independent human validation. Inspect contradictory evidence, negation, roles, monetary bases and claim omissions against the captured text; structural validation cannot prove a judge's semantic labels are correct.

## Retrieval Precision@10

For each answerable question, mark each ranked candidate relevant only if it supplies evidence needed for that exact question, including necessary conditions or a conflicting requested value. Shared supplier identity, distance or keyword overlap alone is insufficient. Every captured candidate needs one Boolean label and rationale.

`P@10(q) = relevant candidates in the raw top ten / 10`.

The headline is the macro mean across the 120 answerable questions in a complete full-suite run. Unsupported questions have no positive evidence set and are excluded; their safe handling is separately scored. This is raw retriever quality, not precision of the four filtered chunks used to generate answers, and not answerability-classification precision.

When a supplier has only N < 10 indexed chunks, the N results are judged and the 10-N unfilled positions contribute zero. **Maximum achievable P@10 is at most N/10**: 30% for a three-chunk pack, 80%/90% for eight/nine chunks. These corpus-size effects are why the report also shows `returned_precision = relevant / returned`, supplier chunk counts and the number of short-corpus questions. No duplicate/fake chunks or invented ranks are inserted to inflate the metric. Relevance labels determine a further ceiling; N/10 is only a corpus-size upper bound.

## Faithfulness

Freeze an exact answer-span inventory before exposing any documents, then assess each independently checkable assertion. A claim is supported only if the actual generation context entails it, including qualifiers, source attribution, financial basis, address role and relevant dates/conditions. `support_kind` distinguishes explicit facts, entailed inferences, finite-context absence and unsupported claims. An inference need not appear word-for-word; quote its premises, for example conflicting recorded terms supporting a request for clarification. It may not invent precedence or change roles/amount bases.

A supported explicit/inferred claim has one or more verbatim quotes (whitespace layout ignored) referencing actual generation chunk IDs. A finite-context absence claim requires a representative quote from **every supplied context chunk** and semantic assessment that none supplies the requested fact; an empty context needs no quote. This concerns what the model received, not an assertion that the fact is absent from all uploaded documents. The judge must not reject local absence using an audit-only clause, or infer zero/absence in the real world merely from missing context. Text found only in the wider audit or an uncited original does not establish support from the context the model saw. An unsupported claim has no support quotes and a rationale.

`Faithfulness(q) = supported claims / total factual claims`.

The headline is the macro mean over asserted answers, including assertions to unsupported questions. It excludes abstentions (no factual-claim denominator); the exact safe fallback is scored separately, rather than automatically assigning abstentions 100% faithfulness. Micro claim support and the number of fully supported asserted answers are also reported with explicit denominators. Faithfulness does not establish answer completeness, real-world correctness or causal dependence on the context. Groundedness is a closely related evidence-support concept; no second independent achievement is claimed.

## Audit contract and incomplete coverage

Each question retains:

- `metric_evidence`: version, redacted question, observed answer/decision, retrieval cutoff/filter, indexed supplier chunk count, full ranked candidates, actual generation context, text hashes, embedding model and formatted generation evidence.
- `metric_judgment`: method, judge/reviewer, provider, composite and stage prompt versions/hashes, evidence hash, assessment time, model correlation flag, attempt records, separate usage/latency, relevance labels, exact answer spans/offsets and fixed claim/support-kind verdicts.
- `metric_judgment_history`: previous successful/failed assessments preserved when a saved run is reassessed. Recorded judge usage includes current and historical attempts; unrecoverable historical failure usage stays explicitly unknown.
- `evidence_metrics`: reproducible per-question arithmetic and explicit pending/not-applicable/completed status.

Snapshot validation checks complete ranks, hashes, original/page identity, supplier ownership and consistency with the recorded generation IDs. Judgment validation rejects missing/duplicate relevance labels, non-Boolean verdicts, absent claims on asserted answers, support drawn from outside generation context, invented quotes and evidence-hash mismatches. It does not substitute a semantic judge with keyword matching.

The full eligible-set score is null/N/A until all eligible judgments validate. Any partial mean is labelled **scored-subset**, with scored/eligible/pending counts. Supplier progress states completed and pending/failed counts; the final output explicitly says **INCOMPLETE** before returning nonzero if anything remains. The original RAG `run_status=completed` describes answer execution, not successful semantic judging. Failed judgments stay in the report with reasons and captured attempt data. No missing verdict becomes a pass or zero-valued claim by default. Unsupported questions and abstentions are explicitly not applicable to their respective metrics.

Reports containing only IDs/distances and truncated citation excerpts cannot acquire missing top-10/context text retroactively; they need a fresh evidence-enabled run. The latest owner report already contains complete snapshots and can be assessed under protocol v3 without regenerating answers.
