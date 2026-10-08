"""The final controlled RAG evaluation stays credible and presentation-ready."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.run_quality_evaluation import (
    answer_matches, build_summary, evaluate_fields, evaluate_question,
    render_markdown_report, reviewer_headers, run_evaluation,
    validate_manifest, write_reports,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sample_documents" / "evaluation_sets" / "baseline_manifest_v3.json"


def test_final_manifest_has_five_suppliers_and_fifty_varied_questions() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    questions = [item for supplier in manifest["suppliers"] for item in supplier["questions"]]

    assert manifest["version"] == 3
    assert len(manifest["suppliers"]) == 5
    assert all(len(supplier["questions"]) == 10 for supplier in manifest["suppliers"])
    assert len(questions) == 50
    assert {item["question_type"] for item in questions} == {
        "direct_fact", "paraphrased_fact", "date_interpretation",
        "multi_fact", "safe_not_found",
    }
    assert sum(not item["information_found"] for item in questions) == 10
    assert all(item["expected_sources"] for item in questions if item["information_found"])
    assert all(not item["expected_sources"] for item in questions if not item["information_found"])


def test_evaluation_authenticates_as_reviewer(monkeypatch) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return {"token": "evaluation-token"}

    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", fake_request)
    assert reviewer_headers("http://api.test/api") == {
        "Authorization": "Bearer evaluation-token",
    }
    assert calls[-1][:2] == ("POST", "http://api.test/api/portal/auth/reviewer-demo")

    assert reviewer_headers("http://api.test/api", "reviewer@example.com", "secret") == {
        "Authorization": "Bearer evaluation-token",
    }
    assert calls[-1][1].endswith("/portal/auth/reviewer")
    assert calls[-1][2] == {"email": "reviewer@example.com", "password": "secret"}


def test_summary_and_markdown_expose_mentor_ready_metrics() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = []
    counter = 0
    for supplier in manifest["suppliers"]:
        question_results = []
        for case in supplier["questions"]:
            counter += 1
            answerable = case["information_found"]
            question_results.append({
                "id": case["id"],
                "question_type": case["question_type"],
                "passed": True,
                "answer_match": True,
                "found_match": True,
                "citation_match": True,
                "safe_fallback_match": None if answerable else True,
                "isolation_match": True,
                "information_found": answerable,
                "expected_information_found": answerable,
                "api_latency_ms": 900 + counter * 10,
                "recorded_latency_ms": 800 + counter * 10,
                "input_tokens": 100,
                "output_tokens": 20,
                "retrieval_count": 3,
                "model": "demo-model",
                "prompt_version": "rag-answer-v3",
            })
        results.append({
            "slug": supplier["slug"],
            "fields": {"passed": 9, "total": 9},
            "documents": list(supplier["documents"]),
            "extraction_expectations": supplier["extraction_expectations"],
            "rag_only_documents": supplier["rag_only_documents"],
            "questions": question_results,
        })

    summary = build_summary(results, elapsed_ms=60_000)
    report = render_markdown_report({
        "evaluated_at": "2026-10-08T00:00:00+00:00",
        "base_url": "http://127.0.0.1:8000/api",
        "summary": summary,
    })

    assert summary["questions_passed"] == summary["questions_total"] == 50
    assert summary["dataset"]["suppliers"] == 5
    assert summary["dataset"]["documents"] == 15
    assert summary["safe_fallback_accuracy"] == 1.0
    assert summary["citation_accuracy"] == 1.0
    assert summary["latency_ms"]["p95"] is not None
    assert summary["tokens"]["total"] == 6000
    assert summary["retrieval"]["average_chunks"] == 3
    assert summary["models"] == ["demo-model"]
    for heading in (
        "Executive results", "RAG response latency", "Results by question type",
        "Results by supplier", "Usage", "Failures", "Method and interpretation", "Limitations",
    ):
        assert heading in report


def test_preflight_rejects_schema_drift_and_changed_pdf_before_api_calls(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    shutil.copytree(MANIFEST.parent, corpus)
    manifest_path = corpus / MANIFEST.name
    manifest = validate_manifest(manifest_path)
    assert sum(len(fields) for supplier in manifest["suppliers"] for fields in supplier["extraction_expectations"].values()) == 45
    supplier = manifest["suppliers"][0]
    supplier["extraction_expectations"]["registration"]["address"] = "Old unsupported field"
    manifest_path.write_text(json.dumps(manifest))
    calls = []
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="current policy fields"):
        run_evaluation("http://api.test/api", manifest_path)
    assert not calls

    del supplier["extraction_expectations"]["registration"]["address"]
    manifest_path.write_text(json.dumps(manifest))
    pdf = corpus / supplier["slug"] / supplier["documents"]["registration"]
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_manifest(manifest_path)


@pytest.mark.parametrize("date", ["30 JUN 2027", "30 June 2027", "June 30, 2027", "2027-06-30", "30/06/2027"])
def test_equivalent_dates_pass_but_wrong_dates_do_not(date):
    case = {"expected_terms": [], "expected_dates": ["2027-06-30"]}
    assert answer_matches(f"Expires on {date}.", case)
    assert not answer_matches("Expires on 29 June 2027.", case)
    assert not answer_matches("Expires during June 2027.", case)


def test_full_address_requires_all_components():
    case = json.loads(MANIFEST.read_text())["suppliers"][0]["questions"][6]
    assert answer_matches("Plot 22; SIDCO Industrial Estate; Kurichi; Coimbatore; Tamil Nadu 641021", case)
    assert answer_matches("Plot 22, SIDCO Industrial Estate, Kurichi, Coimbatore, Tamil Nadu (PIN: 641021)", case)
    assert not answer_matches("Coimbatore, Tamil Nadu, India", case)


def test_field_checks_require_the_right_document_pan_and_date():
    detail = {
        "documents": [{"id": "reg", "document_type": "registration"}, {"id": "tax", "document_type": "tax"}],
        "extracted_fields": [
            {"document_id": "reg", "field_name": "registration_date", "value": "12 September 2018", "needs_review": False},
            {"document_id": "tax", "field_name": "tax_identifier", "value": "AABCK1234F", "needs_review": False},
            {"document_id": "tax", "field_name": "supplier_name", "value": "Expected Name", "needs_review": False},
        ],
    }
    result = evaluate_fields(detail, {"registration": {"registration_date": "2018-09-12", "supplier_name": "Expected Name"}, "tax": {"tax_identifier": "AABCK1234F"}})
    assert result["passed"] == 2 and result["total"] == 3
    assert result["checks"][1]["actual"] is None  # Cannot borrow the name from another original.
    detail["extracted_fields"][1]["value"] = "33AABCK1234F1Z8"
    assert evaluate_fields(detail, {"tax": {"tax_identifier": "AABCK1234F"}})["passed"] == 0


def test_pdf_generator_is_reproducible_for_pinned_corpus_hashes(tmp_path):
    from scripts.generate_evaluation_documents import SUPPLIERS, registration_pdf
    first, second = tmp_path / "first", tmp_path / "second"
    registration_pdf(SUPPLIERS[0], first)
    registration_pdf(SUPPLIERS[0], second)
    filename = "01_supplier_registration_form.pdf"
    assert (first / filename).read_bytes() == (second / filename).read_bytes()


@pytest.mark.parametrize("chunk_id,filename,page", [
    ("other:doc:0", "registration.pdf", 1),
    ("supplier:unknown:0", "registration.pdf", 1),
    ("supplier:doc:0", "unexpected.pdf", 1),
    ("supplier:doc:0", "registration.pdf", 2),
])
def test_citation_validation_rejects_wrong_supplier_original_source_or_page(monkeypatch, chunk_id, filename, page):
    body = {
        "answer": "Correct name", "information_found": True,
        "citations": [{"chunk_id": chunk_id, "filename": filename, "page_number": page, "excerpt": "Correct name"}],
        "run": {"retrieval_count": 1, "latency_ms": 100, "input_tokens": 10, "output_tokens": 3,
                "model": "test", "prompt_version": "test", "details": {"retrieved_chunk_ids": [chunk_id]}},
    }
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", lambda *args, **kwargs: body)
    result = evaluate_question("http://api.test", "supplier", {
        "id": "name", "question_type": "direct_fact", "question": "Name?", "expected_terms": ["Correct name"],
        "expected_sources": ["registration.pdf"], "information_found": True,
    }, [], {}, [{"id": "doc", "filename": "registration.pdf", "page_count": 1}])
    assert result["answer_match"] and not result["citation_match"] and not result["passed"]


def test_report_replacement_archives_previous_run_without_changing_its_bytes(tmp_path):
    from scripts.run_quality_evaluation import render_markdown_report as render
    baseline = json.loads((MANIFEST.parent / "historical_results_manifest_v2_50_questions.json").read_text())
    output, report = tmp_path / "latest_results.json", tmp_path / "latest_results.md"
    old_json, old_md = b'{"previous":true}', b"Previous report\n"
    output.write_bytes(old_json)
    report.write_bytes(old_md)
    write_reports(baseline, output, report)
    archived_json = list((tmp_path / "results_archive").rglob("latest_results.json"))
    archived_md = list((tmp_path / "results_archive").rglob("latest_results.md"))
    assert len(archived_json) == len(archived_md) == 1
    assert archived_json[0].read_bytes() == old_json and archived_md[0].read_bytes() == old_md
    assert json.loads(output.read_text()) == baseline and report.read_text() == render(baseline)


@pytest.mark.parametrize("backend_refresh", [True, False])
def test_live_runner_creates_fresh_suppliers_and_forces_complete_processing(monkeypatch, backend_refresh):
    manifest = validate_manifest(MANIFEST)
    records, process_calls = {}, []
    entries = iter(manifest["suppliers"])

    def fake_request(method, url, **kwargs):
        if url.endswith("/health"):
            return {"status": "healthy"}
        if url.endswith("/reviewer-demo"):
            return {"token": "token"}
        if url.endswith("/suppliers"):
            assert method == "POST"  # Must never list/reuse existing suppliers.
            entry = next(entries)
            sid = f"supplier-{len(records)}"
            records[sid] = {"entry": entry, "documents": [], "next_question": 0}
            assert kwargs["json"]["is_evaluation"] is True
            return {"id": sid, "is_evaluation": True}
        sid = url.split("/suppliers/")[1].split("/")[0]
        record = records[sid]
        if url.endswith("/process"):
            assert kwargs["params"] == {"refresh": "true"}
            process_calls.append(sid)
            return {"field_count": 9, "chunk_count": 3, "processed_document_count": 3, "failed_document_count": 0,
                    "run": {"latency_ms": 100, "input_tokens": 50, "output_tokens": 30, "model": "model", "prompt_version": "extraction-v4", "status": "succeeded", "details": {"refresh_requested": backend_refresh}}}
        if url.endswith("/questions"):
            case = record["entry"]["questions"][record["next_question"]]
            record["next_question"] += 1
            sources = case["expected_sources"][:1]
            citations = [{"filename": source, "page_number": 1, "excerpt": "Supporting text", "chunk_id": f"{sid}:{next(d['id'] for d in record['documents'] if d['filename'] == source)}:0"} for source in sources]
            return {"answer": " ".join(case["expected_terms"] + case.get("expected_dates", [])),
                    "information_found": case["information_found"], "citations": citations,
                    "run": {"retrieval_count": len(citations), "latency_ms": 100, "input_tokens": 10, "output_tokens": 3,
                            "model": "test", "prompt_version": "test", "details": {"retrieved_chunk_ids": [c["chunk_id"] for c in citations]}}}
        fields = [
            {"document_id": doc["id"], "field_name": key, "value": value, "needs_review": False}
            for doc in record["documents"]
            for key, value in record["entry"]["extraction_expectations"].get(doc["document_type"], {}).items()
        ]
        return {"documents": record["documents"], "extracted_fields": fields}

    def upload(url, **kwargs):
        sid = url.split("/suppliers/")[1].split("/")[0]
        kind = kwargs["data"]["document_type"]
        record = records[sid]
        record["documents"].append({"id": f"{sid}-{kind}", "document_type": kind,
                                    "filename": record["entry"]["documents"][kind], "page_count": 1,
                                    "sha256": record["entry"]["document_sha256"][kind]})
        from types import SimpleNamespace
        return SimpleNamespace(ok=True)

    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", fake_request)
    monkeypatch.setattr("scripts.run_quality_evaluation.requests.post", upload)
    if not backend_refresh:
        with pytest.raises(RuntimeError, match="fresh processing run"):
            run_evaluation("http://api.test/api", MANIFEST)
        return
    result = run_evaluation("http://api.test/api", MANIFEST)
    assert len(records) == len(process_calls) == 5
    assert result["manifest_version"] == 3
    assert result["summary"]["fields_total"] == result["summary"]["fields_passed"] == 45
    assert result["summary"]["questions_total"] == result["summary"]["questions_passed"] == 50
    assert result["summary"]["dataset"]["extraction_documents"] == 10
    assert result["summary"]["dataset"]["rag_only_documents"] == 5
