"""Semantic labels remain auditable; incomplete evidence cannot become a score."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.rag_evaluation import (
    EVIDENCE_VERSION, chunk_snapshot, fingerprint, metric_summary, question_metrics,
    validate_evidence, validate_judgment,
)
from scripts.run_quality_evaluation import main, render_evidence_metrics, judge_report


def fixture():
    chunks=[chunk_snapshot(SimpleNamespace(chunk_id=f'supplier:doc:{i}',document_id='doc',
            filename='registration.pdf',page_number=1,text=text,distance=0.1+i/10),i+1)
            for i,text in enumerate(['Payment is Net 45 days from accepted invoice.',
                                     'Warehouse is Dock 4.', 'Dispatch contact is Ananya.'])]
    evidence={'version':EVIDENCE_VERSION,'question':'What are the payment terms?',
              'answer':'Payment is Net 45 days from accepted invoice. There is no deductible.',
              'information_found':True,'retrieval_k':10,'supplier_chunk_count':3,
              'generation_top_k':4,'retrieval_top_10':chunks,'generation_context':chunks[:1]}
    labels={'relevance':[{'chunk_id':c['chunk_id'],'relevant':i==0,'rationale':'Payment clause' if i==0 else 'Unrelated role'} for i,c in enumerate(chunks)],
            'claims':[{'claim':'Payment is Net 45 days from accepted invoice.','supported':True,
                       'support':[{'chunk_id':chunks[0]['chunk_id'],'quote':chunks[0]['text']}],'rationale':'Explicit terms'},
                      {'claim':'There is no deductible.','supported':False,'support':[], 'rationale':'Not in context'}]}
    judgment={'status':'completed','method':'llm_judge','model_or_reviewer':'independent-judge',
              'assessed_at':'2026-10-08T10:00:00+00:00','evidence_sha256':fingerprint(evidence),
              'prompt_version':'rag-metric-judge-v1','labels':labels,'input_tokens':50,'output_tokens':20,'latency_ms':100}
    q={'id':'payment','question':'What are the payment terms?','answer':evidence['answer'],
       'expected_information_found':True,'information_found':True,'retrieved_chunk_ids':[chunks[0]['chunk_id']],
       'metric_evidence':evidence,'metric_judgment':judgment}
    docs=[{'id':'doc','filename':'registration.pdf','page_count':1}]
    return {'slug':'example','supplier_id':'supplier','documents':docs,'questions':[q]},q


def test_precision_uses_ten_positions_not_number_of_returned_chunks():
    s,q=fixture();m=question_metrics(q,s['supplier_id'],s['documents'])
    assert m['precision_at_10']==0.1 and m['returned_precision']==1/3
    assert m['corpus_size_ceiling']==0.3 and m['faithfulness']==0.5
    assert m['supported_claims']==1 and m['claims_total']==2 and m['fully_supported'] is False
    summary=metric_summary([s])
    assert summary['precision_at_10']['value']==0.1
    assert summary['faithfulness']['value']==0.5
    assert summary['judging']['input_tokens']==50


@pytest.mark.parametrize('mutation', ['missing_rank','duplicate_rank','wrong_supplier','tampered_text','wrong_page','generation_text_changed'])
def test_snapshot_rejects_incomplete_or_foreign_or_changed_evidence(mutation):
    s,q=fixture();e=q['metric_evidence'];top=e['retrieval_top_10']
    if mutation=='missing_rank':top.pop()
    elif mutation=='duplicate_rank':top[1]['rank']=1
    elif mutation=='wrong_supplier':top[1]['chunk_id']='other:doc:1'
    elif mutation=='tampered_text':top[1]['text']='Rewritten gold answer'
    elif mutation=='wrong_page':top[1]['page_number']=2
    else:
        e['generation_context']=copy.deepcopy(e['generation_context'])
        e['generation_context'][0]['text']='Changed context'
        e['generation_context'][0]['text_sha256']=hashlib.sha256(b'Changed context').hexdigest()
    with pytest.raises(ValueError):validate_evidence(e,s['supplier_id'],s['documents'])
    assert question_metrics(q,s['supplier_id'],s['documents'])['precision_at_10'] is None


@pytest.mark.parametrize('mutation', ['missing_label','duplicate_label','string_boolean','outside_context','invented_quote','empty_claims','unsupported_with_support','changed_provenance','duplicate_claim'])
def test_invalid_semantic_judgments_cannot_produce_scores(mutation):
    s,q=fixture();j=q['metric_judgment'];labels=j['labels']
    if mutation=='missing_label':labels['relevance'].pop()
    elif mutation=='duplicate_label':labels['relevance'][1]=copy.deepcopy(labels['relevance'][0])
    elif mutation=='string_boolean':labels['relevance'][0]['relevant']='true'
    elif mutation=='outside_context':labels['claims'][0]['support']=[{'chunk_id':'supplier:doc:1','quote':'Warehouse is Dock 4.'}]
    elif mutation=='invented_quote':labels['claims'][0]['support'][0]['quote']='Net 60 days'
    elif mutation=='empty_claims':labels['claims']=[]
    elif mutation=='unsupported_with_support':labels['claims'][0]['supported']=False
    elif mutation=='duplicate_claim':labels['claims'].append(copy.deepcopy(labels['claims'][0]))
    else:j['evidence_sha256']='wrong'
    m=question_metrics(q,s['supplier_id'],s['documents'])
    assert m['validation_error'] and m['precision_at_10'] is None and m['faithfulness'] is None


def test_partial_coverage_never_advertises_full_set_score():
    s,q=fixture();pending=copy.deepcopy(q);pending['id']='pending';pending.pop('metric_judgment');s['questions'].append(pending)
    metrics=metric_summary([s])
    assert metrics['precision_at_10']['value'] is None
    assert metrics['precision_at_10']['scored_subset_value']==0.1
    assert metrics['faithfulness']['value'] is None and metrics['faithfulness']['pending_questions']==1


def test_abstention_has_no_faithfulness_denominator_and_unsupported_assertion_is_included():
    s,q=fixture();q['expected_information_found']=False
    m=question_metrics(q,s['supplier_id'],s['documents'])
    assert m['precision_status']=='not_applicable' and m['faithfulness']==0.5
    q['information_found']=False;q['metric_evidence']['information_found']=False
    q['metric_judgment']['labels']['claims']=[];q['metric_judgment']['evidence_sha256']=fingerprint(q['metric_evidence'])
    m=question_metrics(q,s['supplier_id'],s['documents'])
    assert m['faithfulness_status']=='not_applicable' and m['faithfulness'] is None


def test_no_snapshot_no_fabricated_metric_and_clear_report():
    s,q=fixture();q.pop('metric_evidence')
    metrics=metric_summary([s]);report='\n'.join(render_evidence_metrics({'suppliers':[s],'summary':{'evidence_metrics':metrics}}))
    assert metrics['faithfulness']['value'] is None and 'Full ranked chunk text/context was not captured' in report
    assert metrics['precision_at_10']['short_corpus_questions'] is None
    assert 'unfilled positions contribute zero' in report and 'not aliases' in report


def test_judge_error_preserves_observations_and_pending_metrics(monkeypatch):
    s,q=fixture();q['run_id']='run';q.pop('metric_judgment')
    original=copy.deepcopy(q);result={'suppliers':[s],'summary':{}}
    def fail(*args,**kwargs):raise RuntimeError('Judge unavailable')
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',fail)
    judge_report(result,'http://api',{})
    assert q['answer']==original['answer'] and q['metric_evidence']==original['metric_evidence']
    assert q['metric_judgment']['status']=='error' and result['summary']['evidence_metrics']['faithfulness']['value'] is None


def test_recalculation_uses_saved_labels_without_network_or_changing_source(tmp_path,monkeypatch):
    s,q=fixture();source=tmp_path/'source.json';source.write_text(json.dumps({'suppliers':[s],'summary':{}}))
    before=source.read_bytes();out=tmp_path/'metrics.json';md=tmp_path/'metrics.md';written=[]
    monkeypatch.setattr('sys.argv',['evaluation','--metrics-from-report',str(source),'--output',str(out),'--report-output',str(md)])
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',lambda *a,**k:pytest.fail('No network'))
    monkeypatch.setattr('scripts.run_quality_evaluation.write_reports',lambda result,*paths:written.append(result))
    main()
    assert source.read_bytes()==before and written[0]['summary']['evidence_metrics']['faithfulness']['value']==0.5
    assert written[0]['suppliers'][0]['questions'][0]['answer']==q['answer']


def test_macro_claim_score_and_micro_claim_support_have_distinct_denominators():
    s,q=fixture();second=copy.deepcopy(q);second['id']='single-claim'
    second['metric_judgment']['labels']['claims']=second['metric_judgment']['labels']['claims'][:1]
    s['questions'].append(second);metrics=metric_summary([s])
    assert metrics['faithfulness']['value']==0.75
    assert metrics['faithfulness']['micro_claim_support']==0.6667
    assert metrics['faithfulness']['fully_supported_answers']==1


def test_judging_resumes_without_repeating_completed_calls(monkeypatch):
    s,q=fixture();result={'suppliers':[s],'summary':{}}
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',lambda *a,**k:pytest.fail('Valid prior judgment must be preserved'))
    judge_report(result,'http://api',{})
    assert result['summary']['evidence_metrics']['faithfulness']['value']==0.5


def test_formatted_generation_context_cannot_diverge_from_chunk_text():
    s,q=fixture();q['metric_evidence']['generation_evidence_text']='Different model evidence'
    with pytest.raises(ValueError,match='Formatted model evidence'):
        validate_evidence(q['metric_evidence'],s['supplier_id'],s['documents'])


def test_support_quote_accepts_pdf_line_wrapping_without_repairing_facts():
    s,q=fixture();labels=q['metric_judgment']['labels'];evidence=q['metric_evidence']
    evidence['generation_context'][0]['text']='Payment is Net 45 days\nfrom accepted invoice.'
    evidence['generation_context'][0]['text_sha256']=hashlib.sha256(evidence['generation_context'][0]['text'].encode()).hexdigest()
    validate_judgment(labels,evidence)
    labels['claims'][0]['support'][0]['quote']='Payment is Net 60 days from accepted invoice.'
    with pytest.raises(ValueError,match='Support quotes'):validate_judgment(labels,evidence)
