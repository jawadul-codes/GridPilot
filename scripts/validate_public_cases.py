"""Validate the official public sample pack against the complete GridPilot pipeline.

Reference mode validates all input/output schemas and feeds official ground-truth
directives into the optimizer. Live mode additionally calls the configured LLM and
compares its machine-checkable semantics with the official interpretations.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from app.guardrails import validate_interpretations
from app.interpreter import interpret_notes
from app.optimizer import build_schedule, schedule_totals
from app.schemas import DirectiveInterpretation, OptimizeEnergyRequest, OptimizeEnergyResponse
from app.validator import TOLERANCE, validate_schedule


def semantic_directive(item: DirectiveInterpretation) -> dict:
    """Return only fields judged against organizer interpretation ground truth."""
    return {
        "note_index": item.note_index,
        "applies": item.applies,
        "directive_type": item.directive_type.value,
        "structured_adjustment": (
            item.structured_adjustment.model_dump() if item.structured_adjustment else None
        ),
    }


def validate_pack(path: Path, live: bool = False) -> int:
    pack = json.loads(path.read_text(encoding="utf-8"))
    cases = pack.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("public sample pack must contain a non-empty cases array")
    declared_count = pack.get("_meta", {}).get("case_count")
    if declared_count != len(cases):
        raise ValueError(f"case_count says {declared_count}, but found {len(cases)} cases")

    failures = 0
    latencies: list[float] = []
    print("case       interpretation  schedule  cost_delta_bdt  latency_s")
    for case in cases:
        case_id = case["id"]
        request = OptimizeEnergyRequest.model_validate(case["input"])
        expected_response = OptimizeEnergyResponse.model_validate(case["expected_output"])
        expected = expected_response.interpretations
        interpretations = expected
        interpretation_status = "reference"

        if live:
            started = time.perf_counter()
            interpretations = interpret_notes(request.operator_notes, request.battery)
            latencies.append(time.perf_counter() - started)
            interpretations = validate_interpretations(
                request.operator_notes, interpretations, request.battery
            )
            if [semantic_directive(x) for x in interpretations] != [
                semantic_directive(x) for x in expected
            ]:
                interpretation_status = "FAIL"
                failures += 1
            else:
                interpretation_status = "pass"

        try:
            plan = build_schedule(request, interpretations)
            validate_schedule(request, interpretations, plan)
            total_grid, total_cost, peak_grid = schedule_totals(request, plan)
            values = [total_grid, total_cost, peak_grid]
            if not all(math.isfinite(value) and value >= 0 for value in values):
                raise ValueError("totals must be finite and non-negative")
            cost_delta = total_cost - expected_response.total_cost_bdt
            schedule_status = "pass" if abs(cost_delta) <= TOLERANCE else "FAIL"
            if schedule_status == "FAIL":
                failures += 1
        except Exception as exc:
            cost_delta = math.nan
            schedule_status = f"FAIL ({exc})"
            failures += 1

        latency = f"{latencies[-1]:.3f}" if live else "-"
        print(
            f"{case_id:<10} {interpretation_status:<15} {schedule_status:<9} "
            f"{cost_delta:>14.2f}  {latency}"
        )

    if live and latencies:
        ordered = sorted(latencies)
        p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
        print(f"LLM latency: average={sum(latencies)/len(latencies):.3f}s p95={ordered[p95_index]:.3f}s")
    print(f"Result: {len(cases) - failures}/{len(cases)} checks passed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Path to the official public sample JSON")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured LLM and compare interpretation semantics",
    )
    args = parser.parse_args()
    return validate_pack(args.path, live=args.live)


if __name__ == "__main__":
    raise SystemExit(main())
