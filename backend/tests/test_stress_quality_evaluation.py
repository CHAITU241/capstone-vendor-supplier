"""Stress rubric calibration uses pinned evidence and deliberate incorrect controls."""
import copy
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from scripts.run_quality_evaluation import (
    amounts_in, answer_matches, dates_in, score_response, validate_manifest,
    verify_ocr_execution, build_summary, render_markdown_report, write_reports,
    run_evaluation, ensure_documents,
)
from app.config import Settings
from app.services.documents import extract_document_text
from app.services.chunking import chunk_document
from app.services.redaction import redact_pii

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'sample_documents/evaluation_sets/evaluation_manifest.json'
MANIFEST_DATA = json.loads(MANIFEST.read_text())
STRESS = MANIFEST_DATA['suppliers'][10:]
CASES = [(s,q) for s in STRESS for q in s['questions']]


def response(supplier, case):
    docs = [{'id':kind,'filename':name,'page_count':len(pymupdf.open(MANIFEST.parent/supplier['slug']/name))} for kind,name in supplier['documents'].items()]
    citations = [{'filename':r['filename'],'page_number':r['pages'][0],
                  'chunk_id':f"supplier:{next(d['id'] for d in docs if d['filename']==r['filename'])}:{r['pages'][0]-1}",
                  'excerpt':'UI excerpts are truncated; full-page support is checked using the pinned originals.'}
                 for r in case.get('citation_requirements',[])]
    return docs, {'answer':case['reference_answer'],'information_found':case['information_found'],
                  'citations':citations,'run':{'retrieval_count':len(citations),
                  'details':{'retrieved_chunk_ids':[c['chunk_id'] for c in citations]}}}


def test_final_corpus_and_actual_ocr_chunk_budget():
    manifest = validate_manifest(MANIFEST)
    pinned = json.loads((MANIFEST.parent/'baseline_manifest_v4.json').read_text())
    assert manifest['suppliers'][:10] == pinned['suppliers']
    assert manifest['expected_counts']['questions'] == 150
    assert len(STRESS)==5 and len(CASES)==50
    pages = 0
    for supplier in STRESS:
        chunks = []
        methods = []
        for kind,filename in supplier['documents'].items():
            path = MANIFEST.parent/supplier['slug']/filename
            extracted = extract_document_text(path,'application/pdf',Settings())
            pages += extracted.page_count
            assert extracted.text_extraction_method == supplier['document_modes'][kind]
            assert list(extracted.ocr_pages) == supplier['expected_ocr_pages'][kind]
            # These are readable stress scans, not deliberate unreadable intake failures.
            if extracted.ocr_pages:
                assert extracted.ocr_quality_status != 'poor'
            chunked = chunk_document(redact_pii(extracted.text).text,'text-embedding-3-small')
            assert len(chunked)==extracted.page_count  # One chunk per page, >top-k across pack.
            chunks.extend(chunked)
            methods.append({'filename':filename,'page_count':extracted.page_count,
                            'text_extraction_method':extracted.text_extraction_method,'ocr_pages':list(extracted.ocr_pages)})
        assert len(chunks)>4
        verify_ocr_execution(supplier,methods)
        assert all(len(q.get('citation_requirements',[]))<=3 for q in supplier['questions'])
    assert pages==43


@pytest.mark.parametrize('supplier,case', CASES, ids=[f"{s['slug']}/{q['id']}" for s,q in CASES])
def test_all_fifty_independently_authored_correct_controls_pass(supplier,case):
    docs,body=response(supplier,case)
    assert score_response(body,'supplier',case,[],docs)['passed']


@pytest.mark.parametrize('supplier,case', [(s,q) for s,q in CASES if q['information_found']], ids=[f"{s['slug']}/{q['id']}" for s,q in CASES if q['information_found']])
def test_answerless_and_wrong_page_controls_cannot_pass(supplier,case):
    docs,body=response(supplier,case)
    body['answer']='There is some information.'
    assert not score_response(body,'supplier',case,[],docs)['answer_match']
    body['answer']=case['reference_answer']
    body['citations'][0]['page_number']=99
    assert not score_response(body,'supplier',case,[],docs)['passed']


@pytest.mark.parametrize('value', ['INR 20,00,000','INR 2,000,000','INR 20 lakh','20 lakh rupees','INR 2 million','Rs. 2000000','₹2,000,000'])
def test_equivalent_currency_formats_pass(value):
    assert 2000000 in amounts_in(value)
    assert answer_matches(value, {'expected_terms':[],'expected_amounts':[2000000]})


@pytest.mark.parametrize('value', ['2000000','INR 2000001','INR 2000000.9','INR 20 crore','INR 20,000'])
def test_wrong_amount_or_unqualified_number_fails(value):
    assert not answer_matches(value, {'expected_terms':[],'expected_amounts':[2000000]})


