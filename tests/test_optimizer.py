"""Independent tests for optimizer constraints and replay validation."""

import pytest

from app.optimizer import build_schedule, schedule_totals
from app.schemas import DirectiveInterpretation, OptimizeEnergyRequest
from app.validator import validate_schedule


def request() -> OptimizeEnergyRequest:
    return OptimizeEnergyRequest.model_validate({
        "scenario_id": "optimizer-test", "operator_notes": ["test"],
        "hourly_data": [{"hour": h, "demand_kwh": 10, "solar_kwh": 12 if h == 12 else 0,
                         "tariff_bdt_per_kwh": 1 if h in (0, 1, 2, 23) else 10} for h in range(24)],
        "battery": {"capacity_kwh": 20, "initial_energy_kwh": 10, "minimum_energy_kwh": 2,
                    "max_charge_kwh": 5, "max_discharge_kwh": 5},
    })


def directive(kind: str, adjustment: dict | None) -> DirectiveInterpretation:
    return DirectiveInterpretation.model_validate({"note_index": 0, "applies": kind != "no_op", "directive_type": kind,
        "structured_adjustment": adjustment, "explanation": "test directive"})


@pytest.mark.parametrize(("kind", "adjustment"), [
    ("solar_reduction", {"hours": [12], "factor": 0.2}),
    ("minimum_battery_reserve", {"hours": [18, 19], "minimum_energy_kwh": 10}),
    ("no_charge_window", {"hours": [0, 1]}),
    ("no_discharge_window", {"hours": [18, 19]}),
    ("max_grid_window", {"hours": [18], "max_grid_kwh": 10}),
    ("no_op", None),
])
def test_every_directive_produces_replayable_schedule(kind: str, adjustment: dict | None) -> None:
    scenario = request()
    directives = [directive(kind, adjustment)]
    plan = build_schedule(scenario, directives)
    validate_schedule(scenario, directives, plan)
    assert len(plan) == 24


def test_optimizer_shifts_energy_to_expensive_hours() -> None:
    scenario = request()
    plan = build_schedule(scenario, [])
    validate_schedule(scenario, [], plan)
    assert sum(plan[h].grid_kwh for h in (0, 1, 2, 23)) > 40
    assert any(item.battery_action.value == "discharge" for item in plan if item.hour not in (0, 1, 2, 23))
    assert schedule_totals(scenario, plan)[1] >= 0


def test_replay_rejects_invalid_energy_balance() -> None:
    scenario = request()
    plan = build_schedule(scenario, [])
    plan[0] = plan[0].model_copy(update={"grid_kwh": plan[0].grid_kwh + 1})
    with pytest.raises(ValueError, match="energy balance"):
        validate_schedule(scenario, [], plan)


def test_multiple_directives_compose() -> None:
    scenario = request()
    directives = [directive("solar_reduction", {"hours": [12], "factor": 0.5}),
                  directive("no_charge_window", {"hours": [0, 1]}),
                  directive("minimum_battery_reserve", {"hours": [18], "minimum_energy_kwh": 8})]
    plan = build_schedule(scenario, directives)
    validate_schedule(scenario, directives, plan)


def test_overlapping_solar_reductions_multiply_and_grid_caps_hold() -> None:
    scenario = request()
    directives = [
        directive("solar_reduction", {"hours": [12], "factor": 0.5}),
        directive("solar_reduction", {"hours": [12], "factor": 0.5}),
        directive("max_grid_window", {"hours": [12], "max_grid_kwh": 7}),
    ]
    plan = build_schedule(scenario, directives)
    validate_schedule(scenario, directives, plan)
    assert plan[12].solar_used_kwh <= 3.0 + 0.01
    assert plan[12].grid_kwh <= 7.0 + 0.01


def test_totals_match_plan_within_contest_precision() -> None:
    scenario = request()
    plan = build_schedule(scenario, [])
    total_grid, total_cost, peak = schedule_totals(scenario, plan)
    assert total_grid == pytest.approx(sum(item.grid_kwh for item in plan), abs=0.01)
    assert total_cost == pytest.approx(sum(item.grid_kwh * scenario.hourly_data[item.hour].tariff_bdt_per_kwh for item in plan), abs=0.01)
    assert peak == pytest.approx(max(item.grid_kwh for item in plan), abs=0.01)
