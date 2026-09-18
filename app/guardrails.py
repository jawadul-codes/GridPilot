"""Deterministic validation for LLM-produced directives."""

from app.schemas import BatteryConfig, DirectiveInterpretation


def validate_interpretations(
    notes: list[str],
    interpretations: list[DirectiveInterpretation],
    battery: BatteryConfig,
) -> list[DirectiveInterpretation]:
    """Validate and normalize interpretations before optimization."""
    del notes, interpretations, battery
    raise NotImplementedError
