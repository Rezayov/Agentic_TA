import hashlib
from pathlib import Path

from homework_ta.application.ports.reference_retriever import ReferenceRetriever
from homework_ta.application.use_cases.build_evidence_packet import (
    BuildEvidencePacket,
    _apply_character_budget,
)
from homework_ta.domain.models import GradingInput, RetrievalHit, RetrievalTrace, SourceExcerpt
from homework_ta.infrastructure.references.chunking import ReferenceDocument, chunk_document
from homework_ta.infrastructure.references.sqlite_fts import (
    SQLiteReferenceRetriever,
    build_reference_index,
)

TEXTBOOK = """# Solving linear equations

An equation remains equivalent when the same quantity is subtracted from both sides.
Both sides may also be divided by the same nonzero quantity.

# Quadratic equations

The quadratic formula can be used when factoring is inconvenient.
"""


def test_character_budget_does_not_skip_a_high_rank_passage_for_lower_ranked_ones() -> None:
    excerpts = (
        SourceExcerpt(source_id="rank-1", location="p1", content="A" * 700),
        SourceExcerpt(source_id="rank-2", location="p2", content="B" * 400),
        SourceExcerpt(source_id="rank-3", location="p3", content="C" * 300),
    )

    assert [item.source_id for item in _apply_character_budget(excerpts, 500)] == []


class _BudgetRetriever(ReferenceRetriever):
    def retrieve(self, query: str, *, limit: int):
        excerpts = (
            SourceExcerpt(source_id="rank-1", location="p1", content="A" * 700),
            SourceExcerpt(source_id="rank-2", location="p2", content="B" * 400),
        )
        trace = RetrievalTrace(
            query=query,
            index_sha256="0" * 64,
            hits=tuple(
                RetrievalHit(
                    source_id=item.source_id,
                    location=item.location,
                    rank=index,
                    content_sha256=hashlib.sha256(item.content.encode()).hexdigest(),
                )
                for index, item in enumerate(excerpts, start=1)
            ),
        )
        return excerpts[:limit], trace


def test_evidence_packet_keeps_retrieval_order_under_character_budget(tmp_path) -> None:
    grading_input = GradingInput.model_validate_json(
        Path("tests/fixtures/example_input.json").read_text(encoding="utf-8")
    )

    packet = BuildEvidencePacket(
        _BudgetRetriever(), max_retrieved_characters=1_000
    ).execute(grading_input)

    assert [hit.source_id for hit in packet.retrieval.hits] == ["rank-1"]


def test_heading_aware_chunks_have_stable_traceable_identifiers() -> None:
    document = ReferenceDocument(
        source_name="algebra-book",
        display_name="algebra.md",
        content=TEXTBOOK,
    )

    first = chunk_document(document)
    second = chunk_document(document)

    assert first == second
    assert len(first) == 2
    assert "Solving linear equations" in first[0].location
    assert first[0].content.startswith("Solving linear equations\n\n")
    assert first[0].source_id.startswith("textbook:")


def test_sqlite_retrieval_builds_a_bounded_shared_packet(tmp_path) -> None:
    database = tmp_path / "references.sqlite3"
    fingerprint = build_reference_index(
        database,
        (
            ReferenceDocument(
                source_name="algebra-book",
                display_name="algebra.md",
                content=TEXTBOOK,
            ),
        ),
    )
    grading_input = GradingInput.model_validate_json(
        Path("tests/fixtures/example_input.json").read_text(encoding="utf-8")
    )

    packet = BuildEvidencePacket(SQLiteReferenceRetriever(database), max_results=3).execute(
        grading_input
    )

    assert packet.retrieval.index_sha256 == fingerprint
    assert packet.retrieval.hits[0].rank == 1
    assert "Solving linear equations" in packet.retrieval.hits[0].location
    assert "Subtracting 3 from both sides" not in packet.retrieval.query
    retrieved_ids = {hit.source_id for hit in packet.retrieval.hits}
    assert retrieved_ids <= {source.source_id for source in packet.grading_input.source_material}
