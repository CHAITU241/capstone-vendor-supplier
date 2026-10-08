"""Run repeatable extraction and grounded-Q&A evaluation against the live API."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
import uuid
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


def dates_in(value: str) -> set[str]:
    """Accept equivalent calendar dates without accepting a different date."""
    patterns = (
        (r"\b\d{4}-\d{1,2}-\d{1,2}\b", ("%Y-%m-%d",)),
        (r"\b\d{1,2}[ /-][A-Za-z]{3,9}[ ,/-]+\d{4}\b", ("%d %b %Y", "%d %B %Y")),
        (r"\b[A-Za-z]{3,9} \d{1,2},? \d{4}\b", ("%b %d %Y", "%B %d %Y")),
        (r"\b\d{1,2}/\d{1,2}/\d{4}\b", ("%d/%m/%Y",)),
    )
    dates = set()
    for pattern, formats in patterns:
        for match in re.findall(pattern, value):
            candidate = re.sub(r"[ ,/-]+", " ", match).strip() if any("%b" in fmt or "%B" in fmt for fmt in formats) else match
            for fmt in formats:
                try:
                    dates.add(datetime.strptime(candidate, fmt).date().isoformat())
                    break
                except ValueError:
                    continue
    return dates


def answer_matches(answer: str, case: dict) -> bool:
    return (
        all(normalized(term) in normalized(answer) for term in case["expected_terms"])
        and all(any(normalized(term) in normalized(answer) for term in group) for group in case.get("expected_term_groups", []))
        and set(case.get("expected_dates", [])) <= dates_in(answer)
    )


def conflict_checks(answer: str, case: dict) -> dict[str, bool | None]:
    """Predeclared lexical guards, not an assertion of semantic entailment."""
    value = normalized(answer)
    acknowledgement = bool(re.search(r"\b(conflict\w*|disagree\w*|different|differ\w*|inconsisten\w*|discrepan\w*|mismatch\w*)\b", value))
    uncertainty = bool(re.search(
        r"\b(unclear|unresolved|insufficient|unconfirmed)\b|"
        r"\b(cannot|can t|unable to)\b.{0,55}\b(confirm|determine|establish|choose|verify)\b|"
        r"\b(not|no|neither)\b.{0,35}\b(confirmed|established|precedence|definitive|authoritative|confirmation)\b|"
        r"\b(clarif\w*|confirm\w*|verif\w*)\b.{0,35}\b(required|needed|necessary)\b|"
        r"\b(need\w*|require\w*|should|must)\b.{0,55}\b(clarif\w*|confirm\w*|verif\w*)\b",
        value,
    ))
    return {
        "conflict_match": acknowledgement if case.get("requires_conflict_acknowledgement") else None,
        "uncertainty_match": uncertainty if case.get("requires_uncertainty") else None,
    }


def validate_manifest(manifest_path: Path) -> dict:
    """Fail before API calls when the local corpus or extraction contract drifts."""
    import pymupdf

    sys.path.insert(0, str(ROOT / "backend" if (ROOT / "backend").is_dir() else ROOT))
    from app.models import DocumentType
    from app.services.document_policy import extraction_field_names

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if version not in (3, 4):
        raise ValueError("Use a policy-aligned version-3 or expanded version-4 manifest.")
    suppliers = manifest["suppliers"]
    expected_suppliers = 5 if version == 3 else 10
    if len(suppliers) != expected_suppliers or len({s["slug"] for s in suppliers}) != expected_suppliers:
        raise ValueError(f"The evaluation requires {expected_suppliers} distinct supplier packs.")
    type_counts = {}
    paths = set()
    for entry in suppliers:
        source_texts = {}
        documents = entry["documents"]
        expectations = entry["extraction_expectations"]
        rag_only = entry["rag_only_documents"]
        if len(documents) != 3 or set(expectations) & set(rag_only) or set(documents) != set(expectations) | set(rag_only):
            raise ValueError(f"Every document needs an extraction contract or an explicit RAG-only scope: {entry['slug']}")
        for kind, filename in documents.items():
            path = (manifest_path.parent / entry["slug"] / filename).resolve()
            if not path.is_relative_to(manifest_path.parent.resolve()):
                raise ValueError("Evaluation document path escapes the corpus.")
            paths.add(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["document_sha256"][kind]:
                raise ValueError(f"PDF checksum mismatch: {path}")
            mode = entry.get("document_modes", {}).get(kind, "native")
            with pymupdf.open(path) as doc:
                if not doc.is_pdf or doc.is_encrypted or not doc.page_count:
                    raise ValueError(f"Unreadable evaluation PDF: {path}")
                if mode == "ocr":
                    if any(page.get_text().strip() or not page.get_images() for page in doc):
                        raise ValueError(f"OCR original must contain only scanned page images: {path}")
                    transcript = path.with_suffix(".source.txt")
                    # Git may check out text as CRLF on Windows. The pinned
                    # transcript uses LF; tolerate only that newline conversion.
                    transcript_bytes = transcript.read_bytes().replace(b"\r\n", b"\n")
                    if hashlib.sha256(transcript_bytes).hexdigest() != entry["source_transcript_sha256"][kind]:
                        raise ValueError(f"OCR authoring transcript checksum mismatch: {path}")
                    source_text = transcript.read_text(encoding="utf-8")
                    # Exercise the deployed extraction routine. Recognition mistakes
                    # are scored live, not silently repaired from the transcript.
                    from app.config import Settings
                    from app.services.documents import extract_document_text
                    extracted = extract_document_text(path, "application/pdf", Settings())
                    if extracted.text_extraction_method != "ocr" or not extracted.text.strip():
                        raise ValueError(f"OCR preflight did not exercise scanned pages: {path}")
                elif mode == "native" and all(page.get_text().strip() for page in doc):
                    source_text = " ".join(page.get_text() for page in doc)
                else:
                    raise ValueError(f"Unreadable or unknown document mode: {path}")
            allowed = set(extraction_field_names(DocumentType(kind)))
            source_texts[filename] = source_text
            if kind in expectations:
                if not expectations[kind] or set(expectations[kind]) != allowed:
                    raise ValueError(f"Extraction ground truth must cover the current policy fields: {entry['slug']}/{kind}")
                for name, value in expectations[kind].items():
                    present = value in dates_in(source_text) if name.endswith("_date") else normalized(value) in normalized(source_text)
                    if not present:
                        raise ValueError(f"Extraction ground truth absent from source PDF: {entry['slug']}/{kind}/{name}")
            elif allowed or not rag_only[kind]:
                raise ValueError(f"RAG-only exclusion conflicts with current extraction policy: {kind}")
        if len(entry["questions"]) != 10 or len({q["id"] for q in entry["questions"]}) != 10:
            raise ValueError("Each supplier requires ten distinct questions.")
        for case in entry["questions"]:
            kind = case["question_type"]
            type_counts[kind] = type_counts.get(kind, 0) + 1
            if case["information_found"]:
                if not case["expected_sources"] or not (case["expected_terms"] or case.get("expected_dates")):
                    raise ValueError("Answerable cases require evidence and answer assertions.")
                if not set(case["expected_sources"]) <= set(documents.values()):
                    raise ValueError("Question cites an unknown corpus document.")
                if not set(case.get("required_sources", [])) <= set(case["expected_sources"]):
                    raise ValueError("Required citations must be allowed source documents.")
                evidence = " ".join(source_texts[name] for name in case["expected_sources"])
                if any(normalized(term) not in normalized(evidence) for term in case["expected_terms"]) or not set(case.get("expected_dates", [])) <= dates_in(evidence):
                    raise ValueError(f"Question ground truth absent from declared sources: {entry['slug']}/{case['id']}")
                if kind == "conflict_resolution" and (
                    len(case.get("required_sources", [])) < 2
                    or not case.get("requires_conflict_acknowledgement")
                    or not case.get("requires_uncertainty")
                ):
                    raise ValueError("Conflicting evidence requires both sources, conflict acknowledgement and uncertainty.")
            elif kind != "safe_not_found" or case["expected_sources"] or case["expected_terms"] != [NOT_FOUND_ANSWER]:
                raise ValueError("Unsupported cases require the exact guarded fallback and no sources.")
            for expected_date in case.get("expected_dates", []):
                datetime.strptime(expected_date, "%Y-%m-%d")
        ground_truth = manifest_path.parent / entry["slug"] / "ground_truth.json"
        if json.loads(ground_truth.read_text(encoding="utf-8")) != entry:
            raise ValueError(f"Supplier ground truth differs from combined manifest: {entry['slug']}")
    counts = ({"documents":15, "questions":50, "question_types":{"direct_fact":20,"paraphrased_fact":10,"date_interpretation":5,"multi_fact":5,"safe_not_found":10}}
              if version == 3 else {"documents":30, "questions":100, "question_types":{"direct_fact":32,"paraphrased_fact":16,"date_interpretation":7,"multi_fact":9,"safe_not_found":20,"conflict_resolution":8,"scenario_based":8}})
    if len(paths) != counts["documents"] or type_counts != counts["question_types"]:
        raise ValueError("Corpus document/question counts differ from the pinned evaluation contract.")
    if version == 4:
        cohorts = {name:sum(s.get("cohort", "baseline") == name for s in suppliers) for name in ("baseline", "ocr", "conflicting_evidence", "scenario_questions")}
        if cohorts != {"baseline":5,"ocr":2,"conflicting_evidence":2,"scenario_questions":1}:
            raise ValueError("Expanded evaluation requires 5 baseline, 2 OCR, 2 conflict and 1 scenario supplier.")
        if any(set(s.get("document_modes", {}).values()) != {"ocr"} or len(s["document_modes"]) != 3 for s in suppliers if s.get("cohort") == "ocr"):
            raise ValueError("Both OCR supplier packs require three image-only originals.")
        if manifest.get("expected_counts") != {"suppliers":10, **counts}:
            raise ValueError("Declared expected counts differ from the pinned v4 contract.")
    return manifest


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


def create_evaluation_supplier(base_url: str, payload: dict, headers: dict[str, str]) -> dict:
    # Preserve existing suppliers, uploads and reviewer state. Each run owns new IDs.
    return request_json("POST", f"{base_url}/suppliers", json=payload, headers=headers)


def ensure_documents(
    base_url: str,
    supplier_id: str,
    supplier_dir: Path,
    documents: dict[str, str],
    headers: dict[str, str],
    document_sha256: dict[str, str],
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
    detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}", headers=headers)
    for kind, filename in documents.items():
        matches = [doc for doc in detail["documents"] if doc["document_type"] == kind]
        if len(matches) != 1 or matches[0].get("sha256") != document_sha256[kind]:
            raise RuntimeError(f"Backend original differs from the evaluated corpus: {filename}")


def evaluate_fields(detail: dict, expectations: dict[str, dict[str, str]]) -> dict:
    checks = []
    for kind, expected_fields in expectations.items():
        document = next(doc for doc in detail["documents"] if doc["document_type"] == kind)
        for field_name, expected_value in expected_fields.items():
            matches = [field for field in detail["extracted_fields"] if field["document_id"] == document["id"] and field["field_name"] == field_name]
            actual = matches[0] if len(matches) == 1 else None
            value = actual["value"] if actual else None
            passed = value is not None and (
                dates_in(value) == {expected_value} if field_name.endswith("_date")
                else normalized(expected_value) == normalized(value)
            )
            checks.append({
                "document_type": kind,
                "document_id": document["id"],
                "field_name": field_name,
                "passed": passed,
                "expected": expected_value,
                "actual": value,
                "needs_review": actual["needs_review"] if actual else None,
                "duplicate_count": len(matches) if len(matches) > 1 else 0,
            })
    return {
        "passed": sum(item["passed"] for item in checks),
        "total": len(checks),
        "checks": checks,
    }


def verify_ocr_execution(entry: dict, documents: list[dict]) -> None:
    if entry.get("cohort") != "ocr":
        return
    if len(documents) != len(entry["documents"]) or any(
        doc.get("text_extraction_method") != "ocr"
        or doc.get("ocr_pages") != list(range(1, doc["page_count"] + 1))
        for doc in documents
    ):
        raise RuntimeError("Scanned originals did not pass through backend OCR. Enable OCR and rebuild the backend before evaluation.")


def evaluate_question(
    base_url: str,
    supplier_id: str,
    case: dict,
    other_supplier_names: list[str],
    headers: dict[str, str],
    documents: list[dict],
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
    answer_match = answer_matches(body["answer"], case)
    found_match = body["information_found"] is case["information_found"]
    citation_names = {item["filename"] for item in body["citations"]}
    expected_sources = set(case["expected_sources"])
    if case["information_found"]:
        citation_match = (bool(citation_names) and citation_names <= expected_sources
                          and set(case.get("required_sources", [])) <= citation_names)
    else:
        citation_match = not citation_names and body["answer"] == NOT_FOUND_ANSWER
    isolation_text = " ".join([
        body["answer"].casefold(),
        *(item["excerpt"].casefold() for item in body["citations"]),
    ])
    isolation_match = not any(
        other_name.casefold() in isolation_text for other_name in other_supplier_names
    )
    documents_by_id = {doc["id"]: doc for doc in documents}
    retrieved_ids = body["run"].get("details", {}).get("retrieved_chunk_ids", [])
    def belongs_to_supplier(chunk_id: str) -> bool:
        parts = chunk_id.split(":")
        return len(parts) == 3 and parts[0] == supplier_id and parts[1] in documents_by_id

    isolation_match = (
        isolation_match
        and len(retrieved_ids) == body["run"]["retrieval_count"]
        and all(belongs_to_supplier(cid) for cid in retrieved_ids)
    )
    for citation in body["citations"]:
        chunk_id = citation["chunk_id"]
        owned = belongs_to_supplier(chunk_id)
        isolation_match = isolation_match and owned
        if not owned:
            citation_match = False
            continue
        document = documents_by_id[chunk_id.split(":")[1]]
        citation_match = citation_match and (
            chunk_id in retrieved_ids
            and document["filename"] == citation["filename"]
            and 1 <= citation["page_number"] <= document["page_count"]
        )
    safe_fallback_match = (
        body["information_found"] is False
        and body["answer"] == NOT_FOUND_ANSWER
        and not body["citations"]
    ) if not case["information_found"] else None
    conflict = conflict_checks(body["answer"], case)
    passed = answer_match and found_match and citation_match and isolation_match and all(value is not False for value in conflict.values())
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
        **conflict,
        "answer": body["answer"],
        "expected_terms": case["expected_terms"],
        "expected_dates": case.get("expected_dates", []),
        "expected_term_groups": case.get("expected_term_groups", []),
        "expected_sources": case["expected_sources"],
        "required_sources": case.get("required_sources", []),
        "gold_rationale": case.get("gold_rationale"),
        "information_found": body["information_found"],
        "expected_information_found": case["information_found"],
        "citations": [
            {"chunk_id": item["chunk_id"], "filename": item["filename"], "page_number": item["page_number"], "excerpt": item["excerpt"]}
            for item in body["citations"]
        ],
        "retrieval_count": body["run"]["retrieval_count"],
        "retrieved_chunk_ids": retrieved_ids,
        "retrieval_distances": body["run"].get("details", {}).get("retrieval_distances", []),
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
            "conflict_match": question.get("conflict_match"),
            "uncertainty_match": question.get("uncertainty_match"),
        }
        for supplier in results
        for question in supplier["questions"]
        if not question["passed"]
    ]
    field_failures = [
        {"supplier": supplier["slug"], **check}
        for supplier in results
        for check in supplier["fields"].get("checks", [])
        if not check["passed"]
    ]
    return {
        "dataset": {
            "suppliers": len(results),
            "documents": sum(len(supplier.get("documents", [])) for supplier in results),
            "extraction_documents": sum(len(supplier.get("extraction_expectations", {})) for supplier in results),
            "rag_only_documents": sum(len(supplier.get("rag_only_documents", {})) for supplier in results),
            "questions": len(questions),
            "answerable_questions": len(found_questions),
            "safe_not_found_questions": len(not_found_questions),
            "ocr_suppliers": sum(s.get("cohort") == "ocr" for s in results),
            "ocr_documents": sum(len(s.get("documents", [])) for s in results if s.get("cohort") == "ocr"),
            "conflicting_evidence_suppliers": sum(s.get("cohort") == "conflicting_evidence" for s in results),
            "scenario_question_suppliers": sum(s.get("cohort") == "scenario_questions" for s in results),
            "question_types": {
                name: sum(question["question_type"] == name for question in questions)
                for name in sorted({question["question_type"] for question in questions})
            },
        },
        "fields_passed": fields_passed,
        "fields_total": fields_total,
        "field_accuracy": ratio(fields_passed, fields_total),
        "field_failures": field_failures,
        "processing_runs": [supplier.get("processing", {}) for supplier in results],
        "processing_error_count": sum(supplier.get("processing", {}).get("failed_document_count", 0) for supplier in results),
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
        "by_cohort": {
            cohort: {
                "passed": sum(q["passed"] for s in results if s.get("cohort", "baseline") == cohort for q in s["questions"]),
                "total": sum(len(s["questions"]) for s in results if s.get("cohort", "baseline") == cohort),
                "accuracy": ratio(sum(q["passed"] for s in results if s.get("cohort", "baseline") == cohort for q in s["questions"]), sum(len(s["questions"]) for s in results if s.get("cohort", "baseline") == cohort)),
            } for cohort in sorted({s.get("cohort", "baseline") for s in results})
        },
        "ocr_documents": [
            {"supplier":s["slug"], "filename":d["filename"], "method":d.get("text_extraction_method"),
             "pages":d.get("ocr_pages", []), "quality_score":d.get("ocr_quality_score"),
             "quality_status":d.get("ocr_quality_status"), "warnings":d.get("ocr_warnings", [])}
            for s in results if s.get("cohort") == "ocr" for d in s.get("documents", [])
        ],
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
    manifest = validate_manifest(manifest_path)
    supplier_names = [item["create_payload"]["name"] for item in manifest["suppliers"]]
    results = []

    health = request_json("GET", f"{base_url}/health")
    if health.get("status") != "healthy":
        raise RuntimeError(f"API health check did not pass: {health}")
    headers = reviewer_headers(base_url, reviewer_email, reviewer_password)

    for entry in manifest["suppliers"]:
        supplier = create_evaluation_supplier(base_url, entry["create_payload"], headers)
        supplier_id = supplier["id"]
        supplier_dir = manifest_path.parent / entry["slug"]
        ensure_documents(
            base_url,
            supplier_id,
            supplier_dir,
            entry["documents"],
            headers,
            entry["document_sha256"],
        )
        processing = request_json(
            "POST",
            f"{base_url}/suppliers/{supplier_id}/process",
            headers=headers,
            params={"refresh": "true"},
            timeout=300,
        )
        if not processing["run"].get("details", {}).get("refresh_requested") or processing.get("processed_document_count") != len(entry["documents"]):
            raise RuntimeError("Backend did not perform a complete fresh processing run. Rebuild/start the backend before evaluation.")
        detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}", headers=headers)
        verify_ocr_execution(entry, detail["documents"])
        field_result = evaluate_fields(
            detail, entry["extraction_expectations"]
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
                    detail["documents"],
                )
            )
        results.append(
            {
                "slug": entry["slug"],
                "cohort": entry.get("cohort", "baseline"),
                "supplier_id": supplier_id,
                "documents": detail["documents"],
                "extraction_expectations": entry["extraction_expectations"],
                "rag_only_documents": entry["rag_only_documents"],
                "processing": {
                    "field_count": processing["field_count"],
                    "chunk_count": processing["chunk_count"],
                    "latency_ms": processing["run"]["latency_ms"],
                    "input_tokens": processing["run"]["input_tokens"],
                    "output_tokens": processing["run"]["output_tokens"],
                    "prompt_version": processing["run"]["prompt_version"],
                    "model": processing["run"]["model"],
                    "status": processing["run"]["status"],
                    "error_message": processing["run"].get("error_message"),
                    "details": processing["run"].get("details", {}),
                    "processed_document_count": processing["processed_document_count"],
                    "failed_document_count": processing["failed_document_count"],
                    "refresh_requested": True,
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
        "run_id": str(uuid.uuid4()),
        "manifest_version": manifest["version"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "evaluation_scope": ("Policy extraction on registration and tax originals; grounded RAG on all originals. Six image-only scans, two conflicting-evidence suppliers and procurement-style scenarios are included. Full onboarding approval is outside scope."
                             if manifest["version"] == 4 else "Policy extraction on registration and tax documents; grounded RAG across all three documents. Not full onboarding approval or OCR coverage."),
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
        f"- Manifest version: `{result.get('manifest_version', 'Historical v2')}`",
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
        f"| Supplier isolation | {percentage(summary['supplier_isolation_accuracy'])} | Retrieved/cited chunk IDs belong to this supplier's originals; no other evaluation supplier name appears |",
        f"| Field extraction accuracy | {summary['fields_passed']}/{summary['fields_total']} ({percentage(summary['field_accuracy'])}) | Each expected policy field matches within its source document; equivalent dates accepted |",
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
                for name in ("answer_match", "found_match", "citation_match", "isolation_match", "conflict_match", "uncertainty_match")
                if failure.get(name) is False
            ]
            lines.append(
                f"| {failure['supplier']} | {failure['id']} | {failure['question_type']} | {', '.join(components)} |"
            )
    lines.extend([
        "",
        "## Extraction scope and failures",
        "",
        result.get("evaluation_scope", "Historical manifest v2 used legacy extraction expectations; its field accuracy is not comparable with the current policy contract."),
        "",
        f"Extraction documents: {dataset.get('extraction_documents', 'Not recorded')}; supplementary RAG-only documents: {dataset.get('rag_only_documents', 'Not recorded')}.",
        "",
    ])
    field_failures = summary.get("field_failures", [])
    if field_failures:
        lines.extend(["| Supplier | Document | Field | Expected | Actual |", "|---|---|---|---|---|"])
        for failure in field_failures:
            cells = [failure["supplier"], failure["document_type"], failure["field_name"], failure["expected"], failure["actual"]]
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    elif summary["fields_passed"] != summary["fields_total"]:
        lines.append("Historical field mismatches are recorded in the JSON supplier checks.")
    else:
        lines.append("No failed extraction checks.")
    for processing in summary.get("processing_runs", []):
        lines.append(f"- Processing: status={processing.get('status', 'unknown')}; failed documents={processing.get('failed_document_count', 'unknown')}; model={processing.get('model', 'unknown')}; prompt={processing.get('prompt_version', 'unknown')}; input/output tokens={processing.get('input_tokens', 0)}/{processing.get('output_tokens', 0)}.")
    if result.get("manifest_version") == 4:
        lines.extend(["", "## Results by evaluation cohort", "", "| Cohort | Passed | Accuracy |", "|---|---:|---:|"])
        for name, metrics in summary["by_cohort"].items():
            lines.append(f"| {name.replace('_', ' ').title()} | {metrics['passed']}/{metrics['total']} | {percentage(metrics['accuracy'])} |")
        lines.extend(["", "## OCR execution evidence", "", "| Supplier | Original | Method | Pages | Quality |", "|---|---|---|---|---|"])
        for doc in summary["ocr_documents"]:
            lines.append(f"| {doc['supplier']} | {doc['filename']} | {doc['method']} | {doc['pages']} | {doc['quality_score']} ({doc['quality_status']}) |")
        lines.extend(["", "Conflict cases additionally require every declared source citation, both disagreeing values, source attribution, explicit conflict acknowledgement and a lexical uncertainty/clarification guard. Recognition errors and incorrect conflict answers remain failed cases. OCR authoring transcripts are used only for offline ground-truth validation and are never uploaded as evidence."])
    lines.extend([
        "",
        "## Method and interpretation",
        "",
        "Each question passes only when expected answer components (including equivalent calendar dates), information-found decision, citation rule and supplier isolation all pass. Citations must use expected source documents and valid retrieved chunk IDs belonging to the evaluated supplier. Safe-not-found cases require the exact guarded fallback with no citations. Every run creates fresh supplier records, checks original PDF hashes and forces extraction/indexing refresh; existing supplier data is preserved. Extraction checks use current policy fields per document, with the legacy liability certificate explicitly RAG-only. Latency wraps the live HTTP request; P50/P95 use nearest rank. Headline token totals cover Q&A; extraction/indexing usage is recorded separately. Scores from different manifest versions must not be presented as a like-for-like improvement.",
        "",
        "## Limitations",
        "",
        ("This remains a small synthetic English corpus, not a production guarantee. Scans cover clean rasterization and JPEG compression, not the full range of real scanning defects. Procurement-style questions are authored scenarios, not independently sampled real user traffic. Component matching and conflict guards are lexical, not semantic entailment checks. Future calibration needs held-out real documents, more scan defects, multi-page evidence and independently labelled user questions."
         if result.get("manifest_version") == 4 else "This is a controlled synthetic regression evaluation, not a production guarantee. The corpus uses text-native, one-page English PDFs and exact expected facts. Results should be labelled as controlled evaluation results; production calibration would require a larger held-out corpus containing scans, OCR noise, multi-page evidence, conflicting values and real user paraphrases."),
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--validate-only", action="store_true", help="Validate the PDF corpus, checksums and policy contract without API calls or writing reports.")
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
    if args.validate_only:
        manifest = validate_manifest(args.manifest.resolve())
        suppliers = manifest["suppliers"]
        print(f"Validated manifest v{manifest['version']}: {len(suppliers)} suppliers, {sum(len(s['documents']) for s in suppliers)} PDFs, {sum(len(s['questions']) for s in suppliers)} questions, {sum(len(f) for s in suppliers for f in s['extraction_expectations'].values())} source-scoped extraction checks.")
        return
    result = run_evaluation(
        args.base_url.rstrip("/"),
        args.manifest.resolve(),
        args.reviewer_email,
        args.reviewer_password,
    )
    write_reports(result, args.output, args.report_output)
    print("summary=" + json.dumps(result["summary"]), flush=True)
    print(f"results={args.output.resolve()}", flush=True)
    print(f"report={args.report_output.resolve()}", flush=True)


def write_reports(result: dict, output: Path, report_output: Path) -> None:
    """Stage a complete run before replacing latest; preserve previous report bytes."""
    outputs = {output: json.dumps(result, indent=2), report_output: render_markdown_report(result)}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + str(uuid.uuid4())
    temporary = []
    try:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            staged = path.with_name(path.name + "." + stamp + ".tmp")
            staged.write_text(content, encoding="utf-8")
            temporary.append((staged, path))
        for path in outputs:
            if path.exists():
                archive = path.parent / "results_archive" / stamp
                archive.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, archive / path.name)
        for staged, path in temporary:
            staged.replace(path)
    finally:
        for staged, _ in temporary:
            staged.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
