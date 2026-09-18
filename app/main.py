"""GridPilot AI FastAPI application."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from app.interpreter import InterpretationError, interpret_notes
from app.pipeline import run_pipeline
from app.schemas import HealthResponse, OptimizeEnergyRequest, OptimizeEnergyResponse

app = FastAPI(title="GridPilot AI", version="0.1.0")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send visitors at the deployment root to the interactive API docs."""
    return RedirectResponse(url="/docs")


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
        return run_pipeline(request, interpreter=interpret_notes)
    except InterpretationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to produce an energy plan") from exc
