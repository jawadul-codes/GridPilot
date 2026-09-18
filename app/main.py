"""GridPilot AI FastAPI application."""

from fastapi import FastAPI, HTTPException

from app.schemas import HealthResponse, OptimizeEnergyRequest, OptimizeEnergyResponse

app = FastAPI(title="GridPilot AI", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(request: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
    """Run the interpretation and optimization pipeline (to be implemented)."""
    del request
    raise HTTPException(status_code=501, detail="Optimization pipeline is not implemented yet")
