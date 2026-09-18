"""Independent deterministic replay validation of optimized schedules."""

from app.schemas import DirectiveInterpretation, HourlyPlan, OptimizeEnergyRequest


def validate_schedule(
    request: OptimizeEnergyRequest,
    interpretations: list[DirectiveInterpretation],
    plan: list[HourlyPlan],
    tolerance: float = 0.01,
) -> None:
    """Raise an error when the schedule violates any invariant."""
    del request, interpretations, plan, tolerance
    raise NotImplementedError
