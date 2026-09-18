"""Contract tests for the agreed integration examples."""

import json
from pathlib import Path

from app.schemas import OptimizeEnergyRequest, OptimizeEnergyResponse


EXAMPLES = Path(__file__).parents[1] / "examples"


def test_agreed_sample_request_matches_schema() -> None:
    payload = json.loads((EXAMPLES / "sample_request.json").read_text(encoding="utf-8"))
    request = OptimizeEnergyRequest.model_validate(payload)
    assert request.scenario_id == "campus-demo-001"
    assert len(request.hourly_data) == 24


def test_agreed_sample_response_matches_schema() -> None:
    payload = json.loads((EXAMPLES / "sample_response.json").read_text(encoding="utf-8"))
    response = OptimizeEnergyResponse.model_validate(payload)
    assert len(response.interpretations) == 3
    assert len(response.hourly_plan) == 24
