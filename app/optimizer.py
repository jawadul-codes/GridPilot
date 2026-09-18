"""Linear-programming model for the 24-hour energy schedule."""

from __future__ import annotations

from collections import defaultdict

import pulp

from app.schemas import BatteryAction, DirectiveInterpretation, DirectiveType, HourlyPlan, OptimizeEnergyRequest

EPSILON = 1e-7


def _directive_constraints(interpretations: list[DirectiveInterpretation]) -> tuple[dict[int, float], dict[int, float], set[int], set[int], dict[int, float]]:
    """Compile validated directives into per-hour solver inputs."""
    solar_factor: dict[int, float] = defaultdict(lambda: 1.0)
    reserve: dict[int, float] = defaultdict(float)
    no_charge: set[int] = set()
    no_discharge: set[int] = set()
    grid_cap: dict[int, float] = {}
    for directive in interpretations:
        if not directive.applies:
            continue
        adjustment = directive.structured_adjustment
        if adjustment is None:
            continue
        if directive.directive_type is DirectiveType.SOLAR_REDUCTION:
            for hour in adjustment.hours:
                solar_factor[hour] *= adjustment.factor  # type: ignore[attr-defined]
        elif directive.directive_type is DirectiveType.MINIMUM_BATTERY_RESERVE:
            for hour in adjustment.hours:
                reserve[hour] = max(reserve[hour], adjustment.minimum_energy_kwh)  # type: ignore[attr-defined]
        elif directive.directive_type is DirectiveType.NO_CHARGE_WINDOW:
            no_charge.update(adjustment.hours)
        elif directive.directive_type is DirectiveType.NO_DISCHARGE_WINDOW:
            no_discharge.update(adjustment.hours)
        elif directive.directive_type is DirectiveType.MAX_GRID_WINDOW:
            for hour in adjustment.hours:
                cap = adjustment.max_grid_kwh  # type: ignore[attr-defined]
                grid_cap[hour] = min(grid_cap.get(hour, cap), cap)
    return solar_factor, reserve, no_charge, no_discharge, grid_cap


def build_schedule(request: OptimizeEnergyRequest, interpretations: list[DirectiveInterpretation]) -> list[HourlyPlan]:
    """Return a minimum-cost, directive-compliant 24-hour schedule."""
    factors, extra_reserves, no_charge, no_discharge, grid_caps = _directive_constraints(interpretations)
    hours = range(24)
    data = {entry.hour: entry for entry in request.hourly_data}
    battery = request.battery
    model = pulp.LpProblem("gridpilot_energy_schedule", pulp.LpMinimize)
    grid = pulp.LpVariable.dicts("grid", hours, lowBound=0)
    solar = pulp.LpVariable.dicts("solar_used", hours, lowBound=0)
    charge = pulp.LpVariable.dicts("battery_charge", hours, lowBound=0)
    discharge = pulp.LpVariable.dicts("battery_discharge", hours, lowBound=0)
    energy = pulp.LpVariable.dicts("battery_energy_after", hours, lowBound=0)
    charging = pulp.LpVariable.dicts("is_charging", hours, cat=pulp.LpBinary)
    peak_grid = pulp.LpVariable("peak_grid", lowBound=0)
    total_cost = pulp.lpSum(grid[h] * data[h].tariff_bdt_per_kwh for h in hours)
    model += total_cost
    for hour in hours:
        entry = data[hour]
        model += grid[hour] + solar[hour] + discharge[hour] == entry.demand_kwh + charge[hour]
        model += grid[hour] <= peak_grid
        model += solar[hour] <= entry.solar_kwh * factors[hour]
        model += energy[hour] >= max(battery.minimum_energy_kwh, extra_reserves[hour])
        model += energy[hour] <= battery.capacity_kwh
        model += charge[hour] <= battery.max_charge_kwh * charging[hour]
        model += discharge[hour] <= battery.max_discharge_kwh * (1 - charging[hour])
        model += energy[hour] == (battery.initial_energy_kwh if hour == 0 else energy[hour - 1]) + charge[hour] - discharge[hour]
        if hour in no_charge:
            model += charge[hour] == 0
        if hour in no_discharge:
            model += discharge[hour] == 0
        if hour in grid_caps:
            model += grid[hour] <= grid_caps[hour]
    model += energy[23] == battery.initial_energy_kwh
    status = model.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise ValueError(f"No feasible optimal schedule: {pulp.LpStatus[status]}")

    # The contest's primary objective is cost. When several schedules have the
    # same optimum cost, choose the one with the smallest peak grid draw. This
    # makes outputs deterministic and aligns with the supplied public plans.
    optimal_cost = float(pulp.value(total_cost))
    model += total_cost <= optimal_cost + EPSILON
    model.setObjective(peak_grid)
    status = model.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise ValueError(f"No feasible peak-minimized schedule: {pulp.LpStatus[status]}")

    def value(variable: pulp.LpVariable) -> float:
        result = float(pulp.value(variable))
        return 0.0 if abs(result) < EPSILON else round(result, 8)

    plan: list[HourlyPlan] = []
    for hour in hours:
        charged, discharged = value(charge[hour]), value(discharge[hour])
        if charged > EPSILON and discharged > EPSILON:
            raise ValueError("Solver returned simultaneous charge and discharge")
        action, amount = (BatteryAction.CHARGE, charged) if charged > EPSILON else ((BatteryAction.DISCHARGE, discharged) if discharged > EPSILON else (BatteryAction.IDLE, 0.0))
        plan.append(HourlyPlan(hour=hour, grid_kwh=value(grid[hour]), solar_used_kwh=value(solar[hour]), battery_action=action, battery_kwh=amount, battery_energy_after_kwh=value(energy[hour])))
    return plan


def schedule_totals(request: OptimizeEnergyRequest, plan: list[HourlyPlan]) -> tuple[float, float, float]:
    """Return total grid energy, cost, and peak grid import for a plan."""
    tariffs = {item.hour: item.tariff_bdt_per_kwh for item in request.hourly_data}
    return sum(item.grid_kwh for item in plan), sum(item.grid_kwh * tariffs[item.hour] for item in plan), max((item.grid_kwh for item in plan), default=0.0)
