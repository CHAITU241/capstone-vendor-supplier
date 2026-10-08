"""Run repeatable extraction and grounded-Q&A evaluation against the live API."""

import argparse
import json
import math
import os
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "sample_documents" / "evaluation_sets" / "evaluation_manifest.json"
)
NOT_FOUND_ANSWER = "Information not found in uploaded supplier documents."


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def ratio(passed: int, total: int) -> float | None:
    return round(passed / total, 4) if total else None


def percentile(values: list[int], percentage: int) -> int | None:
    """Return a transparent nearest-rank percentile for the report."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentage / 100 * len(ordered)))
    return ordered[rank - 1]


def request_json(
    method: str,
    url: str,
    *,
    timeout: int = 60,
    **kwargs,
) -> dict | list:
    response = requests.request(method, url, timeout=timeout, **kwargs)
    if not response.ok:
        raise RuntimeError(
            f"{method} {url} returned {response.status_code}: {response.text[:500]}"
        )
    return response.json() if response.content else {}


def reviewer_headers(
    base_url: str,
    email: str | None = None,
    password: str | None = None,
) -> dict[str, str]:
    if bool(email) != bool(password):
        raise RuntimeError("Provide both reviewer email and password, or neither for demo login.")
    endpoint = "reviewer" if email else "reviewer-demo"
    payload = {"email": email, "password": password} if email else None
    session = request_json("POST", f"{base_url}/portal/auth/{endpoint}", json=payload)
    token = session.get("token") if isinstance(session, dict) else None
    if not token:
        raise RuntimeError("Reviewer authentication did not return a session token.")
    return {"Authorization": f"Bearer {token}"}


def get_or_create_supplier(base_url: str, payload: dict, headers: dict[str, str]) -> dict:
    suppliers = request_json("GET", f"{base_url}/suppliers", headers=headers)
    matches = [item for item in suppliers if item["name"] == payload["name"]]
    if matches:
        return matches[-1]
    return request_json("POST", f"{base_url}/suppliers", json=payload, headers=headers)


def ensure_documents(
    base_url: str,
    supplier_id: str,
    supplier_dir: Path,
    documents: dict[str, str],
    headers: dict[str, str],
) -> None:
    detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}", headers=headers)
    uploaded_types = {item["document_type"] for item in detail["documents"]}
    for document_type, filename in documents.items():
        if document_type in uploaded_types:
            continue
        path = supplier_dir / filename
        with path.open("rb") as handle:
            response = requests.post(
                f"{base_url}/suppliers/{supplier_id}/documents",
                data={"document_type": document_type},
                files={"file": (filename, handle, "application/pdf")},
                headers=headers,
                timeout=60,
            )
        if not response.ok:
            raise RuntimeError(
                f"Upload {path} returned {response.status_code}: {response.text[:500]}"
            )


def evaluate_fields(actual_fields: list[dict], expected_fields: dict[str, str]) -> dict:
    actual_by_name = {field["field_name"]: field for field in actual_fields}
    checks = []
    for field_name, expected_value in expected_fields.items():
        actual = actual_by_name.get(field_name)
        passed = actual is not None and normalized(expected_value) == normalized(actual["value"])
        checks.append(
            {
                "field_name": field_name,
                "passed": passed,
                "expected": expected_value,
                "actual": actual["value"] if actual else None,
                "needs_review": actual["needs_review"] if actual else None,
            }
        )
    return {
        "passed": sum(item["passed"] for item in checks),
        "total": len(checks),
        "checks": checks,
    }


def evaluate_question(
    base_url: str,
    supplier_id: str,
    case: dict,
    other_supplier_names: list[str],
    headers: dict[str, str],
) -> dict:
    started = time.perf_counter()
    body = request_json(
        "POST",
        f"{base_url}/suppliers/{supplier_id}/questions",
        json={"question": case["question"]},
        headers=headers,
        timeout=180,
    )
    api_latency_ms = round((time.perf_counter() - started) * 1000)
    answer = normalized(body["answer"])
    expected_terms = [normalized(term) for term in case["expected_terms"]]
    answer_match = all(term in answer for term in expected_terms)
    found_match = body["information_found"] is case["information_found"]
    citation_names = {item["filename"] for item in body["citations"]}
    expected_sources = set(case["expected_sources"])
    if case["information_found"]:
        citation_match = bool(citation_names & expected_sources)
    else:
        citation_match = not citation_names and body["answer"] == NOT_FOUND_ANSWER
    isolation_text = " ".join([
        body["answer"].casefold(),
        *(item["excerpt"].casefold() for item in body["citations"]),
    ])
    isolation_match = not any(
        other_name.casefold() in isolation_text for other_name in other_supplier_names
    )
    safe_fallback_match = (
        body["information_found"] is False
        and body["answer"] == NOT_FOUND_ANSWER
        and not body["citations"]
    ) if not case["information_found"] else None
    passed = answer_match and found_match and citation_match and isolation_match
    return {
        "id": case["id"],
        "question_type": case["question_type"],
        "question": case["question"],
        "passed": passed,
        "answer_match": answer_match,
        "found_match": found_match,
        "citation_match": citation_match,
        "safe_fallback_match": safe_fallback_match,
        "isolation_match": isolation_match,
        "answer": body["answer"],
        "information_found": body["information_found"],
        "expected_information_found": case["information_found"],
        "citations": [
            {"filename": item["filename"], "page_number": item["page_number"]}
            for item in body["citations"]
        ],
        "retrieval_count": body["run"]["retrieval_count"],
        "api_latency_ms": api_latency_ms,
        "recorded_latency_ms": body["run"]["latency_ms"],
        "input_tokens": body["run"]["input_tokens"],
        "output_tokens": body["run"]["output_tokens"],
        "model": body["run"].get("model"),
        "prompt_version": body["run"].get("prompt_version"),
    }


def grouped_question_metrics(questions: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for question in questions:
        groups.setdefault(question["question_type"], []).append(question)
    output = {}
    for name, items in sorted(groups.items()):
        answerable = [item for item in items if item["expected_information_found"]]
        unsupported = [item for item in items if not item["expected_information_found"]]
        output[name] = {
            "passed": sum(item["passed"] for item in items),
            "total": len(items),
            "accuracy": ratio(sum(item["passed"] for item in items), len(items)),
            "answer_accuracy": ratio(sum(item["answer_match"] for item in items), len(items)),
            "citation_accuracy": ratio(
                sum(item["citation_match"] for item in answerable), len(answerable),
            ),
            "safe_fallback_accuracy": ratio(
                sum(item["safe_fallback_match"] is True for item in unsupported),
                len(unsupported),
            ),
        }
    return output


def build_summary(results: list[dict], elapsed_ms: int) -> dict:
    questions = [question for supplier in results for question in supplier["questions"]]
    latencies = [question["api_latency_ms"] for question in questions]
    recorded_latencies = [question["recorded_latency_ms"] for question in questions]
    retrieval_counts = [question["retrieval_count"] for question in questions]
    fields_passed = sum(item["fields"]["passed"] for item in results)
    fields_total = sum(item["fields"]["total"] for item in results)
    questions_passed = sum(question["passed"] for question in questions)
    found_questions = [question for question in questions if question["expected_information_found"]]
    not_found_questions = [question for question in questions if not question["expected_information_found"]]
    per_supplier = {
        supplier["slug"]: {
            "passed": sum(item["passed"] for item in supplier["questions"]),
            "total": len(supplier["questions"]),
            "accuracy": ratio(
                sum(item["passed"] for item in supplier["questions"]),
                len(supplier["questions"]),
            ),
        }
        for supplier in results
    }
    failures = [
        {
            "supplier": supplier["slug"],
            "id": question["id"],
            "question_type": question["question_type"],
            "answer_match": question["answer_match"],
            "found_match": question["found_match"],
            "citation_match": question["citation_match"],
            "isolation_match": question["isolation_match"],
        }
        for supplier in results
        for question in supplier["questions"]
        if not question["passed"]
    ]
    return {
        "dataset": {
            "suppliers": len(results),
            "documents": len(results) * 3,
            "questions": len(questions),
            "answerable_questions": len(found_questions),
            "safe_not_found_questions": len(not_found_questions),
            "question_types": {
                name: sum(question["question_type"] == name for question in questions)
                for name in sorted({question["question_type"] for question in questions})
            },
        },
        "fields_passed": fields_passed,
        "fields_total": fields_total,
        "field_accuracy": ratio(fields_passed, fields_total),
        "questions_passed": questions_passed,
        "questions_total": len(questions),
        "question_accuracy": ratio(questions_passed, len(questions)),
        "answer_accuracy": ratio(sum(question["answer_match"] for question in questions), len(questions)),
        "information_found_accuracy": ratio(sum(question["found_match"] for question in questions), len(questions)),
        "citation_accuracy": ratio(
            sum(question["citation_match"] for question in found_questions), len(found_questions),
        ),
        "safe_fallback_accuracy": ratio(
            sum(question["safe_fallback_match"] is True for question in not_found_questions),
            len(not_found_questions),
        ),
        "supplier_isolation_accuracy": ratio(
            sum(question["isolation_match"] for question in questions), len(questions),
        ),
        "latency_ms": {
            "average": round(statistics.mean(latencies)),
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "maximum": max(latencies),
            "average_model_recorded": round(statistics.mean(recorded_latencies)),
        },
        "tokens": {
            "input": sum(question["input_tokens"] for question in questions),
            "output": sum(question["output_tokens"] for question in questions),
            "total": sum(question["input_tokens"] + question["output_tokens"] for question in questions),
            "average_per_question": round(sum(
                question["input_tokens"] + question["output_tokens"] for question in questions
            ) / len(questions)),
        },
        "retrieval": {
            "average_chunks": round(statistics.mean(retrieval_counts), 2),
            "maximum_chunks": max(retrieval_counts),
        },
        "models": sorted({question["model"] for question in questions if question.get("model")}),
        "prompt_versions": sorted({
            question["prompt_version"] for question in questions if question.get("prompt_version")
        }),
        "by_question_type": grouped_question_metrics(questions),
        "by_supplier": per_supplier,
        "failure_count": len(failures),
        "failures": failures,
        "evaluation_elapsed_ms": elapsed_ms,
    }


def run_evaluation(
    base_url: str,
    manifest_path: Path,
    reviewer_email: str | None = None,
    reviewer_password: str | None = None,
) -> dict:
    evaluation_started = time.perf_counter()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    supplier_names = [item["create_payload"]["name"] for item in manifest["suppliers"]]
    results = []

    health = request_json("GET", f"{base_url}/health")
    if health.get("status") != "healthy":
        raise RuntimeError(f"API health check did not pass: {health}")
    headers = reviewer_headers(base_url, reviewer_email, reviewer_password)

    for entry in manifest["suppliers"]:
        supplier = get_or_create_supplier(base_url, entry["create_payload"], headers)
        supplier_id = supplier["id"]
        supplier_dir = manifest_path.parent / entry["slug"]
        ensure_documents(
            base_url,
            supplier_id,
            supplier_dir,
            entry["documents"],
            headers,
        )
        processing = request_json(
            "POST",
            f"{base_url}/suppliers/{supplier_id}/process",
            headers=headers,
            timeout=300,
        )
        detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}", headers=headers)
        field_result = evaluate_fields(
            detail["extracted_fields"], entry["expected_fields"]
        )
        question_results = []
        for case in entry["questions"]:
            question_results.append(
                evaluate_question(
                    base_url,
                    supplier_id,
                    case,
                    [name for name in supplier_names if name != entry["create_payload"]["name"]],
                    headers,
                )
            )
        results.append(
            {
                "slug": entry["slug"],
                "supplier_id": supplier_id,
                "processing": {
                    "field_count": processing["field_count"],
                    "chunk_count": processing["chunk_count"],
                    "latency_ms": processing["run"]["latency_ms"],
                    "input_tokens": processing["run"]["input_tokens"],
                    "output_tokens": processing["run"]["output_tokens"],
                    "prompt_version": processing["run"]["prompt_version"],
                },
                "fields": field_result,
                "questions": question_results,
            }
        )
        passed_questions = sum(item["passed"] for item in question_results)
        print(
            f"{entry['slug']}: fields {field_result['passed']}/{field_result['total']}, "
            f"questions {passed_questions}/{len(question_results)}",
            flush=True,
        )

    summary = build_summary(
        results,
        round((time.perf_counter() - evaluation_started) * 1000),
    )
    return {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "summary": summary,
        "suppliers": results,
    }


def percentage(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def render_markdown_report(result: dict) -> str:
    summary = result["summary"]
    dataset = summary["dataset"]
    latency = summary["latency_ms"]
    tokens = summary["tokens"]
    retrieval = summary["retrieval"]
    lines = [
        "# SourceSure AI — Controlled RAG Quality Evaluation",
        "",
        f"- Evaluated at: `{result['evaluated_at']}`",
        f"- API: `{result['base_url']}`",
        f"- Dataset: **{dataset['questions']} questions**, **{dataset['suppliers']} suppliers**, **{dataset['documents']} documents**",
        f"- Composition: {dataset['answerable_questions']} answerable and {dataset['safe_not_found_questions']} unsupported/not-found questions",
        "",
        "## Executive results",
        "",
        "| Metric | Result | Definition |",
        "|---|---:|---|",
        f"| End-to-end RAG accuracy | {summary['questions_passed']}/{summary['questions_total']} ({percentage(summary['question_accuracy'])}) | Answer, found/not-found decision, citation and supplier isolation must all pass |",
        f"| Answer accuracy | {percentage(summary['answer_accuracy'])} | All expected answer terms are present |",
        f"| Found/not-found decision accuracy | {percentage(summary['information_found_accuracy'])} | The response correctly decides whether the evidence contains the answer |",
        f"| Citation accuracy | {percentage(summary['citation_accuracy'])} | Answerable questions cite an expected source document |",
        f"| Safe fallback accuracy | {percentage(summary['safe_fallback_accuracy'])} | Unsupported questions return the exact fallback with zero citations |",
        f"| Supplier isolation | {percentage(summary['supplier_isolation_accuracy'])} | Citations contain no other evaluation supplier's name |",
        f"| Field extraction accuracy | {summary['fields_passed']}/{summary['fields_total']} ({percentage(summary['field_accuracy'])}) | Extracted canonical values equal ground truth after normalization |",
        "",
        "## RAG response latency",
        "",
        "| Average | P50 | P95 | Maximum |",
        "|---:|---:|---:|---:|",
        f"| {latency['average']} ms | {latency['p50']} ms | {latency['p95']} ms | {latency['maximum']} ms |",
        "",
        f"Model-recorded average: {latency['average_model_recorded']} ms. End-to-end API latency is used for the headline because it includes retrieval and application overhead.",
        "",
        "## Results by question type",
        "",
        "| Question type | Passed | Accuracy |",
        "|---|---:|---:|",
    ]
    for name, metrics in summary["by_question_type"].items():
        lines.append(
            f"| {name.replace('_', ' ').title()} | {metrics['passed']}/{metrics['total']} | {percentage(metrics['accuracy'])} |"
        )
    lines.extend([
        "",
        "## Results by supplier",
        "",
        "| Supplier pack | Passed | Accuracy |",
        "|---|---:|---:|",
    ])
    for name, metrics in summary["by_supplier"].items():
        lines.append(
            f"| {name.replace('_', ' ').title()} | {metrics['passed']}/{metrics['total']} | {percentage(metrics['accuracy'])} |"
        )
    lines.extend([
        "",
        "## Usage",
        "",
        f"- Input tokens: **{tokens['input']:,}**",
        f"- Output tokens: **{tokens['output']:,}**",
        f"- Total tokens: **{tokens['total']:,}**",
        f"- Average tokens per question: **{tokens['average_per_question']:,}**",
        f"- Average/max retrieved chunks: **{retrieval['average_chunks']} / {retrieval['maximum_chunks']}**",
        f"- Answer model(s): **{', '.join(summary['models']) or 'Not reported'}**",
        f"- Prompt version(s): **{', '.join(summary['prompt_versions']) or 'Not reported'}**",
        f"- Total evaluation runtime: **{summary['evaluation_elapsed_ms'] / 1000:.1f} seconds**",
        "",
        "## Failures",
        "",
    ])
    if not summary["failures"]:
        lines.append("No failed cases.")
    else:
        lines.extend([
            "| Supplier | Case | Type | Failed components |",
            "|---|---|---|---|",
        ])
        for failure in summary["failures"]:
            components = [
                name.replace("_match", "")
                for name in ("answer_match", "found_match", "citation_match", "isolation_match")
                if not failure[name]
            ]
            lines.append(
                f"| {failure['supplier']} | {failure['id']} | {failure['question_type']} | {', '.join(components)} |"
            )
    lines.extend([
        "",
        "## Method and interpretation",
        "",
        "Each question passes only when the expected answer terms, information-found decision, citation rule and cross-supplier isolation check all pass. Safe-not-found cases must return the exact guarded fallback with no citations. Latency is measured around the live HTTP request; P50 and P95 use the nearest-rank method. Token totals in this report cover the 50 Q&A calls; monetary cost should be taken from the matching Langfuse/OpenRouter usage records because pricing is provider- and model-specific.",
        "",
        "## Limitations",
        "",
        "This is a controlled synthetic regression evaluation, not a production guarantee. The corpus uses text-native, one-page English PDFs and exact expected facts. Results should be labelled as controlled evaluation results; production calibration would require a larger held-out corpus containing scans, OCR noise, multi-page evidence, conflicting values and real user paraphrases.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--reviewer-email",
        default=os.getenv("EVALUATION_REVIEWER_EMAIL"),
        help="Use credential login instead of the default reviewer-demo session.",
    )
    parser.add_argument(
        "--reviewer-password",
        default=os.getenv("EVALUATION_REVIEWER_PASSWORD"),
        help="Reviewer password; prefer the EVALUATION_REVIEWER_PASSWORD environment variable.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_MANIFEST.parent / "latest_results.json",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_MANIFEST.parent / "latest_results.md",
    )
    args = parser.parse_args()
    result = run_evaluation(
        args.base_url.rstrip("/"),
        args.manifest.resolve(),
        args.reviewer_email,
        args.reviewer_password,
    )
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.report_output.write_text(render_markdown_report(result), encoding="utf-8")
    print("summary=" + json.dumps(result["summary"]), flush=True)
    print(f"results={args.output.resolve()}", flush=True)
    print(f"report={args.report_output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
