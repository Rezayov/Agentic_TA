"""Build one immutable evidence packet shared by both assessors."""

import hashlib
from dataclasses import dataclass

from homework_ta.application.ports.reference_retriever import (
    ReferenceRetriever,
    RetrievalError,
)
from homework_ta.domain.models import GradingInput, RetrievalTrace, SourceExcerpt


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    grading_input: GradingInput
    retrieval: RetrievalTrace


class BuildEvidencePacket:
    def __init__(
        self,
        retriever: ReferenceRetriever,
        *,
        max_results: int = 8,
        max_retrieved_characters: int = 24_000,
    ) -> None:
        if not 1 <= max_results <= 20:
            raise ValueError("max_results must be between 1 and 20")
        if not 1_000 <= max_retrieved_characters <= 100_000:
            raise ValueError("retrieval character budget must be between 1000 and 100000")
        self._retriever = retriever
        self._max_results = max_results
        self._max_retrieved_characters = max_retrieved_characters

    def execute(self, grading_input: GradingInput) -> EvidencePacket:
        query = _build_query(grading_input)
        excerpts, trace = self._retriever.retrieve(query, limit=self._max_results)
        if not excerpts:
            raise RetrievalError("the reference index returned no relevant textbook passages")
        _validate_retrieval(query, excerpts, trace)

        bounded = _apply_character_budget(excerpts, self._max_retrieved_characters)
        if not bounded:
            raise RetrievalError("retrieved passages exceeded the configured evidence budget")
        allowed_ids = {excerpt.source_id for excerpt in bounded}
        bounded_trace = RetrievalTrace(
            query=trace.query,
            index_sha256=trace.index_sha256,
            hits=tuple(hit for hit in trace.hits if hit.source_id in allowed_ids),
        )
        merged = _merge_sources(grading_input.source_material, bounded)
        enriched = GradingInput(
            submission=grading_input.submission,
            rubric=grading_input.rubric,
            source_material=merged,
        )
        return EvidencePacket(grading_input=enriched, retrieval=bounded_trace)


def _build_query(grading_input: GradingInput) -> str:
    rubric_text = "\n".join(
        f"{criterion.criterion_id}: {criterion.description}"
        for criterion in grading_input.rubric.criteria
    )
    # The student's answer is deliberately excluded to reduce retrieval manipulation and bias.
    return (
        f"Question: {grading_input.submission.question}\n"
        f"Rubric: {grading_input.rubric.title}\n{rubric_text}"
    )


def _apply_character_budget(
    excerpts: tuple[SourceExcerpt, ...], budget: int
) -> tuple[SourceExcerpt, ...]:
    selected: list[SourceExcerpt] = []
    used = 0
    for excerpt in excerpts:
        size = len(excerpt.content)
        if size > budget - used:
            continue
        selected.append(excerpt)
        used += size
    return tuple(selected)


def _validate_retrieval(
    query: str, excerpts: tuple[SourceExcerpt, ...], trace: RetrievalTrace
) -> None:
    if trace.query != query:
        raise RetrievalError("retrieval trace query does not match the requested query")
    hits_by_id = {hit.source_id: hit for hit in trace.hits}
    if len(hits_by_id) != len(trace.hits):
        raise RetrievalError("retrieval trace contains duplicate source IDs")
    if len(excerpts) != len(trace.hits):
        raise RetrievalError("retrieval excerpts and trace have different lengths")
    for excerpt in excerpts:
        hit = hits_by_id.get(excerpt.source_id)
        if hit is None or hit.location != excerpt.location:
            raise RetrievalError(f"retrieval trace mismatch for {excerpt.source_id}")
        content_hash = hashlib.sha256(excerpt.content.encode("utf-8")).hexdigest()
        if content_hash != hit.content_sha256:
            raise RetrievalError(f"retrieval content hash mismatch for {excerpt.source_id}")


def _merge_sources(
    existing: tuple[SourceExcerpt, ...], retrieved: tuple[SourceExcerpt, ...]
) -> tuple[SourceExcerpt, ...]:
    by_id = {source.source_id: source for source in existing}
    existing_ids = set(by_id)
    for source in retrieved:
        previous = by_id.get(source.source_id)
        if previous is not None and previous != source:
            raise RetrievalError(f"retrieved source ID conflicts with input: {source.source_id}")
        by_id[source.source_id] = source
    return tuple(
        (*existing, *(source for source in retrieved if source.source_id not in existing_ids))
    )
