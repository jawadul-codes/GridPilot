"""Deterministic validation for LLM-produced directives."""

from app.schemas import BatteryConfig, DirectiveInterpretation


def validate_interpretations(
    notes: list[str],
    interpretations: list[DirectiveInterpretation],
    battery: BatteryConfig,
) -> list[DirectiveInterpretation]:
    """Validate and normalize interpretations before optimization."""
    expected = list(range(len(notes)))
    actual = [item.note_index for item in interpretations]
    if actual != expected:
        raise ValueError("interpretations must appear exactly once in note_index order")

    for item in interpretations:
        adjustment = item.structured_adjustment
        if adjustment is None:
            continue
        hours = adjustment.hours
        if hours != sorted(set(hours)) or any(hour < 0 or hour > 23 for hour in hours):
            raise ValueError(f"note {item.note_index}: hours must be unique sorted integers 0..23")
        if item.directive_type.value == "minimum_battery_reserve":
            if adjustment.minimum_energy_kwh > battery.capacity_kwh:  # type: ignore[attr-defined]
                raise ValueError(f"note {item.note_index}: reserve exceeds battery capacity")
    return interpretations
