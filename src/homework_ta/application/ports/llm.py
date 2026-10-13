"""Language-model boundary owned by the application layer."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[ChatMessage, ...]
    response_schema: dict[str, Any]
    schema_name: str
    temperature: float = 0.0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str | None = None


class LanguageModel(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return one completion or raise a provider exception."""
