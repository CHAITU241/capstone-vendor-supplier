"""Saved-run calibration: equivalent answers pass; wrong facts and evidence still fail."""
import copy
import json
from pathlib import Path

import pytest

from scripts.run_quality_evaluation import answer_matches, score_response, validate_manifest
from scripts.generate_stress_evaluation_documents import apply_scoring_revision

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / 'sample_documents/evaluation_sets/evaluation_manifest.json'
MANIFEST = json.loads(MANIFEST_PATH.read_text())
INS = '03_certificate_of_liability_insurance.pdf'
REG = '01_supplier_registration_form.pdf'
TAX = '02_gst_registration_certificate.pdf'


def case_for(slug, qid):
    supplier = next(s for s in MANIFEST['suppliers'] if s['slug'] == slug)
    return supplier, next(q for q in supplier['questions'] if q['id'] == qid)


def grade(slug, qid, answer, pages):
    supplier, case = case_for(slug, qid)
    documents = [{'id': name, 'filename': name, 'page_count': 10}
                 for name in supplier['documents'].values()]
    citations = [{'filename': name, 'page_number': page,
                  'chunk_id': f'supplier:{name}:{page-1}', 'excerpt': 'Pinned page support.'}
                 for name, page in pages]
    body = {'answer': answer, 'information_found': True, 'citations': citations,
            'run': {'retrieval_count': len(citations),
                    'details': {'retrieved_chunk_ids': [c['chunk_id'] for c in citations]}}}
    return score_response(body, 'supplier', case, [], documents)


CALIBRATED = [
    ('dakshin_logistics', 'transit_limit', 'The road-transit limit per consignment is INR 20,00,000. This limit applies to goods during the declared road journey and is separate from the warehouse storage limit, which is INR 50,00,000 per occurrence at an approved warehouse.', [(INS,2),(INS,3)]),
    ('amrutha_food', 'original_aggregate', 'INR 20,00,000', [(INS,2)]),
    ('amrutha_food', 'before_e2_effective', "No, AP may not record E2's higher annual aggregate as of 20 July 2027 because E2's effective date is 01 August 2027. The applicable limit before that date is E1's INR 30,00,000 annual aggregate.", [(INS,4),(INS,3)]),
    ('varsha_facilities', 'height_without_permit', 'No, the declared working-at-height extension does not cover it.', [(INS,3)]),
    ('chitra_components', 'pickup_depot', 'Bay 9, Nelamangala Freight Yard, Bengaluru, Karnataka 562123', [(REG,2),(TAX,2)]),
    ('udaya_maintenance', 'permit_without_watch', 'No, the submitted hot-work extension does not cover this situation.', [(INS,3)]),
]


@pytest.mark.parametrize('slug,qid,answer,pages', CALIBRATED)
def test_six_correct_saved_responses_pass(slug,qid,answer,pages):
    assert grade(slug,qid,answer,pages)['passed']


@pytest.mark.parametrize('slug,qid,answer,pages', [CALIBRATED[i] for i in (0,2,4)])
def test_corroboration_cannot_replace_primary_or_allow_unrelated_page(slug,qid,answer,pages):
    assert not grade(slug,qid,answer,pages[1:])['citation_match']
    assert not grade(slug,qid,answer,pages+[(INS,1)])['citation_match']


@pytest.mark.parametrize('answer', ['INR 20 lakh', 'Rs. 2,000,000', '20 lakh rupees', '₹2000000.', 'The original annual aggregate is INR 20,00,000.'])
def test_single_amount_equivalents_pass(answer):
    assert answer_matches(answer, case_for('amrutha_food','original_aggregate')[1])


@pytest.mark.parametrize('answer', ['INR 30,00,000', '2000000', 'Deductible INR 20,00,000', 'The per-occurrence limit is INR 20,00,000', 'INR 20 lakh and INR 30 lakh', 'No INR 20 lakh'])
def test_scalar_exception_does_not_accept_wrong_value_or_basis(answer):
    assert not answer_matches(answer, case_for('amrutha_food','original_aggregate')[1])


@pytest.mark.parametrize('qid,slug', [('height_without_permit','varsha_facilities'),('permit_without_watch','udaya_maintenance')])
@pytest.mark.parametrize('answer', ['No.', 'It is not covered.', 'It is excluded from the extension.', 'The extension does not cover this situation.'])
def test_unambiguous_denial_equivalents_pass(qid,slug,answer):
    assert grade(slug,qid,answer,[(INS,3)])['passed']


@pytest.mark.parametrize('qid,slug', [('height_without_permit','varsha_facilities'),('permit_without_watch','udaya_maintenance')])
@pytest.mark.parametrize('answer', ['Yes, it is covered.', 'No, but it is covered.', 'No, it can be covered.', 'No, yes it is covered.', 'It does cover work without the permit or fire watch.', 'It is not excluded.', 'Perhaps it is excluded.', 'No information about this.', 'A permit and fire watch are mentioned.'])
def test_coverage_keywords_cannot_hide_affirmation_or_uncertainty(qid,slug,answer):
    assert not grade(slug,qid,answer,[(INS,3)])['answer_match']


@pytest.mark.parametrize('slug,qid,answer,pages', [
    ('coromandel_sensor_systems','insurance_provider_and_expiry','Liability insurer: HarborPoint General Insurance Company Limited; Policy expiry date: 30 JUN 2027.',[(INS,1),(REG,1)]),
    ('tungabhadra_industrial_services','insurance_diary','30 JUN 2027',[(INS,1)]),
    ('amrutha_food','missing_recall_limit','INR 40,00,000',[(INS,4)]),
    ('varsha_facilities','operating_site_and_property',"The service-establishment address is Suite 6, Yelahanka Service Centre, Bengaluru, Karnataka 560064. The sublimit that applies to customer property in the supplier's care, custody, and control is not specified in the provided evidence.",[(TAX,2),(REG,1)]),
    ('chitra_components','claims_routing',"Insurance claims correspondence is routed to the Claims Desk at 2, Residency Road, Bengaluru, Karnataka 560025. This is the insurer's routing address.",[(INS,2)]),
])
def test_remaining_saved_failures_are_not_relaxed(slug,qid,answer,pages):
    assert not grade(slug,qid,answer,pages)['passed']


def test_revision_changes_only_six_rubrics_and_no_documents_or_questions():
    previous = json.loads((MANIFEST_PATH.parent/'evaluation_manifest_v5_scoring_v1.json').read_text())
    assert MANIFEST['scoring_revision'] == 2
    changed = []
    for before, after in zip(previous['suppliers'], MANIFEST['suppliers'], strict=True):
        assert {k:v for k,v in before.items() if k!='questions'} == {k:v for k,v in after.items() if k!='questions'}
        for old, new in zip(before['questions'], after['questions'], strict=True):
            assert old['question'] == new['question']
            assert old.get('required_sources') == new.get('required_sources')
            assert old.get('citation_requirements') == new.get('citation_requirements')
            if old != new:
                changed.append((after['slug'],new['id']))
                reproduced=copy.deepcopy(old)
                apply_scoring_revision(reproduced)
                assert reproduced == new
    assert set(changed) == {(s,q) for s,q,_,_ in CALIBRATED}
    validate_manifest(MANIFEST_PATH)
