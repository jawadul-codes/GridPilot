"""Tests for LLM interpretation and deterministic guardrails."""

import pytest

from app.guardrails import validate_interpretations
from app.interpreter import InterpretationError, interpret_notes
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
