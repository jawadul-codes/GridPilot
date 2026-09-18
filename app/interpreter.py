"""LLM-backed conversion of operator notes into structured directives."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx

from app.config import settings
from app.schemas import BatteryConfig, DirectiveInterpretation


class InterpretationError(RuntimeError):
    """Controlled LLM/provider or structured-output failure."""


class LLMClient(Protocol):
    def generate_json(self, *, system_prompt: str, payload: dict[str, Any]) -> Any: ...


SYSTEM_PROMPT = """Interpret synthetic smart-campus operator notes as JSON.
Return exactly one directive_interpretation entry per note in zero-based note_index order.
Allowed types and adjustment shapes:
solar_reduction={"hours":[...],"factor":number}; factor is usable solar remaining.
minimum_battery_reserve={"hours":[...],"minimum_energy_kwh":number}.
no_charge_window={"hours":[...]}; no_discharge_window={"hours":[...]}.
max_grid_window={"hours":[...],"max_grid_kwh":number}; no_op=null.
Only no_op uses applies=false; all other types use applies=true.
Whole-hour windows are start-inclusive/end-exclusive: 1 PM to 3 PM is [13,14].
Hours must be unique sorted integers 0..23. Do not invent values or unsupported rules.
Each entry must contain note_index, applies, directive_type, structured_adjustment, explanation.
"""


INTERPRETATION_SCHEMA = {
    "name": "gridpilot_directive_interpretation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "directive_interpretation": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "note_index": {"type": "integer", "minimum": 0, "maximum": 2},
                        "applies": {"type": "boolean"},
                        "directive_type": {
                            "type": "string",
                            "enum": [
                                "solar_reduction", "minimum_battery_reserve",
                                "no_charge_window", "no_discharge_window",
                                "max_grid_window", "no_op",
                            ],
                        },
                        "structured_adjustment": {
                            "anyOf": [
                                {"type": "object", "properties": {"hours": {"type": "array", "items": {"type": "integer"}}, "factor": {"type": "number"}}, "required": ["hours", "factor"], "additionalProperties": False},
                                {"type": "object", "properties": {"hours": {"type": "array", "items": {"type": "integer"}}, "minimum_energy_kwh": {"type": "number"}}, "required": ["hours", "minimum_energy_kwh"], "additionalProperties": False},
                                {"type": "object", "properties": {"hours": {"type": "array", "items": {"type": "integer"}}}, "required": ["hours"], "additionalProperties": False},
                                {"type": "object", "properties": {"hours": {"type": "array", "items": {"type": "integer"}}, "max_grid_kwh": {"type": "number"}}, "required": ["hours", "max_grid_kwh"], "additionalProperties": False},
                                {"type": "null"},
                            ]
                        },
                        "explanation": {"type": "string", "minLength": 1},
                    },
                    "required": ["note_index", "applies", "directive_type", "structured_adjustment", "explanation"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["directive_interpretation"],
        "additionalProperties": False,
    },
}


class OpenAICompatibleClient:
    def generate_json(self, *, system_prompt: str, payload: dict[str, Any]) -> Any:
        if not settings.llm_api_key or not settings.llm_model:
            raise InterpretationError("LLM_API_KEY and LLM_MODEL must be configured")
        url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
        body = {
            "model": settings.llm_model,
            "response_format": {"type": "json_schema", "json_schema": INTERPRETATION_SCHEMA},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
        }
        last_error: Exception | None = None
        attempts = max(1, settings.llm_max_attempts)
        for attempt in range(attempts):
            try:
                response = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json=body,
                    timeout=settings.request_timeout_seconds,
                )
                if response.status_code in {408, 409, 429} or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable model-provider response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                choice = response.json()["choices"][0]
                message = choice["message"]
                if message.get("refusal"):
                    raise InterpretationError("Language model refused to interpret the notes")
                if choice.get("finish_reason") != "stop":
                    raise InterpretationError("Language model returned an incomplete interpretation")
                return json.loads(message["content"])
            except InterpretationError:
                raise
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status not in {408, 409, 429} and status < 500:
                    break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise InterpretationError("Language model returned malformed JSON") from exc

            if attempt + 1 < attempts:
                time.sleep(settings.llm_retry_base_seconds * (2**attempt))

        raise InterpretationError("Language-model provider is temporarily unavailable") from last_error


def interpret_notes(
    notes: list[str],
    battery: BatteryConfig,
    client: LLMClient | None = None,
) -> list[DirectiveInterpretation]:
    """Interpret notes using an LLM and parse its untrusted structured output."""
    provider = client or OpenAICompatibleClient()
    try:
        raw = provider.generate_json(
            system_prompt=SYSTEM_PROMPT,
            payload={"operator_notes": notes, "battery": battery.model_dump()},
        )
        entries = raw["directive_interpretation"]
        if not isinstance(entries, list):
            raise TypeError("directive_interpretation must be an array")
        return [DirectiveInterpretation.model_validate(entry) for entry in entries]
    except InterpretationError:
        raise
    except Exception as exc:
        raise InterpretationError("Language model returned invalid structured output") from exc
