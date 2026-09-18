"""Integration boundary for the complete GridPilot processing pipeline.

This module is the contract between Teammate A's interpretation/API work and
Teammate B's optimizer/replay work. Keeping orchestration here makes the order of
operations explicit and allows every stage to be tested independently.
"""

from __future__ import annotations

from collections.abc import Callable

from app.guardrails import validate_interpretations
from app.interpreter import interpret_notes
from app.optimizer import build_schedule, schedule_totals
from app.schemas import (
    BatteryConfig,
    DirectiveInterpretation,
    HourlyPlan,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.validator import validate_schedule


Interpreter = Callable[
    [list[str], BatteryConfig],
    list[DirectiveInterpretation],
]
Optimizer = Callable[
    [OptimizeEnergyRequest, list[DirectiveInterpretation]],
    list[HourlyPlan],
]
ReplayValidator = Callable[
    [OptimizeEnergyRequest, list[DirectiveInterpretation], list[HourlyPlan]],
    None,
]


def build_plan_summary(interpretations: list[DirectiveInterpretation]) -> str:
    """Create a deterministic summary without spending another LLM request."""
    applied = [
        item.directive_type.value
        for item in interpretations
        if item.applies
    ]
    ignored = sum(not item.applies for item in interpretations)
    if applied:
        directive_text = ", ".join(applied)
        summary = f"Applied {directive_text} and generated a validated minimum-cost plan"
    else:
        summary = "No operator note changed the schedule; generated a validated minimum-cost plan"
    if ignored:
        noun = "note" if ignored == 1 else "notes"
        summary += f" while ignoring {ignored} unrelated {noun}"
    return summary + "."


def run_pipeline(
    request: OptimizeEnergyRequest,
    *,
    interpreter: Interpreter = interpret_notes,
    optimizer: Optimizer = build_schedule,
    replay_validator: ReplayValidator = validate_schedule,
) -> OptimizeEnergyResponse:
    """Run interpretation, guardrails, optimization, replay, and serialization.

    The order is deliberate: untrusted model output cannot reach the optimizer
    before deterministic validation, and an optimizer result cannot reach the API
    response before independent replay validation.
    """
    interpretations = interpreter(request.operator_notes, request.battery)
    interpretations = validate_interpretations(
        request.operator_notes,
        interpretations,
        request.battery,
    )
    plan = optimizer(request, interpretations)
    replay_validator(request, interpretations, plan)
    total_grid, total_cost, peak_grid = schedule_totals(request, plan)

    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        interpretations=interpretations,
        hourly_plan=plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        summary=build_plan_summary(interpretations),
    )
