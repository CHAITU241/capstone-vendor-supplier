# Reproducible retrieval precision and faithfulness

The deterministic end-to-end RAG pass rate remains separate from these semantic metrics. Neither answer-term matching nor source/page validity proves relevance or claim entailment.

## Capture and assess

Every normal evaluation question requests evaluation-only evidence capture. The answering path still queries the configured top-k (default four) and distance threshold (default 0.72), embeds the question once and answers once. After answering, a separate query with the **same embedding** captures raw supplier-filtered top ten candidates without the distance cutoff. The audit is not given to the answer model. HTTP Q&A latency includes audit overhead, recorded separately in `retrieval_audit_latency_ms`; backend recorded Q&A time ends before the audit. Judge calls are post-hoc and excluded from both Q&A timing and Q&A token totals.

Full-text capture and the reviewer-authenticated judging endpoint accept only `is_evaluation=true` suppliers. Normal supplier responses do not acquire full-context snapshots. Original texts are the redacted indexed chunks, including actual OCR output; authoring transcripts are never substituted. The report also retains the exact formatted generation evidence string.

`--judge` requests one structured semantic assessment per eligible question through the backend's existing provider. `EVALUATION_JUDGE_MODEL` can select another supported model/deployment; otherwise the answer model is reused, explicitly disclosed. `--judge-report` performs the same assessment on saved captured runs without re-answering. It requires their backend run/supplier records. A saved report with completed judgments is self-contained for `--metrics-from-report`: no API/model request is made by the script. Compose may start/wait for its backend dependency, but the recalculation itself does not contact it.

Judging is opt-in because it makes additional billable calls. Without it, evidence remains available and scores remain pending. A reviewer may supply human judgments using the same schema and `method=human_review`, a named reviewer and assessment time. Do not describe LLM labels as independent human validation. Inspect contradictory evidence, negation, roles, monetary bases and claim omissions against the captured text; structural validation cannot prove a judge's semantic labels are correct.

## Retrieval Precision@10

For each answerable question, mark each ranked candidate relevant only if it supplies evidence needed for that exact question, including necessary conditions or a conflicting requested value. Shared supplier identity, distance or keyword overlap alone is insufficient. Every captured candidate needs one Boolean label and rationale.

`P@10(q) = relevant candidates in the raw top ten / 10`.

The headline is the macro mean across the 120 answerable questions in a complete full-suite run. Unsupported questions have no positive evidence set and are excluded; their safe handling is separately scored. This is raw retriever quality, not precision of the four filtered chunks used to generate answers, and not answerability-classification precision.

When a supplier has only N < 10 indexed chunks, the N results are judged and the 10-N unfilled positions contribute zero. **Maximum achievable P@10 is at most N/10**: 30% for a three-chunk pack, 80%/90% for eight/nine chunks. These corpus-size effects are why the report also shows `returned_precision = relevant / returned`, supplier chunk counts and the number of short-corpus questions. No duplicate/fake chunks or invented ranks are inserted to inflate the metric. Relevance labels determine a further ceiling; N/10 is only a corpus-size upper bound.

## Faithfulness

Split each asserted answer into all atomic factual claims. A claim is supported only if the actual generation context entails it, including qualifiers, source attribution, financial basis, address role and relevant dates/conditions. A supported claim has one or more verbatim quotes (whitespace layout ignored) referencing actual generation chunk IDs. Text found only in the wider audit or an uncited original does not establish support from the context the model saw. An unsupported claim has no support quotes and a rationale.

`Faithfulness(q) = supported claims / total factual claims`.

The headline is the macro mean over asserted answers, including assertions to unsupported questions. It excludes abstentions (no factual-claim denominator); the exact safe fallback is scored separately, rather than automatically assigning abstentions 100% faithfulness. Micro claim support and the number of fully supported asserted answers are also reported with explicit denominators. Faithfulness does not establish answer completeness, real-world correctness or causal dependence on the context. Groundedness is a closely related evidence-support concept; no second independent achievement is claimed.

## Audit contract and incomplete coverage

Each question retains:

- `metric_evidence`: version, redacted question, observed answer/decision, retrieval cutoff/filter, indexed supplier chunk count, full ranked candidates, actual generation context, text hashes, embedding model and formatted generation evidence.
- `metric_judgment`: method, judge/reviewer, provider, prompt version/hash, evidence hash, assessment time, model correlation flag, separate usage/latency, relevance labels and atomic claim/support verdicts.
- `evidence_metrics`: reproducible per-question arithmetic and explicit pending/not-applicable/completed status.

Snapshot validation checks complete ranks, hashes, original/page identity, supplier ownership and consistency with the recorded generation IDs. Judgment validation rejects missing/duplicate relevance labels, non-Boolean verdicts, absent claims on asserted answers, support drawn from outside generation context, invented quotes and evidence-hash mismatches. It does not substitute a semantic judge with keyword matching.

The full eligible-set score is null/N/A until all eligible judgments validate. Any partial mean is labelled **scored-subset**, with scored/eligible/pending counts. Failed judgments stay in the report with reasons, and a requested judging run returns nonzero while preserving observations. No missing verdict becomes a pass or zero-valued claim by default. Unsupported questions and abstentions are explicitly not applicable to their respective metrics.

The owner report captured before this change can be rescored for the two deterministic grading corrections, but it cannot acquire missing top-10 rankings and exact context retroactively. A new evidence-enabled run is necessary for these new metrics.
