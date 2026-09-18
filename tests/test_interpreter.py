"""Tests for LLM interpretation and deterministic guardrails."""

import httpx
import pytest

from app.guardrails import validate_interpretations
from app import interpreter
from app.interpreter import InterpretationError, OpenAICompatibleClient, interpret_notes
from app.schemas import BatteryConfig


class FakeClient:
    def __init__(self, response):
        self.response = response

    def generate_json(self, *, system_prompt, payload):
        return self.response


BATTERY = BatteryConfig(
    capacity_kwh=100,
    initial_energy_kwh=50,
    minimum_energy_kwh=10,
    max_charge_kwh=20,
    max_discharge_kwh=20,
)


def test_interpret_and_guardrail_valid_notes() -> None:
    notes = ["Solar remains at 20% from 1 PM to 3 PM.", "The menu changes."]
    output = {"directive_interpretation": [
        {"note_index": 0, "applies": True, "directive_type": "solar_reduction",
         "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
         "explanation": "Solar is reduced."},
        {"note_index": 1, "applies": False, "directive_type": "no_op",
         "structured_adjustment": None, "explanation": "Not energy-related."},
    ]}
    result = interpret_notes(notes, BATTERY, FakeClient(output))
    assert validate_interpretations(notes, result, BATTERY) == result
    assert result[0].structured_adjustment.factor == 0.2


def test_malformed_model_output_is_controlled() -> None:
    with pytest.raises(InterpretationError, match="invalid structured output"):
        interpret_notes(["note"], BATTERY, FakeClient({"wrong": []}))


def test_guardrails_reject_missing_note_mapping() -> None:
    with pytest.raises(ValueError, match="note_index order"):
        validate_interpretations(["note"], [], BATTERY)


@pytest.mark.parametrize(
    ("note", "directive_type", "adjustment"),
    [
        ("Panel washing from one until three leaves one-fifth output.", "solar_reduction", {"hours": [13, 14], "factor": 0.2}),
        ("Hold 35 kWh from six through nine tonight.", "minimum_battery_reserve", {"hours": [18, 19, 20], "minimum_energy_kwh": 35}),
        ("Battery intake is unavailable 2-4 PM.", "no_charge_window", {"hours": [14, 15]}),
        ("Do not draw from storage between 7 and 9 PM.", "no_discharge_window", {"hours": [19, 20]}),
        ("Grid draw cannot exceed 45 kWh from 5-7 PM.", "max_grid_window", {"hours": [17, 18], "max_grid_kwh": 45}),
        ("The cafeteria menu changes tomorrow.", "no_op", None),
    ],
)
def test_paraphrased_directive_contract(note, directive_type, adjustment) -> None:
    applies = directive_type != "no_op"
    output = {"directive_interpretation": [{
        "note_index": 0, "applies": applies, "directive_type": directive_type,
        "structured_adjustment": adjustment, "explanation": "Test interpretation.",
    }]}
    result = interpret_notes([note], BATTERY, FakeClient(output))
    assert validate_interpretations([note], result, BATTERY) == result


def test_provider_retries_retryable_status(monkeypatch) -> None:
    monkeypatch.setattr(interpreter.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(interpreter.settings, "llm_model", "test-model")
    monkeypatch.setattr(interpreter.settings, "llm_max_attempts", 2)
    monkeypatch.setattr(interpreter.settings, "llm_retry_base_seconds", 0)
    calls = []

    def fake_post(*args, **kwargs):
        request = httpx.Request("POST", args[0])
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, request=request, json={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"directive_interpretation": []}'}}]
        })

    monkeypatch.setattr(interpreter.httpx, "post", fake_post)
    result = OpenAICompatibleClient().generate_json(system_prompt="JSON", payload={})
    assert result == {"directive_interpretation": []}
    assert len(calls) == 2
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert "temperature" not in calls[0]


def test_provider_does_not_retry_auth_failure(monkeypatch) -> None:
    monkeypatch.setattr(interpreter.settings, "llm_api_key", "secret-never-expose")
    monkeypatch.setattr(interpreter.settings, "llm_model", "test-model")
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(401, request=httpx.Request("POST", args[0]))

    monkeypatch.setattr(interpreter.httpx, "post", fake_post)
    with pytest.raises(InterpretationError, match="temporarily unavailable") as error:
        OpenAICompatibleClient().generate_json(system_prompt="JSON", payload={})
    assert calls == 1
    assert "secret-never-expose" not in str(error.value)
