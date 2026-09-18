"""Independent deterministic replay validation of optimized schedules."""

from app.optimizer import _directive_constraints
from app.schemas import BatteryAction, DirectiveInterpretation, HourlyPlan, OptimizeEnergyRequest

TOLERANCE = 0.01


def validate_schedule(request: OptimizeEnergyRequest, interpretations: list[DirectiveInterpretation], plan: list[HourlyPlan], tolerance: float = TOLERANCE) -> None:
    """Replay every hour and raise ``ValueError`` on any violated invariant."""
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    if len(plan) != 24 or [entry.hour for entry in plan] != list(range(24)):
        raise ValueError("Invalid schedule: plan must contain hours 0 through 23 exactly once, in order")
    factors, extra_reserves, no_charge, no_discharge, grid_caps = _directive_constraints(interpretations)
    previous_energy = request.battery.initial_energy_kwh
    for entry, source in zip(plan, request.hourly_data, strict=True):
        hour = entry.hour
        charge = entry.battery_kwh if entry.battery_action is BatteryAction.CHARGE else 0.0
        discharge = entry.battery_kwh if entry.battery_action is BatteryAction.DISCHARGE else 0.0
        if entry.battery_action is BatteryAction.IDLE and entry.battery_kwh > tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} has non-zero idle action")
        if charge > request.battery.max_charge_kwh + tolerance or discharge > request.battery.max_discharge_kwh + tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} exceeds battery rate limit")
        if hour in no_charge and charge > tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} violates no_charge_window")
        if hour in no_discharge and discharge > tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} violates no_discharge_window")
        if entry.solar_used_kwh > source.solar_kwh * factors[hour] + tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} exceeds effective solar")
        if hour in grid_caps and entry.grid_kwh > grid_caps[hour] + tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} violates max_grid_window")
        balance = entry.grid_kwh + entry.solar_used_kwh + discharge - source.demand_kwh - charge
        if abs(balance) > tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} violates energy balance")
        expected_energy = previous_energy + charge - discharge
        if abs(entry.battery_energy_after_kwh - expected_energy) > tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} has invalid battery state transition")
        minimum = max(request.battery.minimum_energy_kwh, extra_reserves[hour])
        if not minimum - tolerance <= entry.battery_energy_after_kwh <= request.battery.capacity_kwh + tolerance:
            raise ValueError(f"Invalid schedule: hour {hour} violates battery bounds")
        previous_energy = entry.battery_energy_after_kwh
    if abs(previous_energy - request.battery.initial_energy_kwh) > tolerance:
        raise ValueError("Invalid schedule: final battery energy does not equal initial energy")
