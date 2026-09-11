"""Run repeatable extraction and grounded-Q&A evaluation against the live API."""

import argparse
import json
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


def get_or_create_supplier(base_url: str, payload: dict) -> dict:
    suppliers = request_json("GET", f"{base_url}/suppliers")
    matches = [item for item in suppliers if item["name"] == payload["name"]]
    if matches:
        return matches[-1]
    return request_json("POST", f"{base_url}/suppliers", json=payload)


def ensure_documents(
    base_url: str,
    supplier_id: str,
    supplier_dir: Path,
    documents: dict[str, str],
) -> None:
    detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}")
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
) -> dict:
    started = time.perf_counter()
    body = request_json(
        "POST",
        f"{base_url}/suppliers/{supplier_id}/questions",
        json={"question": case["question"]},
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
    citation_text = " ".join(item["excerpt"].casefold() for item in body["citations"])
    isolation_match = not any(
        other_name.casefold() in citation_text for other_name in other_supplier_names
    )
    passed = answer_match and found_match and citation_match and isolation_match
    return {
        "id": case["id"],
        "question": case["question"],
        "passed": passed,
        "answer_match": answer_match,
        "found_match": found_match,
        "citation_match": citation_match,
        "isolation_match": isolation_match,
        "answer": body["answer"],
        "information_found": body["information_found"],
        "citations": [
            {"filename": item["filename"], "page_number": item["page_number"]}
            for item in body["citations"]
        ],
        "retrieval_count": body["run"]["retrieval_count"],
        "api_latency_ms": api_latency_ms,
        "recorded_latency_ms": body["run"]["latency_ms"],
        "input_tokens": body["run"]["input_tokens"],
        "output_tokens": body["run"]["output_tokens"],
    }


def run_evaluation(base_url: str, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    supplier_names = [item["create_payload"]["name"] for item in manifest["suppliers"]]
    results = []

    health = request_json("GET", f"{base_url}/health")
    if health.get("status") != "healthy":
        raise RuntimeError(f"API health check did not pass: {health}")

    for entry in manifest["suppliers"]:
        supplier = get_or_create_supplier(base_url, entry["create_payload"])
        supplier_id = supplier["id"]
        supplier_dir = manifest_path.parent / entry["slug"]
        ensure_documents(
            base_url,
            supplier_id,
            supplier_dir,
            entry["documents"],
        )
        processing = request_json(
            "POST",
            f"{base_url}/suppliers/{supplier_id}/process",
            timeout=300,
        )
        detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}")
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

    questions = [question for supplier in results for question in supplier["questions"]]
    latencies = [question["api_latency_ms"] for question in questions]
    fields_passed = sum(item["fields"]["passed"] for item in results)
    fields_total = sum(item["fields"]["total"] for item in results)
    questions_passed = sum(question["passed"] for question in questions)
    found_questions = [question for question in questions if question["information_found"]]
    not_found_questions = [question for question in questions if not question["information_found"]]
    summary = {
        "suppliers": len(results),
        "fields_passed": fields_passed,
        "fields_total": fields_total,
        "field_accuracy": round(fields_passed / fields_total, 4),
        "questions_passed": questions_passed,
        "questions_total": len(questions),
        "question_accuracy": round(questions_passed / len(questions), 4),
        "citation_accuracy": round(
            sum(question["citation_match"] for question in found_questions)
            / len(found_questions),
            4,
        ),
        "not_found_accuracy": round(
            sum(question["passed"] for question in not_found_questions)
            / len(not_found_questions),
            4,
        ),
        "supplier_isolation_accuracy": round(
            sum(question["isolation_match"] for question in questions)
            / len(questions),
            4,
        ),
        "average_question_latency_ms": round(statistics.mean(latencies)),
        "maximum_question_latency_ms": max(latencies),
    }
    return {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "summary": summary,
        "suppliers": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_MANIFEST.parent / "latest_results.json",
    )
    args = parser.parse_args()
    result = run_evaluation(args.base_url.rstrip("/"), args.manifest.resolve())
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("summary=" + json.dumps(result["summary"]), flush=True)
    print(f"results={args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