def test_equivalent_line_wrapped_and_ordinal_dates_and_wrong_day():
    assert dates_in('12 September\n2020') == {'2020-09-12'}
    assert dates_in('30th June 2028') == {'2028-06-30'}
    assert not answer_matches('29th June 2028',{'expected_terms':[],'expected_dates':['2028-06-30']})


def test_right_document_wrong_clause_and_missing_required_second_page_fail():
    supplier,case=next((s,q) for s,q in CASES if q['id']=='transit_and_storage')
    docs,body=response(supplier,case)
    body['citations'][0]['page_number']=1 # correct PDF; introductory page has no requested limit
    assert not score_response(body,'supplier',case,[],docs)['citation_match']
    docs,body=response(supplier,case)
    body['citations']=body['citations'][:1]
    assert not score_response(body,'supplier',case,[],docs)['citation_match']


def test_supplier_isolation_duplicate_and_malformed_retrieval_ids():
    supplier,case=CASES[0];docs,body=response(supplier,case)
    body['run']['details']['retrieved_chunk_ids']=['other:registration:0']
    assert not score_response(body,'supplier',case,[],docs)['isolation_match']
    docs,body=response(supplier,case)
    body['run']['details']['retrieved_chunk_ids']*=2
    body['run']['retrieval_count']=2
    assert not score_response(body,'supplier',case,[],docs)['isolation_match']
    body['run']['details']['retrieved_chunk_ids']=['supplier:registration:garbage']
    body['run']['retrieval_count']=1
    assert not score_response(body,'supplier',case,[],docs)['isolation_match']


def test_mixed_ocr_metadata_must_prove_exact_scanned_pages():
    supplier=next(s for s in STRESS if s['slug']=='varsha_facilities')
    docs=[{'filename':name,'page_count':3 if kind!='tax' else 2,
           'text_extraction_method':'mixed','ocr_pages':[2]} for kind,name in supplier['documents'].items()]
    verify_ocr_execution(supplier,docs)
    docs[0]['ocr_pages']=[1]
    with pytest.raises(RuntimeError,match='backend OCR'):verify_ocr_execution(supplier,docs)


def test_summary_separates_upload_processing_q_and_a_and_unscored_annotations():
    supplier,case=CASES[0];docs,body=response(supplier,case)
    q={**case,**score_response(body,'supplier',case,[],docs),'answer':body['answer'],
       'expected_information_found':True,'api_latency_ms':2000,'recorded_latency_ms':1800,
       'retrieval_count':1,'input_tokens':20,'output_tokens':10,'model':'test','prompt_version':'test'}
    results=[{'slug':supplier['slug'],'cohort':'stress','documents':docs,'fields':{'passed':9,'total':9},'questions':[q],
              'rag_only_documents':supplier['rag_only_documents'],'upload':{'api_latency_ms':15000},
              'processing':{'api_latency_ms':18000,'latency_ms':17000,'details':{'policy_assessments':[{'document_id':'insurance','reason':'Unscored model claim'}]}}}]
    summary=build_summary(results,35000)
    assert summary['latency_ms']['average']==2000
    assert summary['stage_timings'][0]['upload_api_ms']==15000
    assert summary['stage_timings'][0]['processing_api_ms']==18000
    assert summary['by_suite']['stress']['total']==1
    assert summary['human_review']['status']=='pending'
    # Document type present in live metadata; add it for scope filter.
    docs[2]['document_type']='insurance'
    summary=build_summary(results,35000)
    assert summary['unscored_policy_annotations'][0]['annotations'][0]['reason']=='Unscored model claim'
    report=render_markdown_report({'evaluated_at':'test','base_url':'http://test','manifest_version':5,'summary':summary})
    assert 'Upload and processing latency' in report and 'isolated OCR duration is not instrumented' in report
    assert 'do not establish insurance compliance' in report and 'Required stress-answer review' in report


def test_upload_failure_is_incomplete_pipeline_run_not_wrong_rag_answer(monkeypatch):
    entry=copy.deepcopy(STRESS[0]);manifest={'version':5,'suppliers':[entry]}
    monkeypatch.setattr('scripts.run_quality_evaluation.validate_manifest',lambda _:manifest)
    def fake_request(method,url,**kwargs):
        if url.endswith('/health'):return {'status':'healthy'}
        if '/portal/auth/' in url:return {'token':'demo'}
        if url.endswith('/suppliers'):return {'id':'supplier'}
        raise AssertionError('Do not call processing or Q&A after rejected intake')
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',fake_request)
    def failed_upload(*args,**kwargs):raise RuntimeError('Upload rejected: scan quality')
    monkeypatch.setattr('scripts.run_quality_evaluation.ensure_documents',failed_upload)
    result=run_evaluation('http://test',MANIFEST,cohort='stress')
    summary=result['summary']
    assert summary['run_status']=='incomplete'
    assert summary['questions_total']==0 and summary['planned_questions']==10 and summary['unexecuted_questions']==10
    assert summary['question_accuracy'] is None and summary['failure_count']==0
    report=render_markdown_report(result)
    assert 'INCOMPLETE RUN' in report and 'pipeline failures, not wrong RAG answers' in report


