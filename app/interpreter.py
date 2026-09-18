"""LLM-backed conversion of operator notes into structured directives."""

from app.schemas import DirectiveInterpretation


def interpret_notes(notes: list[str]) -> list[DirectiveInterpretation]:
    """Interpret notes with the configured LLM provider."""
    raise NotImplementedError("Connect the LLM provider and structured-output schema")
