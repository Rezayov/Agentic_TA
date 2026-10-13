from pathlib import Path

from homework_ta.application.use_cases.build_evidence_packet import BuildEvidencePacket
from homework_ta.domain.models import GradingInput
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
