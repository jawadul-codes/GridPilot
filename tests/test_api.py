import json
import time

from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.schemas import DirectiveInterpretation


client = TestClient(app)


def test_root_redirects_to_docs() -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_optimize_energy_full_pipeline(monkeypatch) -> None:
    request = json.loads(open("examples/sample_request.json", encoding="utf-8").read())
    directives = [
        DirectiveInterpretation.model_validate({
            "note_index": 0, "applies": True, "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
            "explanation": "Solar remains at 20 percent.",
        }),
        DirectiveInterpretation.model_validate({
            "note_index": 1, "applies": True, "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [18, 19]},
            "explanation": "Charging is prohibited.",
        }),
        DirectiveInterpretation.model_validate({
            "note_index": 2, "applies": False, "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Not related to energy scheduling.",
        }),
    ]
    monkeypatch.setattr(main, "interpret_notes", lambda notes, battery: directives)
    response = client.post("/optimize-energy", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scenario_id"] == request["scenario_id"]
    assert len(body["directive_interpretation"]) == 3
    assert len(body["hourly_plan"]) == 24
    assert "plan_summary" in body
    assert "interpretations" not in body
    assert "summary" not in body


def test_health_latency_is_small() -> None:
    samples = []
    for _ in range(20):
        started = time.perf_counter()
        response = client.get("/health")
        samples.append(time.perf_counter() - started)
        assert response.status_code == 200
    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < 0.25


def test_model_failure_does_not_expose_secret(monkeypatch) -> None:
    request = json.loads(open("examples/sample_request.json", encoding="utf-8").read())

    def fail(notes, battery):
        from app.interpreter import InterpretationError
        raise InterpretationError("Language-model provider is temporarily unavailable")

    monkeypatch.setattr(main, "interpret_notes", fail)
    response = client.post("/optimize-energy", json=request)
    assert response.status_code == 422
    assert response.json() == {"detail": "Language-model provider is temporarily unavailable"}


def test_malformed_json_returns_400() -> None:
    response = client.post(
        "/optimize-energy",
        content=b'{"scenario_id":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "detail" in response.json()


def test_structurally_invalid_request_returns_400() -> None:
    response = client.post("/optimize-energy", json={"scenario_id": "missing-fields"})
    assert response.status_code == 400
    assert "detail" in response.json()
