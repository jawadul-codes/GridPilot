# GridPilot AI

LLM-assisted smart-campus energy optimizer for the BUP CSE Fest 2026 preliminary.
It converts operator notes into validated directives and generates a minimum-cost,
constraint-safe 24-hour grid, solar, and battery schedule.

## Architecture

```text
POST /optimize-energy
  -> strict request validation
  -> LLM structured directive interpretation
  -> deterministic interpretation guardrails
  -> PuLP/CBC optimization
  -> independent schedule replay validation
  -> canonical JSON response
```

`app/pipeline.py` is the explicit integration boundary between interpretation and
optimization. It guarantees that model output is guardrailed before optimization
and that the optimized schedule is replayed before serialization.

The LLM only interprets language. Deterministic code validates its output before
the optimizer uses it. The returned schedule is replayed independently before it
is returned.

## Requirements

- Python 3.12+
- An OpenAI-compatible model endpoint supporting Chat Completions structured output
- `LLM_API_KEY` and `LLM_MODEL`

## Local quickstart

```powershell
git clone <repository-url>
cd GridPilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

```env
LLM_API_KEY=your-api-key
LLM_MODEL=your-model-id
LLM_BASE_URL=https://api.openai.com/v1
REQUEST_TIMEOUT_SECONDS=8
LLM_MAX_ATTEMPTS=2
LLM_RETRY_BASE_SECONDS=0.25
```

Never commit `.env`; it is ignored by Git.

Start the service:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The service should become ready within 60 seconds.

## API

### Health

```powershell
curl.exe http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

### Optimize energy

The request requires one to three operator notes, exactly 24 ordered hourly entries,
and the battery configuration defined by the challenge.

```powershell
curl.exe -X POST http://localhost:8000/optimize-energy `
  -H "Content-Type: application/json" `
  --data-binary "@examples/sample_request.json"
```

The response contains `scenario_id`, `directive_interpretation`, 24 `hourly_plan`
entries, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, and `plan_summary`.

## Tests

```powershell
pytest -q
```

The suite covers schemas, every directive shape, paraphrase contracts, malformed
model output, provider retries, secret-safe errors, the optimizer, replay validation,
the complete API pipeline, and health latency. Provider tests use fakes and consume
no API credits.

To run a live provider smoke test, configure `.env`, start the service, and send
`examples/sample_request.json`. Do not run it repeatedly unless you intend to consume
provider quota.

The optimizer uses PuLP/CBC to minimize tariff-weighted grid cost across the
24-hour horizon. It independently replays effective solar, energy balance,
battery bounds/rates, directives, and end-of-day neutrality before returning a plan.

Validate all official public sample cases using their reference interpretations:

```powershell
python -m scripts.validate_public_cases "PATH_TO_PUBLIC_SAMPLE_CASES.json"
```

Also test the configured LLM against the official interpretation ground truth:

```powershell
python -m scripts.validate_public_cases "PATH_TO_PUBLIC_SAMPLE_CASES.json" --live
```

## Reliability behavior

- Model calls use strict JSON Schema structured output.
- HTTP 408, 409, 429, network errors, timeouts, and 5xx responses are retried once.
- Authentication and other non-retryable 4xx responses fail immediately.
- Model refusals, incomplete responses, malformed JSON, and invalid directives produce
  controlled errors without returning keys, raw provider payloads, or stack traces.
- Default model timeout is 8 seconds per attempt; the judge's total request limit is
  30 seconds.

## Docker fallback

```powershell
docker build -t gridpilot-ai:latest .
docker run --rm -p 8000:8000 --env-file .env gridpilot-ai:latest
curl.exe http://localhost:8000/health
```

The image binds to `0.0.0.0:8000` and includes a container health check. Secrets are
provided at runtime and are excluded from the build context.

### Published fallback image

The contest fallback image is published on Docker Hub:

```text
closedgates/gridplot:bup-cse-fest-2026
closedgates/gridplot@sha256:93e47fb732e5b61bcec27cdb55f798f1b2868bf196a87c9474a74fa5d7d78709
```

To publish a replacement image before submission, authenticate with Docker Hub,
then update the tag and digest after a successful push:

```powershell
docker tag gridpilot-ai:latest closedgates/gridplot:bup-cse-fest-2026
docker push closedgates/gridplot:bup-cse-fest-2026
docker inspect --format='{{index .RepoDigests 0}}' closedgates/gridplot:bup-cse-fest-2026
```

Record the resulting digest in your submission and keep that image public and
pullable throughout evaluation. Organizers can run it with:

```powershell
docker pull closedgates/gridplot@sha256:93e47fb732e5b61bcec27cdb55f798f1b2868bf196a87c9474a74fa5d7d78709
docker run --rm -p 8000:8000 --env-file .env closedgates/gridplot@sha256:93e47fb732e5b61bcec27cdb55f798f1b2868bf196a87c9474a74fa5d7d78709
```

The required runtime variables are `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`,
`REQUEST_TIMEOUT_SECONDS`, `LLM_MAX_ATTEMPTS`, and `LLM_RETRY_BASE_SECONDS`.

## Deployment

Deploy the Docker image on any public service that supports environment variables:

1. Set `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL` in the platform's secret manager.
2. Expose container port `8000`.
3. Keep the start command from the Dockerfile.
4. Verify `/health` and `/optimize-energy` from outside the development network.
5. Keep the endpoint and model quota available throughout judging.

## Known limitations

- Availability and latency depend on the configured model provider.
- The in-memory service does not persist results across restarts.
- A model that does not support Chat Completions structured output needs a compatible
  adapter or a different `LLM_BASE_URL`.
