"""GridPilot AI FastAPI application."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.guardrails import validate_interpretations
from app.interpreter import InterpretationError, interpret_notes
from app.optimizer import build_schedule, schedule_totals
from app.schemas import HealthResponse, OptimizeEnergyRequest, OptimizeEnergyResponse
from app.validator import validate_schedule

app = FastAPI(title="GridPilot AI", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Use the challenge-required 400 for malformed/structurally invalid JSON."""
    del request
    errors = []
    for error in exc.errors():
        errors.append({
            "type": error.get("type"),
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "Invalid request"),
        })
    return JSONResponse(status_code=400, content={"detail": errors})


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(request: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
    """Interpret notes, optimize the schedule, replay it, and return totals."""
    try:
        interpretations = interpret_notes(request.operator_notes, request.battery)
        interpretations = validate_interpretations(
            request.operator_notes, interpretations, request.battery
        )
        plan = build_schedule(request, interpretations)
        validate_schedule(request, interpretations, plan)
        total_grid, total_cost, peak_grid = schedule_totals(request, plan)
        return OptimizeEnergyResponse(
            scenario_id=request.scenario_id,
            interpretations=interpretations,
            hourly_plan=plan,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
            summary="Generated a validated minimum-cost 24-hour energy schedule.",
        )
    except InterpretationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to produce an energy plan") from exc
