"""Evaluation records are retained, but never populate the reviewer worklist."""
import importlib.util
import io
import json
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app
from app.models import Supplier
from scripts.run_quality_evaluation import create_evaluation_supplier

ROOT = Path(__file__).resolve().parents[2]


def migration_module():
    path = ROOT/'backend/alembic/versions/0022_evaluation_suppliers.py'
    spec = importlib.util.spec_from_file_location('evaluation_supplier_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reviewer_worklist_hides_evaluation_but_keeps_records_and_normal_applications(tmp_path):
    engine = sa.create_engine('sqlite+pysqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db_override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path/'uploads', chroma_path=tmp_path/'chroma', upload_ai_validation_enabled=False,
        admin_auth_enabled=True, admin_email='owner@example.com', admin_password='strong-admin-password',
    )
    try:
        with TestClient(app) as client:
            token=client.post('/api/portal/auth/reviewer-demo').json()['token']
            headers={'Authorization':f'Bearer {token}'}
            payload={'name':'Kaveri Flow Controls Private Limited','country':'India','contact_email':'ananya.rao@example.com'}
            normal=client.post('/api/suppliers',json=payload,headers=headers)
            assert normal.status_code==201 and normal.json()['is_evaluation'] is False
            test=client.post('/api/suppliers',json={**payload,'is_evaluation':True},headers=headers)
            assert test.status_code==201 and test.json()['is_evaluation'] is True
            normal_id=normal.json()['id'];test_id=test.json()['id']
            rows=client.get('/api/suppliers',headers=headers).json()
            assert [row['id'] for row in rows]==[normal_id]
            # ID-based evidence/processing APIs used by the evaluator remain accessible.
            detail=client.get(f'/api/suppliers/{test_id}',headers=headers)
            assert detail.status_code==200 and detail.json()['is_evaluation'] is True
            admin=client.post('/api/portal/auth/admin',json={'email':'owner@example.com','password':'strong-admin-password'})
            access={'Authorization':f"Bearer {admin.json()['token']}"}
            assert {x['id'] for x in client.get('/api/admin/profiles',headers=access).json()}=={normal_id,test_id}
            own=client.post('/api/portal/auth/register',json={'email':'normal@example.com','password':'normal-password'})
            own_headers={'Authorization':f"Bearer {own.json()['token']}"}
            assert client.post('/api/suppliers',json={**payload,'is_evaluation':True},headers=own_headers).status_code==403
            with Session(engine) as db:
                assert db.get(Supplier,UUID(test_id)).is_evaluation is True
                assert db.get(Supplier,UUID(normal_id)).is_evaluation is False
                assert db.scalar(sa.select(Supplier).where(Supplier.account_id.is_not(None))).is_evaluation is False
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_migration_marks_all_known_runs_without_hiding_similar_real_or_portal_suppliers():
    module=migration_module()
    manifest=json.loads((ROOT/'sample_documents/evaluation_sets/evaluation_manifest.json').read_text())
    assert set(module.LEGACY_EVALUATION_IDENTITIES)=={(s['create_payload']['name'],s['create_payload']['contact_email']) for s in manifest['suppliers']}
    engine=sa.create_engine('sqlite+pysqlite://')
    metadata=sa.MetaData()
    old=sa.Table('suppliers',metadata,sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String()),
                 sa.Column('contact_email',sa.String()),sa.Column('country',sa.String()),sa.Column('account_id',sa.String()),
                 sa.Column('category',sa.String()),sa.Column('subcategory',sa.String()),sa.Column('status',sa.String()))
    metadata.create_all(engine)
    with engine.begin() as conn:
        originals=[]
        for name,email in module.LEGACY_EVALUATION_IDENTITIES:
            # Repeated runs create independent rows; cover both retained IDs.
            for _ in range(2):
                originals.append({'id':len(originals)+1,'name':name,'contact_email':email,'country':'India','status':'needs_review'})
        name,email=module.LEGACY_EVALUATION_IDENTITIES[0]
        base={'name':name,'contact_email':email,'country':'India','status':'submitted'}
        for changes in ({'name':'Another Supplier'}, {'contact_email':'real@example.com'}, {'account_id':'a-real-account'},
                        {'category':'GOODS'}, {'subcategory':'GOODS-OFF'}, {'country':'Canada'}, {'contact_email':None}):
            originals.append({**base,**changes,'id':len(originals)+1})
        # SQLite executemany needs a uniform set of columns.
        originals=[{**{'account_id':None,'category':None,'subcategory':None},**x} for x in originals]
        conn.execute(old.insert(),originals)
        module.op=Operations(MigrationContext.configure(conn))
        module.upgrade()
        rows=conn.execute(sa.text('SELECT * FROM suppliers ORDER BY id')).mappings().all()
        assert len(rows)==37
        for i,(before,after) in enumerate(zip(originals,rows,strict=True)):
            assert after['is_evaluation']==(i<30)
            assert {k:after[k] for k in before}==before # No original record is removed or edited.
        # DB/server default also keeps new ordinary applications visible.
        conn.execute(old.insert(),{'id':38,'name':'Real new supplier','country':'India'})
        assert conn.execute(sa.text('SELECT is_evaluation FROM suppliers WHERE id=38')).scalar()==0
        module.downgrade()
        assert conn.execute(sa.text('SELECT count(*) FROM suppliers')).scalar()==38
        assert 'is_evaluation' not in {c['name'] for c in sa.inspect(conn).get_columns('suppliers')}


def test_migration_emits_valid_postgres_default_and_exact_identity_conditions():
    module=migration_module();out=io.StringIO()
    module.op=Operations(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'literal_binds':True,'output_buffer':out}))
    module.upgrade()
    sql=out.getvalue()
    assert 'ADD COLUMN is_evaluation BOOLEAN DEFAULT false NOT NULL' in sql
    assert 'account_id IS NULL' in sql and 'category IS NULL' in sql
    assert 'SET is_evaluation=true' in sql
    assert all(name in sql and email in sql for name,email in module.LEGACY_EVALUATION_IDENTITIES)


def test_evaluator_explicitly_marks_new_records_without_mutating_manifest_payload(monkeypatch):
    original={'name':'Synthetic evaluation supplier','country':'India'};observed=[]
    def request(method,url,**kwargs):
        observed.append((method,url,kwargs))
        return {'id':'new-evaluation-id','is_evaluation':True}
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',request)
    result=create_evaluation_supplier('http://backend/api',original,{'Authorization':'Bearer reviewer'})
    assert result['is_evaluation'] is True
    assert observed[0][2]['json']=={**original,'is_evaluation':True}
    assert 'is_evaluation' not in original


def test_evaluator_stops_if_outdated_backend_does_not_support_isolation(monkeypatch):
    monkeypatch.setattr('scripts.run_quality_evaluation.request_json',lambda *a,**k:{'id':'old-backend-id'})
    with pytest.raises(RuntimeError,match='rebuild the backend'):
        create_evaluation_supplier('http://backend/api',{'name':'Synthetic supplier'}, {})
