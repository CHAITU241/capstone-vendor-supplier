"""Exercise malformed provider outputs and isolate the two semantic input scopes."""
import copy
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.services.openai_service import OpenAIService, MetricJudgeFailure
from app.services.rag_evaluation import (
    JUDGE_PROMPT_VERSION, RELEVANCE_PROMPT, FAITHFULNESS_PROMPT,
    validate_judgment, chunk_snapshot,
)
from scripts.run_quality_evaluation import judge_report, EvaluationRequestError
from test_rag_evidence_metrics import fixture


class UncheckedOutput(BaseModel):
    model_config = ConfigDict(extra="allow")


def service_with_provider(outputs):
    """Return loose provider models, so production schema validation is exercised."""
    calls = []
    options = []
    def parse(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        item = outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        parsed = UncheckedOutput.model_validate(item)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            parsed=parsed, content=json.dumps(item)))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))
    client = SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))))
    client.with_options = lambda **kwargs: options.append(kwargs) or client
    service = OpenAIService(client, Settings(_env_file=None, evaluation_judge_model="independent-judge", langfuse_enabled=False))
    return service, calls, options


def inputs():
    s, q = fixture()
    evidence = copy.deepcopy(q["metric_evidence"])
    # This audit-only fact must never reach faithfulness, even on validation retry.
    evidence["retrieval_top_10"][1]["text"] = "AUDIT_ONLY_SECRET: deductible is INR 20,000."
    relevance = {f"candidate_{i}": {"relevant": i == 1, "rationale": "Relevant payment clause" if i == 1 else "Other facts"}
                 for i in range(1, 4)}
    claims = {"claims": [{"claim": "Payment is Net 45 days from accepted invoice.", "supported": True,
                         "support_kind": "explicit", "support": [{"chunk_id": "context_1", "quote": "Payment is Net 45 days from accepted invoice."}],
                         "rationale": "Explicit context"},
                        {"claim": "There is no deductible.", "supported": False, "support_kind": "unsupported",
                         "support": [], "rationale": "No evidence establishes an actual deductible of zero"}]}
    return evidence, relevance, claims


def test_two_requests_have_separate_scopes_fixed_slots_and_short_ids():
    evidence, relevance, claims = inputs()
    service, calls, options = service_with_provider([relevance, claims])
    result = service.judge_rag_evidence(evidence)
    assert len(calls) == 2 and options == [{"timeout": 60.0, "max_retries": 0}]
    rel_payload = json.loads(calls[0]["messages"][1]["content"])
    faith_payload = json.loads(calls[1]["messages"][1]["content"])
    assert "answer" not in rel_payload and "generation_context" not in rel_payload
    assert "AUDIT_ONLY_SECRET" in calls[0]["messages"][1]["content"]
    assert "AUDIT_ONLY_SECRET" not in json.dumps(calls[1]["messages"])
    assert set(faith_payload) == {"question", "answer", "information_found", "generation_context"}
    assert set(calls[0]["response_format"].model_json_schema()["required"]) == {"candidate_1", "candidate_2", "candidate_3"}
    assert set(faith_payload["generation_context"]) == {"context_1"}
    assert result.value.claims[0].support[0].chunk_id == evidence["generation_context"][0]["chunk_id"]
    assert result.input_tokens == 200 and result.output_tokens == 40
    assert set(result.stage_provenance) == {"relevance", "faithfulness"}
    assert all(a["status"] == "accepted" for a in result.attempts)


@pytest.mark.parametrize("mutation", ["missing_candidate", "invented_candidate", "string_boolean"])
def test_invalid_relevance_is_retried_not_filled_or_silently_accepted(mutation):
    evidence, relevance, claims = inputs()
    bad = copy.deepcopy(relevance)
    if mutation == "missing_candidate":
        bad.pop("candidate_3")
    elif mutation == "invented_candidate":
        bad["candidate_99"] = bad.pop("candidate_3")
    else:
        bad["candidate_1"]["relevant"] = "true"
    service, calls, _ = service_with_provider([bad, relevance, claims])
    result = service.judge_rag_evidence(evidence)
    assert len(calls) == 3 and len(result.value.relevance) == 3
    assert result.attempts[0]["status"] == "rejected"
    assert result.input_tokens == 300
    assert "previous assessment was rejected" in calls[1]["messages"][-1]["content"]
    assert result.value.relevance[2].relevant is False


