"""Expanded gold data and scoring must expose mistakes, not hide them."""
import hashlib
import json
import shutil
from pathlib import Path

import pymupdf
import pytest

from scripts.run_quality_evaluation import answer_matches, conflict_checks, evaluate_question, validate_manifest, verify_ocr_execution

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sample_documents/evaluation_sets/evaluation_manifest.json"


def test_extended_sources_are_image_only_and_cohorts_cover_requested_cases():
    manifest = json.loads(MANIFEST.read_text())
    baseline = json.loads((MANIFEST.parent / "baseline_manifest_v3.json").read_text())
    assert manifest["suppliers"][:5] == baseline["suppliers"]  # Original evidence/gold untouched.
    assert len(manifest["suppliers"]) == 10
    assert sum(len(s["questions"]) for s in manifest["suppliers"]) == 100
    scans = [s for s in manifest["suppliers"] if s.get("cohort") == "ocr"]
    assert len(scans) == 2
    for s in scans:
        for name in s["documents"].values():
            with pymupdf.open(MANIFEST.parent / s["slug"] / name) as doc:
                assert all(not p.get_text().strip() and p.get_images() for p in doc)
    conflicts = [q for s in manifest["suppliers"] for q in s["questions"] if q["question_type"] == "conflict_resolution"]
    assert len(conflicts) == 8 and all(len(q["required_sources"]) == 2 for q in conflicts)
    assert all(q["requires_uncertainty"] and q["expected_term_groups"] for q in conflicts)


def test_ocr_preflight_rejects_a_scan_replaced_with_selectable_text(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(MANIFEST.parent, corpus)
    manifest_path = corpus / MANIFEST.name
    manifest = json.loads(manifest_path.read_text())
    entry = manifest["suppliers"][5]
    path = corpus / entry["slug"] / entry["documents"]["registration"]
    with pymupdf.open(path) as doc:
        doc[0].insert_text((30, 35), "Accidental native text layer")
        changed = doc.tobytes()
    path.write_bytes(changed)
    entry["document_sha256"]["registration"] = hashlib.sha256(changed).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="only scanned page images"):
        validate_manifest(manifest_path)


@pytest.mark.parametrize("text,expected", [
    ("The dates conflict. Neither date is confirmed; supplier clarification is required.", True),
    ("The dates are different and we need confirmation before choosing one.", True),
    ("The dates differ. We cannot determine which date is authoritative.", True),
    ("The dates conflict. The registration date is confirmed and authoritative.", False),
    ("The dates are different. I choose the registration date.", False),
])
def test_conflict_guard_rejects_an_unsupported_winner(text, expected):
    case = {"requires_conflict_acknowledgement":True, "requires_uncertainty":True}
    checks = conflict_checks(text, case)
    assert checks["conflict_match"]
    assert checks["uncertainty_match"] is expected


@pytest.mark.parametrize("cite_both", [True, False])
def test_conflict_answer_requires_both_source_citations(monkeypatch, cite_both):
    sources = ["registration.pdf", "tax.pdf"]
    docs = [{"id": "reg", "filename":sources[0], "page_count":1}, {"id":"tax", "filename":sources[1], "page_count":1}]
    citations = [{"chunk_id":f"supplier:{d['id']}:0", "filename":d['filename'], "page_number":1, "excerpt":"Net 30 or Net 60"} for d in docs[:2 if cite_both else 1]]
    body = {"answer":"Registration states Net 30; tax states Net 60. The terms conflict and require supplier clarification.",
            "information_found":True, "citations":citations,
            "run":{"retrieval_count":2,"latency_ms":100,"input_tokens":10,"output_tokens":5,
                   "details":{"retrieved_chunk_ids":["supplier:reg:0","supplier:tax:0"]}}}
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", lambda *a, **k:body)
    result = evaluate_question("http://test", "supplier", {
        "id":"terms","question_type":"conflict_resolution","question":"Compare terms",
        "expected_terms":["Net 30","Net 60"],"expected_sources":sources,"required_sources":sources,
        "expected_term_groups":[["registration"],["tax","GST"]],"information_found":True,
        "requires_conflict_acknowledgement":True,"requires_uncertainty":True,
    }, [], {}, docs)
    assert result["answer_match"] and result["conflict_match"] and result["uncertainty_match"]
    assert result["citation_match"] is cite_both and result["passed"] is cite_both


def test_conflict_source_attribution_and_all_values_are_required():
    q = {"expected_terms":["Net 30","Net 60"], "expected_term_groups":[["registration"],["tax","GST"]]}
    assert answer_matches("Registration says Net 30; GST says Net 60.", q)
    assert not answer_matches("There are Net 30 and Net 60 terms.", q)
    assert not answer_matches("Registration says Net 30; GST differs.", q)


@pytest.mark.parametrize("method,pages", [("native", []), ("mixed", [1]), ("ocr", []), ("ocr", [2])])
def test_backend_ocr_coverage_cannot_be_claimed_from_wrong_metadata(method, pages):
    entry = {"cohort":"ocr", "documents":{"registration":"scan.pdf"}}
    with pytest.raises(RuntimeError, match="backend OCR"):
        verify_ocr_execution(entry, [{"page_count":1,"text_extraction_method":method,"ocr_pages":pages}])
    verify_ocr_execution(entry, [{"page_count":1,"text_extraction_method":"ocr","ocr_pages":[1]}])


def test_expanded_report_exposes_cohort_ocr_and_conflict_failures():
    from scripts.run_quality_evaluation import build_summary, render_markdown_report
    case = {"id":"conflict","question_type":"conflict_resolution","passed":False,
            "answer_match":True,"found_match":True,"citation_match":False,"isolation_match":True,
            "conflict_match":True,"uncertainty_match":False,"expected_information_found":True,
            "safe_fallback_match":None,"api_latency_ms":100,"recorded_latency_ms":90,
            "retrieval_count":2,"input_tokens":10,"output_tokens":5,"model":"test","prompt_version":"test"}
    summary = build_summary([{"slug":"test_supplier","cohort":"ocr","fields":{"passed":9,"total":9},
                              "documents":[{"filename":"scan.pdf","text_extraction_method":"ocr","ocr_pages":[1],"ocr_quality_score":56,"ocr_quality_status":"review"}],
                              "questions":[case]}], 100)
    report = render_markdown_report({"evaluated_at":"test","base_url":"http://test","manifest_version":4,"summary":summary})
    assert summary["by_cohort"]["ocr"]["accuracy"] == 0
    assert "OCR execution evidence" in report and "56 (review)" in report
    assert "citation, uncertainty" in report
    assert "not independently sampled real user traffic" in report
