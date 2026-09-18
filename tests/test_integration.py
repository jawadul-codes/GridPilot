"""Tests for the explicit Teammate A/Teammate B integration boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline import run_pipeline
from app.schemas import DirectiveInterpretation, OptimizeEnergyRequest


ROOT = Path(__file__).parents[1]


def sample_request() -> OptimizeEnergyRequest:
    payload = json.loads((ROOT / "examples" / "sample_request.json").read_text(encoding="utf-8"))
    return OptimizeEnergyRequest.model_validate(payload)


def integrated_directives() -> list[DirectiveInterpretation]:
    return [
        DirectiveInterpretation.model_validate({
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
            "explanation": "Solar remains at 20 percent.",
        }),
        DirectiveInterpretation.model_validate({
            "note_index": 1,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [18, 19]},
            "explanation": "Charging is prohibited.",
        }),
        DirectiveInterpretation.model_validate({
            "note_index": 2,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Not related to energy scheduling.",
        }),
    ]


def test_real_optimizer_and_replay_integrate_with_interpreter_contract() -> None:
    request = sample_request()
    response = run_pipeline(
        request,
        interpreter=lambda notes, battery: integrated_directives(),
    )

    assert response.scenario_id == request.scenario_id
    assert len(response.interpretations) == len(request.operator_notes)
    assert len(response.hourly_plan) == 24
    assert response.total_grid_kwh == pytest.approx(
        sum(item.grid_kwh for item in response.hourly_plan)
    )
    assert response.peak_grid_kwh == pytest.approx(
        max(item.grid_kwh for item in response.hourly_plan)
    )
    assert "solar_reduction" in response.summary
    assert "no_charge_window" in response.summary
    assert "ignoring 1 unrelated note" in response.summary


def test_guardrails_block_optimizer_when_note_mapping_is_invalid() -> None:
    optimizer_called = False

    def optimizer(request, interpretations):
        nonlocal optimizer_called
        optimizer_called = True
        return []

    with pytest.raises(ValueError, match="note_index order"):
        run_pipeline(
            sample_request(),
            interpreter=lambda notes, battery: integrated_directives()[:-1],
            optimizer=optimizer,
        )

    assert optimizer_called is False


def test_replay_failure_blocks_response() -> None:
    replay_called = False

    def reject_schedule(request, interpretations, plan):
        nonlocal replay_called
        replay_called = True
        raise ValueError("replay rejected schedule")

    with pytest.raises(ValueError, match="replay rejected schedule"):
        run_pipeline(
            sample_request(),
            interpreter=lambda notes, battery: integrated_directives(),
            replay_validator=reject_schedule,
        )

    assert replay_called is True
