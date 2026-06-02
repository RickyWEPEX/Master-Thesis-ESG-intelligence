"""Duenne Kapselung des Anthropic-Claude-Clients.

Bewusst optional: Das Framework laeuft im 'deterministic'-Backend vollstaendig
ohne API. Der Client wird nur instanziiert, wenn das claude-Backend oder die
LLM-Narrative-Generierung tatsaechlich genutzt wird. Der API-Key wird aus der
Umgebungsvariable ANTHROPIC_API_KEY gelesen (QA-5.3: keine Hardcoded Credentials).
"""
from __future__ import annotations

import os


class LLMUnavailableError(RuntimeError):
    pass


class ClaudeClient:
    def __init__(self, model: str, max_tokens: int = 2000, temperature: float = 0.2) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None

    def _ensure(self):
        if self._client is not None:
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMUnavailableError(
                "ANTHROPIC_API_KEY ist nicht gesetzt. Setze die Umgebungsvariable "
                "oder nutze das deterministische Backend (extraction_backend: deterministic)."
            )
        try:
            import anthropic  # noqa: WPS433 (lazy import by design)
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailableError(
                "Paket 'anthropic' nicht installiert. 'pip install anthropic' ausfuehren."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, prompt: str) -> str:
        """Sendet einen Prompt und gibt den Text der Antwort zurueck."""
        self._ensure()
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in message.content if block.type == "text")

    @property
    def available(self) -> bool:
        try:
            self._ensure()
            return True
        except LLMUnavailableError:
            return False
