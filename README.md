# GridPilot AI

LLM-assisted smart campus energy optimizer that interprets operator directives, validates constraints, and generates cost-efficient 24-hour grid, solar, and battery schedules.

## Development

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run the test suite with `pytest`.

The service exposes `GET /health` and a scaffolded `POST /optimize-energy` endpoint. The interpretation, optimization, and replay-validation modules are ready for implementation.