@pytest.mark.parametrize("mutation", ["paraphrased_quote", "audit_id", "joined_quote", "wrong_support_kind"])
def test_bad_faithfulness_support_retries_without_exposing_audit(mutation):
    evidence, relevance, claims = inputs()
    bad = copy.deepcopy(claims)
    support = bad["claims"][0]["support"][0]
    if mutation == "paraphrased_quote":
        support["quote"] = "Payment is Net 60 days from accepted invoice."
    elif mutation == "audit_id":
        support["chunk_id"] = "context_2"
    elif mutation == "joined_quote":
        support["quote"] = "Payment is ... from accepted invoice."
    else:
        bad["claims"][0]["support_kind"] = "unsupported"
    service, calls, _ = service_with_provider([relevance, bad, claims])
    result = service.judge_rag_evidence(evidence)
    assert result.attempts[1]["status"] == "rejected"
    assert result.attempts[1].get("output") or result.attempts[1].get("raw_output")
    assert all("AUDIT_ONLY_SECRET" not in json.dumps(call["messages"]) for call in calls[1:])
    assert result.value.claims[0].support[0].quote == "Payment is Net 45 days from accepted invoice."


def test_exhausted_retries_preserve_rejected_outputs_and_observed_usage():
    evidence, relevance, claims = inputs()
    bad = {"candidate_1": relevance["candidate_1"]}
    service, calls, _ = service_with_provider([bad, bad, bad])
    with pytest.raises(MetricJudgeFailure) as err:
        service.judge_rag_evidence(evidence)
    assessment = err.value.assessment()
    assert len(calls) == 3 and assessment["status"] == "error"
    assert assessment["input_tokens"] == 300 and assessment["output_tokens"] == 60
    assert len(assessment["attempts"]) == 3
    assert all(a["usage_recorded"] and a["raw_output"] for a in assessment["attempts"])


def test_provider_failure_is_visible_without_validation_retry_or_known_usage():
    evidence, relevance, claims = inputs()
    service, calls, _ = service_with_provider([RuntimeError("Provider unavailable")])
    with pytest.raises(MetricJudgeFailure) as err:
        service.judge_rag_evidence(evidence)
    assert len(calls) == 1 and err.value.attempts[0]["usage_recorded"] is False


def test_inference_can_quote_premises_without_the_conclusion_being_verbatim():
    evidence, relevance, claims = inputs()
    evidence["generation_context"] = evidence["retrieval_top_10"][:2]
    evidence["generation_context"][0]["text"] = "Registration payment terms: Net 30 days."
    evidence["generation_context"][1]["text"] = "Tax payment terms: Net 60 days."
    claims = {"claims": [{"claim": "The conflicting payment terms require clarification.", "supported": True,
                         "support_kind": "inference", "rationale": "The two originals disagree; neither is declared authoritative.",
                         "support": [{"chunk_id": "context_1", "quote": "Registration payment terms: Net 30 days."},
                                     {"chunk_id": "context_2", "quote": "Tax payment terms: Net 60 days."}]}]}
    service, calls, _ = service_with_provider([relevance, claims])
    result = service.judge_rag_evidence(evidence)
    assert result.value.claims[0].support_kind == "inference"
    assert "An inference need not occur word for word" in FAITHFULNESS_PROMPT


