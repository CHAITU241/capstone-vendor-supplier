"""Real supplier-scoped retrieval capture preserves generation and isolates judging."""
import uuid
from types import SimpleNamespace

import chromadb
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import Document, DocumentType, Supplier
from app.services.chunking import TextChunk
from app.services.openai_service import GroundedAnswer, ModelResult, OpenAIService, MetricJudgeFailure
from app.services.rag_evaluation import MetricJudgment, JUDGE_PROMPT_VERSION, validate_evidence, validate_judgment
from app.services.retrieval import replace_document_chunks


@pytest.mark.parametrize('capture',[False,True])
def test_evaluation_capture_keeps_four_model_chunks_but_records_ten_and_judge_is_separate(tmp_path,monkeypatch,capture):
    engine=sa.create_engine('sqlite+pysqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    collection=chromadb.EphemeralClient().get_or_create_collection('metric_capture_'+uuid.uuid4().hex,metadata={'hnsw:space':'cosine'})
    settings=Settings(_env_file=None,upload_dir=tmp_path/'uploads',langfuse_enabled=False,
                      evaluation_judge_model='independent-judge',rag_top_k=4,rag_max_distance=0.72)
    with Session(engine) as db:
        supplier=Supplier(name='Synthetic Evaluation',country='India',is_evaluation=True)
        normal=Supplier(name='Real Application',country='India')
        db.add_all([supplier,normal]);db.flush();sid=str(supplier.id);normal_id=str(normal.id)
        doc=Document(supplier_id=supplier.id,document_type=DocumentType.REGISTRATION,
                     filename='registration.pdf',storage_path='registration.pdf',content_type='application/pdf',file_size=100,page_count=1)
        db.add(doc);db.flush();did=str(doc.id);db.commit()
    chunks=[TextChunk(index=i,page_number=1,text=f'Clause {i}. Payment is Net 45 days from accepted invoice.',token_count=12) for i in range(12)]
    replace_document_chunks(collection,sid,did,'registration.pdf',chunks,[[1.0,0.01*i,0.0] for i in range(12)])
    replace_document_chunks(collection,'foreign','foreign-doc','foreign.pdf',[TextChunk(index=0,page_number=1,text='Foreign secret',token_count=2)],[[1.0,0.0,0.0]])
    calls=[]
    class AI:
        def embed(self,texts):
            calls.append('embed');return SimpleNamespace(embeddings=[[1.0,0.0,0.0]],input_tokens=5)
        def answer_question(self,question,evidence):
            calls.append('answer');assert evidence.count('[Chunk ')==4
            assert 'Foreign secret' not in evidence
            return ModelResult(value=GroundedAnswer(answer='Payment is Net 45 days from accepted invoice.',information_found=True,cited_chunk_ids=['chunk_1']),input_tokens=100,output_tokens=12)
        def judge_rag_evidence(self,evidence):
            calls.append('judge');context=evidence['generation_context'][0]
            return ModelResult(value=MetricJudgment(relevance=[{'chunk_id':c['chunk_id'],'relevant':True,'rationale':'Payment clause'} for c in evidence['retrieval_top_10']],
                               claims=[{'claim':evidence['answer'],'answer_start':0,'answer_end':len(evidence['answer']),'supported':True,'support_kind':'explicit','support':[{'chunk_id':context['chunk_id'],'quote':'Payment is Net 45 days from accepted invoice.'}],'rationale':'Explicit terms'}]),input_tokens=200,output_tokens=40)
    def db_override():
        with Session(engine) as db:yield db
    app.dependency_overrides[get_db]=db_override
    app.dependency_overrides[get_settings]=lambda:settings
    monkeypatch.setattr('app.routers.ai.get_chunk_collection',lambda:collection)
    monkeypatch.setattr('app.routers.ai._get_ai_service',lambda:AI())
    try:
        with TestClient(app) as client:
            token=client.post('/api/portal/auth/reviewer-demo').json()['token'];headers={'Authorization':f'Bearer {token}'}
            response=client.post(f'/api/suppliers/{sid}/questions',json={'question':'What are payment terms?','capture_evaluation_evidence':capture},headers=headers)
            assert response.status_code==200,response.text
            body=response.json();details=body['run']['details'];rid=body['run']['id']
            assert body['run']['retrieval_count']==4 and body['run']['input_tokens']==105
            assert calls==['embed','answer']
            if capture:
                evidence=details['evaluation_evidence']
                assert len(evidence['retrieval_top_10'])==10 and evidence['supplier_chunk_count']==12
                assert len(evidence['generation_context'])==4
                assert [c['chunk_id'] for c in evidence['generation_context']]==details['retrieved_chunk_ids']
                assert evidence['generation_evidence_text'].count('[Chunk ')==4
                validate_evidence(evidence,sid,[{'id':did,'filename':'registration.pdf','page_count':1}])
                judged=client.post(f'/api/suppliers/{sid}/evaluation/judge',json={'run_id':rid},headers=headers)
                assert judged.status_code==200,judged.text
                assert judged.json()['model_or_reviewer']=='independent-judge'
                validate_judgment(judged.json()['labels'],evidence)
                assert calls==['embed','answer','judge']
                assert judged.json()['prompt_version']==JUDGE_PROMPT_VERSION
                def fail_judge(evidence):
                    raise MetricJudgeFailure('Invalid support after three attempts',
                        [{'stage':'faithfulness','attempt':1,'status':'rejected','reason':'Invalid quote',
                          'input_tokens':123,'output_tokens':45,'latency_ms':50,'usage_recorded':True}], {})
                monkeypatch.setattr(AI,'judge_rag_evidence',lambda self,evidence:fail_judge(evidence))
                failed=client.post(f'/api/suppliers/{sid}/evaluation/judge',json={'run_id':rid},headers=headers)
                assert failed.status_code==422
                audit=failed.json()['metric_judgment']
                assert audit['input_tokens']==123 and audit['attempts'][0]['reason']=='Invalid quote'
                assert audit['evidence_sha256']==judged.json()['evidence_sha256']
            else:
                assert 'evaluation_evidence' not in details
                assert client.post(f'/api/suppliers/{sid}/evaluation/judge',json={'run_id':rid},headers=headers).status_code==409
            assert client.post(f'/api/suppliers/{normal_id}/questions',json={'question':'Payment terms?','capture_evaluation_evidence':True},headers=headers).status_code==400
            assert client.post(f'/api/suppliers/{normal_id}/evaluation/judge',json={'run_id':rid},headers=headers).status_code==400
            assert client.post(f'/api/suppliers/{sid}/evaluation/judge',json={'run_id':str(uuid.uuid4())},headers=headers).status_code==409
            assert client.post(f'/api/suppliers/{sid}/evaluation/judge',json={'run_id':rid}).status_code==401
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_abstention_without_candidates_needs_no_claim_judge_call():
    client=SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        parse=lambda **kwargs: pytest.fail("An abstention has no claim denominator")))))
    service=OpenAIService(client,Settings(_env_file=None,evaluation_judge_model='judge-model',langfuse_enabled=False))
    evidence={'question':'Unsupported value?','answer':'Information not found in uploaded supplier documents.',
              'information_found':False,'retrieval_top_10':[],'generation_context':[],
              'reference_answer':'Must never reach the judge'}
    result=service.judge_rag_evidence(evidence)
    assert result.value.claims==[] and result.input_tokens==0 and result.output_tokens==0
