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


def test_windows_transcript_newlines_pass_but_changed_source_content_fails(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(MANIFEST.parent, corpus)
    transcripts = sorted(corpus.glob("*/*.source.txt"))
    assert len(transcripts) == 6
    for path in transcripts:
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    # The full preflight still checks PDF hashes and exercises real backend OCR.
    validated = validate_manifest(corpus / MANIFEST.name)
    assert validated["version"] == 4 and len(validated["suppliers"]) == 10
    changed = transcripts[0]
    changed.write_bytes(changed.read_bytes() + b"\r\nChanged source fact")
    with pytest.raises(ValueError, match="OCR authoring transcript checksum mismatch"):
        validate_manifest(corpus / MANIFEST.name)


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


@pytest.mark.parametrize('state,pin,unit,expected', [
    ('Karnataka', '560099', 'Unit 63', True),
    ('Tamil Nadu', '560099', 'Unit 63', False),
    ('Karnataka', '560098', 'Unit 63', False),
    ('Karnataka', '5600999', 'Unit 63', False),
    ('Karnataka', '', 'Unit 63', False),
    ('Karnataka', '560099', 'Unit 64', False),
])
def test_structured_address_accepts_labels_but_requires_every_correct_component(state,pin,unit,expected):
    case={'id':'address_for_master','expected_terms':['Unit 63','Bommasandra Industrial Area','Bengaluru','Karnataka 560099']}
    answer=f'Street: {unit}\nLocality: Bommasandra Industrial Area\nCity: Bengaluru\nState: {state}\nPIN Code: {pin}'
    assert answer_matches(answer,case) is expected


@pytest.mark.parametrize('answer,question,expected', [
    ('The dates differ. You cannot diary one confirmed expiry date.', 'Can I diary one confirmed date?', True),
    ('The dates differ. We cannot record a confirmed date.', 'Can I diary one confirmed date?', True),
    ('No, the stated payment terms are different: Net 30 versus Net 60.', 'Is there one agreed term?', True),
    ('No, the stated payment terms are different: Net 30 versus Net 60.', 'Does the tax document exist?', False),
    ('No, the terms are different. I will use Net 60.', 'Is there one agreed term?', False),
    ('The terms conflict and require clarification. The registration term is authoritative.', 'Is there one agreed term?', False),
    ('The terms are different: Net 30 versus Net 60.', 'Is there one agreed term?', False),
])
def test_equivalent_uncertainty_is_question_bound_and_rejects_a_winner(answer,question,expected):
    case={'question':question,'requires_conflict_acknowledgement':True,'requires_uncertainty':True}
    assert conflict_checks(answer,case)['uncertainty_match'] is expected


@pytest.mark.parametrize('case_id,cited,expected', [
    ('erp_names',['registration','tax'],True),
    ('erp_names',['tax'],True),
    ('erp_names',['insurance'],False),
    ('gst_status',['tax','registration'],True),
    ('gst_status',['registration'],False),
    ('supplier_handover',['registration','insurance'],True),
    ('supplier_handover',['insurance'],False),
    ('supplier_handover',['registration','unknown'],False),
])
def test_corroboration_keeps_unique_fact_and_task_sources_required(case_id,cited,expected):
    from scripts.run_quality_evaluation import score_response
    entry=json.loads(MANIFEST.read_text())['suppliers'][-1]
    case=next(q for q in entry['questions'] if q['id']==case_id)
    docs=[{'id':kind,'filename':filename,'page_count':1} for kind,filename in entry['documents'].items()]
    docs.append({'id':'unknown','filename':'unrelated.pdf','page_count':1})
    body={'answer':' '.join(case['expected_terms']),'information_found':True,
          'citations':[{'filename':next(d['filename'] for d in docs if d['id']==kind),'page_number':1,'chunk_id':f'supplier:{kind}:0','excerpt':'facts'} for kind in cited],
          'run':{'retrieval_count':len(cited),'details':{'retrieved_chunk_ids':[f'supplier:{kind}:0' for kind in cited]}}}
    checks=score_response(body,'supplier',case,[],docs)
    assert checks['answer_match'] and checks['isolation_match']
    assert checks['citation_match'] is expected and checks['passed'] is expected


def test_offline_rescoring_preserves_observations_and_rejects_changed_questions(tmp_path,monkeypatch):
    from scripts.run_quality_evaluation import rescore_evaluation
    docs=[{'id':'reg','supplier_id':'supplier','document_type':'registration','filename':'reg.pdf','page_count':1,'sha256':'reg-hash'},
          {'id':'tax','supplier_id':'supplier','document_type':'tax','filename':'tax.pdf','page_count':1,'sha256':'tax-hash'}]
    case={'id':'name','question_type':'direct_fact','question':'What is the name?','expected_terms':['Demo'],
          'expected_sources':['reg.pdf','tax.pdf'],'information_found':True}
    q={**case,'answer':'Demo','passed':False,'answer_match':True,'found_match':True,'citation_match':False,
       'safe_fallback_match':None,'isolation_match':True,'conflict_match':None,'uncertainty_match':None,
       'expected_information_found':True,'retrieval_count':2,'retrieved_chunk_ids':['supplier:reg:0','supplier:tax:0'],
       'retrieval_distances':[.4,.5],'api_latency_ms':123,'recorded_latency_ms':100,'input_tokens':20,'output_tokens':5,
       'model':'test','prompt_version':'test',
       'citations':[{'chunk_id':f'supplier:{d["id"]}:0','filename':d['filename'],'page_number':1,'excerpt':'Demo'} for d in docs]}
    source={'evaluated_at':'original-time','run_id':'original-run','manifest_version':4,'manifest_sha256':'original-manifest',
            'base_url':'http://test','summary':{'questions_passed':0,'evaluation_elapsed_ms':500},
            'suppliers':[{'slug':'demo','supplier_id':'supplier','documents':docs,'fields':{'passed':0,'total':0},'questions':[q]}]}
    source_path=tmp_path/'live.json';source_path.write_text(json.dumps(source));before=source_path.read_bytes()
    manifest_path=tmp_path/'manifest.json';manifest_path.write_text('scoring-manifest')
    manifest={'version':4,'suppliers':[{'slug':'demo','create_payload':{'name':'Demo'},'questions':[case],
              'documents':{'registration':'reg.pdf','tax':'tax.pdf'},'document_sha256':{'registration':'reg-hash','tax':'tax-hash'}}]}
    monkeypatch.setattr('scripts.run_quality_evaluation.validate_manifest',lambda _:manifest)
    def forbidden(*args,**kwargs):raise AssertionError('Offline rescoring must not call the API')
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',forbidden)
    result=rescore_evaluation(source_path,manifest_path)
    assert result['summary']['questions_passed']==1
    assert result['evaluation_mode']=='offline_rescore' and result['run_id']==source['run_id']
    new_q=result['suppliers'][0]['questions'][0]
    for key in ['answer','citations','retrieved_chunk_ids','retrieval_distances','api_latency_ms','recorded_latency_ms','input_tokens','output_tokens','model','prompt_version']:
        assert new_q[key]==q[key]
    assert source_path.read_bytes()==before and source['suppliers'][0]['questions'][0]['passed'] is False
    assert result['rescoring']['source_report_sha256']==hashlib.sha256(before).hexdigest()
    assert 'Offline' in result['rescoring']['method']
    source['suppliers'][0]['questions'][0]['question']='A different question'
    source_path.write_text(json.dumps(source))
    with pytest.raises(ValueError,match='new live run'):
        rescore_evaluation(source_path,manifest_path)


def test_offline_cli_cannot_replace_live_latest_reports(tmp_path):
    import subprocess,sys
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_quality_evaluation.py'),'--rescore',str(tmp_path/'missing.json')],capture_output=True,text=True)
    assert result.returncode==2 and 'preserve the source and live latest reports' in result.stderr
