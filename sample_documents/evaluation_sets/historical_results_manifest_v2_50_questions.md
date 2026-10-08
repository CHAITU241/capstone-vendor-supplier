# SourceSure AI — Controlled RAG Quality Evaluation

- Evaluated at: `2026-10-08T00:24:41.565110+00:00`
- API: `http://backend:8000/api`
- Dataset: **50 questions**, **5 suppliers**, **15 documents**
- Composition: 40 answerable and 10 unsupported/not-found questions

## Executive results

| Metric | Result | Definition |
|---|---:|---|
| End-to-end RAG accuracy | 45/50 (90.0%) | Answer, found/not-found decision, citation and supplier isolation must all pass |
| Answer accuracy | 90.0% | All expected answer terms are present |
| Found/not-found decision accuracy | 100.0% | The response correctly decides whether the evidence contains the answer |
| Citation accuracy | 100.0% | Answerable questions cite an expected source document |
| Safe fallback accuracy | 100.0% | Unsupported questions return the exact fallback with zero citations |
| Supplier isolation | 100.0% | Citations contain no other evaluation supplier's name |
| Field extraction accuracy | 5/45 (11.1%) | Extracted canonical values equal ground truth after normalization |

## RAG response latency

| Average | P50 | P95 | Maximum |
|---:|---:|---:|---:|
| 2269 ms | 2134 ms | 3179 ms | 3621 ms |

Model-recorded average: 2187 ms. End-to-end API latency is used for the headline because it includes retrieval and application overhead.

## Results by question type

| Question type | Passed | Accuracy |
|---|---:|---:|
| Date Interpretation | 5/5 | 100.0% |
| Direct Fact | 20/20 | 100.0% |
| Multi Fact | 5/5 | 100.0% |
| Paraphrased Fact | 5/10 | 50.0% |
| Safe Not Found | 10/10 | 100.0% |

## Results by supplier

| Supplier pack | Passed | Accuracy |
|---|---:|---:|
| Kaveri Flow Controls | 9/10 | 90.0% |
| Norwood Clinical Systems | 9/10 | 90.0% |
| Prithvi Sustainable Packaging | 9/10 | 90.0% |
| Eastbridge Logistics | 9/10 | 90.0% |
| Sahyadri Renewable Components | 9/10 | 90.0% |

## Usage

- Input tokens: **36,965**
- Output tokens: **1,428**
- Total tokens: **38,393**
- Average tokens per question: **768**
- Average/max retrieved chunks: **1.98 / 3**
- Answer model(s): **openai/gpt-4o-mini**
- Prompt version(s): **rag-answer-v3**
- Total evaluation runtime: **218.6 seconds**

## Failures

| Supplier | Case | Type | Failed components |
|---|---|---|---|
| kaveri_flow_controls | registered_address_paraphrase | paraphrased_fact | answer |
| norwood_clinical_systems | registered_address_paraphrase | paraphrased_fact | answer |
| prithvi_sustainable_packaging | registered_address_paraphrase | paraphrased_fact | answer |
| eastbridge_logistics | registered_address_paraphrase | paraphrased_fact | answer |
| sahyadri_renewable_components | registered_address_paraphrase | paraphrased_fact | answer |

## Method and interpretation

Each question passes only when the expected answer terms, information-found decision, citation rule and cross-supplier isolation check all pass. Safe-not-found cases must return the exact guarded fallback with no citations. Latency is measured around the live HTTP request; P50 and P95 use the nearest-rank method. Token totals in this report cover the 50 Q&A calls; monetary cost should be taken from the matching Langfuse/OpenRouter usage records because pricing is provider- and model-specific.

## Limitations

This is a controlled synthetic regression evaluation, not a production guarantee. The corpus uses text-native, one-page English PDFs and exact expected facts. Results should be labelled as controlled evaluation results; production calibration would require a larger held-out corpus containing scans, OCR noise, multi-page evidence, conflicting values and real user paraphrases.
