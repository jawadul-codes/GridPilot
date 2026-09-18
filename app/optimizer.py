"""Linear-programming model for the 24-hour energy schedule."""

from app.schemas import DirectiveInterpretation, HourlyPlan, OptimizeEnergyRequest


def build_schedule(
    request: OptimizeEnergyRequest,
    interpretations: list[DirectiveInterpretation],
) -> list[HourlyPlan]:
    """Return a minimum-cost feasible schedule."""
    del request, interpretations
    raise NotImplementedError
