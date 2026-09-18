"""LLM-backed conversion of operator notes into structured directives."""

from __future__ import annotations

import json
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


class OpenAICompatibleClient:
    def generate_json(self, *, system_prompt: str, payload: dict[str, Any]) -> Any:
        if not settings.llm_api_key or not settings.llm_model:
            raise InterpretationError("LLM_API_KEY and LLM_MODEL must be configured")
        try:
            response = httpx.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload)},
                    ],
                },
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise InterpretationError("Language-model interpretation failed") from exc


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