def test_context_absence_requires_every_actual_context_chunk_not_the_full_corpus():
    evidence, relevance, claims = inputs()
    evidence["generation_context"] = evidence["retrieval_top_10"][::2]
    claims = {"claims": [{"claim": "The deductible is not specified in the provided context.", "supported": True,
                         "support_kind": "context_absence", "rationale": "Neither of the two supplied chunks gives a deductible.",
                         "support": [{"chunk_id": "context_1", "quote": evidence["generation_context"][0]["text"]},
                                     {"chunk_id": "context_2", "quote": evidence["generation_context"][1]["text"]}]}]}
    bad = copy.deepcopy(claims); bad["claims"][0]["support"].pop()
    service, calls, _ = service_with_provider([relevance, bad, claims])
    result = service.judge_rag_evidence(evidence)
    assert len(calls) == 3 and result.value.claims[0].support_kind == "context_absence"
    assert "full corpus" in FAITHFULNESS_PROMPT


def test_v1_is_preserved_but_reassessed_and_v2_resumes(monkeypatch, capsys):
    s, q = fixture(); q["run_id"] = "saved-run"
    prior = copy.deepcopy(q["metric_judgment"])
    q["metric_judgment"]["prompt_version"] = "rag-metric-judge-v1"
    replacement = copy.deepcopy(prior)
    replacement["input_tokens"] = 100
    calls = []
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", lambda *a, **k: calls.append(k) or replacement)
    result = {"suppliers": [s], "summary": {}}
    original_answer = q["answer"]
    judge_report(result, "http://api", {})
    assert len(calls) == 1 and q["answer"] == original_answer
    assert q["metric_judgment_history"][0]["prompt_version"] == "rag-metric-judge-v1"
    assert result["summary"]["evidence_metrics"]["judging"]["input_tokens"] == 150
    judge_report(result, "http://api", {})
    assert len(calls) == 1 and len(q["metric_judgment_history"]) == 1
    assert "1/1 completed; 0 pending/failed" in capsys.readouterr().out


def test_structured_api_failure_survives_in_saved_report(monkeypatch, capsys):
    s, q = fixture(); q["run_id"] = "saved-run"; q.pop("metric_judgment")
    failed = {"status": "error", "reason": "Invalid quotes", "input_tokens": 300, "output_tokens": 60,
              "attempts": [{"status": "rejected", "usage_recorded": True}], "prompt_version": JUDGE_PROMPT_VERSION}
    def fail(*a, **k):
        raise EvaluationRequestError("HTTP 422", {"metric_judgment": failed})
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", fail)
    result = {"suppliers": [s], "summary": {}}
    judge_report(result, "http://api", {})
    assert q["metric_judgment"] == failed
    summary = result["summary"]["evidence_metrics"]
    assert summary["faithfulness"]["value"] is None
    assert summary["judging"]["input_tokens"] == 300 and summary["judging"]["rejected_attempts"] == 1
    assert "0/1 completed; 1 pending/failed" in capsys.readouterr().out


def test_human_judgments_are_not_replaced_by_prompt_version_upgrade(monkeypatch):
    s, q = fixture(); q["metric_judgment"]["method"] = "human_review"
    q["metric_judgment"]["prompt_version"] = "human-calibration"
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", lambda *a, **k: pytest.fail("Human judgment must be retained"))
    judge_report({"suppliers": [s], "summary": {}}, "http://api", {})


def test_old_backend_cannot_silently_complete_a_new_protocol_run(monkeypatch):
    s, q = fixture(); q["run_id"] = "saved-run"
    old = copy.deepcopy(q["metric_judgment"]); old["prompt_version"] = "rag-metric-judge-v1"
    q.pop("metric_judgment")
    monkeypatch.setattr("scripts.run_quality_evaluation.request_json", lambda *a, **k: old)
    result = {"suppliers": [s], "summary": {}}
    judge_report(result, "http://api", {})
    assert q["metric_judgment"]["status"] == "error"
    assert "Rebuild the backend" in q["metric_judgment"]["reason"]
    assert result["summary"]["evidence_metrics"]["faithfulness"]["value"] is None
    assert result["summary"]["evidence_metrics"]["judging"]["input_tokens"] == 50
