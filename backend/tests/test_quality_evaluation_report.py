"""The final controlled RAG evaluation stays credible and presentation-ready."""

import json
from pathlib import Path

from scripts.run_quality_evaluation import build_summary, render_markdown_report, reviewer_headers


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sample_documents" / "evaluation_sets" / "evaluation_manifest.json"


def test_final_manifest_has_five_suppliers_and_fifty_varied_questions() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    questions = [item for supplier in manifest["suppliers"] for item in supplier["questions"]]

    assert manifest["version"] == 2
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
