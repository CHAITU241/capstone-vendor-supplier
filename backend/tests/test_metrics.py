from fastapi.testclient import TestClient

from app.main import app
from app.metrics import observe_ai_call


def test_metrics_endpoint_exposes_vendorlens_metrics() -> None:
    client = TestClient(app)
    with observe_ai_call("test.operation", "test-model") as observation:
        observation.input_tokens = 3
        observation.output_tokens = 2

    client.get("/")
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "vendorlens_ai_calls_total" in response.text
    assert 'operation="test.operation"' in response.text
    assert "vendorlens_http_requests_total" in response.text