def test_json_and_markdown_cannot_target_same_file(tmp_path):
    target=tmp_path/'report'
    with pytest.raises(ValueError,match='distinct'):write_reports({},target,target)
    assert not target.exists()


def test_stress_generator_reproducible_native_and_mixed(tmp_path):
    from scripts.generate_stress_evaluation_documents import write_pdf
    pages=[('Native', ['Readable registration facts with sufficient words for native extraction. '*4]),
           ('Scan', ['A readable clause in a scanned attachment, with moderate compression and skew. '*4])]
    first,second=tmp_path/'first.pdf',tmp_path/'second.pdf'
    write_pdf(first,'Supplier Registration Form',pages,[2])
    write_pdf(second,'Supplier Registration Form',pages,[2])
    assert first.read_bytes()==second.read_bytes()
    assert first.with_suffix('.source.txt').read_bytes()==second.with_suffix('.source.txt').read_bytes()


def test_equivalent_payment_triggers_and_corroborating_sources():
    supplier,case=next((s,q) for s,q in CASES if q['id']=='dock_and_payment')
    assert answer_matches('Dock 4, Hoskote Freight Park, Karnataka 562114; Net 45 days from invoice acceptance.',case)
    assert not answer_matches('Dock 4, Hoskote Freight Park, Karnataka 562114; Net 45 days from dispatch.',case)
    supplier,case=CASES[0];docs,body=response(supplier,case)
    body['citations'].append({'filename':supplier['documents']['tax'],'page_number':1,'chunk_id':'supplier:tax:0','excerpt':supplier['create_payload']['name']})
    body['run']['retrieval_count']=2;body['run']['details']['retrieved_chunk_ids'].append('supplier:tax:0')
    assert score_response(body,'supplier',case,[],docs)['passed']
    body['citations']=body['citations'][1:] # Corroboration alone cannot replace requested registration evidence.
    assert not score_response(body,'supplier',case,[],docs)['citation_match']


def test_evaluation_dependencies_are_explicit_and_container_wiring_complete():
    requirements=(ROOT/'backend/requirements.txt').read_text()
    assert 'requests==' in requirements and 'pymupdf==' in requirements
    docker=(ROOT/'Dockerfile').read_text()
    assert 'COPY scripts/run_quality_evaluation.py ./scripts/run_quality_evaluation.py' in docker
    assert 'tesseract-ocr-eng' in docker
    compose=(ROOT/'compose.yaml').read_text()
    assert 'entrypoint: ["python", "scripts/run_quality_evaluation.py"]' in compose
    assert 'http://backend:8000/api' in compose
    assert './sample_documents/evaluation_sets:/app/sample_documents/evaluation_sets' in compose


def test_new_mixed_transcript_windows_newlines_pass_and_modified_content_fails(tmp_path):
    import shutil
    corpus=tmp_path/'corpus';shutil.copytree(MANIFEST.parent,corpus)
    paths=list((corpus/'varsha_facilities').glob('*.source.txt'))
    assert len(paths)==3
    for path in paths:path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
    assert validate_manifest(corpus/MANIFEST.name)['version']==5
    paths[0].write_bytes(paths[0].read_bytes()+b'\r\nChanged actual content')
    with pytest.raises(ValueError,match='transcript checksum mismatch'):validate_manifest(corpus/MANIFEST.name)


def test_compose_argument_override_keeps_backend_url(monkeypatch):
    import sys
    from scripts.run_quality_evaluation import main
    monkeypatch.setenv('EVALUATION_BASE_URL','http://backend:8000/api')
    monkeypatch.setattr(sys,'argv',['evaluation','--cohort','stress'])
    calls=[]
    def fake_run(base_url,*args):
        calls.append((base_url,args[-1]))
        return {'summary':{}}
    monkeypatch.setattr('scripts.run_quality_evaluation.run_evaluation',fake_run)
    monkeypatch.setattr('scripts.run_quality_evaluation.write_reports',lambda *args:None)
    main()
    assert calls==[('http://backend:8000/api','stress')]


def test_incomplete_cli_writes_diagnostic_report_and_returns_nonzero(monkeypatch):
    import sys
    from scripts.run_quality_evaluation import main
    monkeypatch.setattr(sys,'argv',['evaluation'])
    calls=[]
    monkeypatch.setattr('scripts.run_quality_evaluation.run_evaluation',lambda *args:{'summary':{'run_status':'incomplete'}})
    monkeypatch.setattr('scripts.run_quality_evaluation.write_reports',lambda *args:calls.append(args[0]))
    with pytest.raises(SystemExit) as exc:main()
    assert exc.value.code==1 and calls[0]['summary']['run_status']=='incomplete'
