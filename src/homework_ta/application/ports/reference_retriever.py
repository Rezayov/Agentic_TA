"""Reference retrieval boundary owned by the application layer."""

from typing import Protocol

from homework_ta.domain.models import RetrievalTrace, SourceExcerpt


class RetrievalError(RuntimeError):
    """Raised when a configured reference index cannot satisfy retrieval."""


class ReferenceRetriever(Protocol):
    def retrieve(
        self, query: str, *, limit: int
    ) -> tuple[tuple[SourceExcerpt, ...], RetrievalTrace]:
        """Return ranked excerpts plus an auditable retrieval trace."""
