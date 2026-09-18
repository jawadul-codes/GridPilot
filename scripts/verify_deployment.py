"""Verify a running GridPilot deployment through its public HTTP contract."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.schemas import DirectiveInterpretation, OptimizeEnergyRequest, OptimizeEnergyResponse
from app.validator import validate_schedule


def semantic_directive(item: DirectiveInterpretation) -> dict:
    return {
        "note_index": item.note_index,
        "applies": item.applies,
        "directive_type": item.directive_type.value,
        "structured_adjustment": (
            item.structured_adjustment.model_dump() if item.structured_adjustment else None
        ),
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def verify(base_url: str, sample_path: Path, rounds: int, timeout: float) -> int:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an absolute http:// or https:// URL")
    if rounds < 1:
        raise ValueError("rounds must be at least 1")

    pack = json.loads(sample_path.read_text(encoding="utf-8"))
    cases = pack["cases"]
    health_url = f"{base_url.rstrip('/')}/health"
    optimize_url = f"{base_url.rstrip('/')}/optimize-energy"
    latencies: list[float] = []
    failures: list[str] = []

    with httpx.Client(timeout=timeout) as client:
        started = time.perf_counter()
        health = client.get(health_url)
        health_latency = time.perf_counter() - started
        if health.status_code != 200 or health.json() != {"status": "ok"}:
            raise RuntimeError(
                f"health check failed: HTTP {health.status_code} {health.text[:200]}"
            )
        print(f"health: pass ({health_latency:.3f}s)")

        for round_number in range(1, rounds + 1):
            for case in cases:
                case_id = case["id"]
                request = OptimizeEnergyRequest.model_validate(case["input"])
                expected = [
                    DirectiveInterpretation.model_validate(item)
                    for item in case["expected_output"]["directive_interpretation"]
                ]
                started = time.perf_counter()
                try:
                    response = client.post(optimize_url, json=case["input"])
                    elapsed = time.perf_counter() - started
                    latencies.append(elapsed)
                    if response.status_code != 200:
                        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
                    result = OptimizeEnergyResponse.model_validate(response.json())
                    if result.scenario_id != request.scenario_id:
                        raise ValueError("scenario_id was not echoed")
                    if [semantic_directive(x) for x in result.interpretations] != [
                        semantic_directive(x) for x in expected
                    ]:
                        raise ValueError("directive interpretation differs from public ground truth")
                    validate_schedule(request, result.interpretations, result.hourly_plan)
                    total_grid = sum(item.grid_kwh for item in result.hourly_plan)
                    total_cost = sum(
                        item.grid_kwh * source.tariff_bdt_per_kwh
                        for item, source in zip(
                            result.hourly_plan, request.hourly_data, strict=True
                        )
                    )
                    peak_grid = max(item.grid_kwh for item in result.hourly_plan)
                    checks = [
                        (result.total_grid_kwh, total_grid, "total_grid_kwh"),
                        (result.total_cost_bdt, total_cost, "total_cost_bdt"),
                        (result.peak_grid_kwh, peak_grid, "peak_grid_kwh"),
                    ]
                    for reported, recalculated, name in checks:
                        if abs(reported - recalculated) > 0.01:
                            raise ValueError(f"{name} disagrees with hourly_plan")
                    print(f"round={round_number} case={case_id} pass {elapsed:.3f}s")
                except Exception as exc:
                    failures.append(f"round={round_number} case={case_id}: {exc}")
                    print(f"round={round_number} case={case_id} FAIL")

    total_requests = rounds * len(cases)
    failure_rate = len(failures) / total_requests if total_requests else 0
    print("\nDeployment metrics")
    print(f"requests: {total_requests}")
    print(f"failures: {len(failures)} ({failure_rate:.1%})")
    print(f"latency average: {statistics.fmean(latencies):.3f}s" if latencies else "latency average: n/a")
    print(f"latency p50: {percentile(latencies, 0.50):.3f}s")
    print(f"latency p95: {percentile(latencies, 0.95):.3f}s")
    print(f"latency max: {max(latencies):.3f}s" if latencies else "latency max: n/a")
    if failures:
        print("\nFailures")
        for failure in failures:
            print(f"- {failure}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("sample_path", type=Path)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    return verify(args.base_url, args.sample_path, args.rounds, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
