"""SQLite FTS5 reference index and retriever."""

import hashlib
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from homework_ta.application.ports.reference_retriever import RetrievalError
from homework_ta.domain.models import RetrievalHit, RetrievalTrace, SourceExcerpt
from homework_ta.infrastructure.references.chunking import (
    ReferenceChunk,
    ReferenceDocument,
    chunk_document,
)

SCHEMA_VERSION = "1"
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "question",
        "rubric",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)


def build_reference_index(
    database_path: Path,
    documents: tuple[ReferenceDocument, ...],
    *,
    chunk_characters: int = 2_400,
) -> str:
    """Build a complete index off to the side, then atomically replace the destination."""

    if not documents:
        raise ValueError("at least one reference document is required")
    source_names = [document.source_name for document in documents]
    if len(source_names) != len(set(source_names)):
        raise ValueError("reference source names must be unique")

    all_chunks = tuple(
        chunk
        for document in documents
        for chunk in chunk_document(document, max_characters=chunk_characters)
    )
    if not all_chunks:
        raise ValueError("reference documents produced no indexable chunks")
    index_sha256 = _index_hash(all_chunks)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=database_path.parent,
        prefix=f".{database_path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with sqlite3.connect(temporary_path) as connection:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE chunks_fts USING fts5("
                "source_id UNINDEXED, location UNINDEXED, content_sha256 UNINDEXED, content, "
                "tokenize='unicode61 remove_diacritics 2')"
            )
            connection.executemany(
                "INSERT INTO chunks_fts(source_id, location, content_sha256, content) "
                "VALUES (?, ?, ?, ?)",
                (
                    (chunk.source_id, chunk.location, chunk.content_sha256, chunk.content)
                    for chunk in all_chunks
                ),
            )
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (("schema_version", SCHEMA_VERSION), ("index_sha256", index_sha256)),
            )
        os.replace(temporary_path, database_path)
    except sqlite3.Error as exc:
        raise RetrievalError(f"could not build SQLite FTS5 reference index: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return index_sha256


class SQLiteReferenceRetriever:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.resolve(strict=True)
        if not self._database_path.is_file():
            raise ValueError("reference database path must be a file")

    def retrieve(
        self, query: str, *, limit: int
    ) -> tuple[tuple[SourceExcerpt, ...], RetrievalTrace]:
        if not 1 <= limit <= 20:
            raise ValueError("retrieval limit must be between 1 and 20")
        match_query = _safe_match_query(query)
        database_uri = f"file:{quote(str(self._database_path), safe='/')}?mode=ro"
        try:
            with sqlite3.connect(database_uri, uri=True) as connection:
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
                if metadata.get("schema_version") != SCHEMA_VERSION:
                    raise RetrievalError("reference index schema version is unsupported")
                rows = connection.execute(
                    "SELECT source_id, location, content_sha256, content "
                    "FROM chunks_fts WHERE chunks_fts MATCH ? "
                    "ORDER BY bm25(chunks_fts, 0.0, 0.0, 0.0, 1.0), rowid LIMIT ?",
                    (match_query, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RetrievalError(f"could not query reference index: {exc}") from exc

        if not rows:
            raise RetrievalError("the reference index returned no relevant textbook passages")

        excerpts: list[SourceExcerpt] = []
        hits: list[RetrievalHit] = []
        for rank, (source_id, location, content_hash, content) in enumerate(rows, start=1):
            actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if actual_hash != content_hash:
                raise RetrievalError(f"reference index integrity check failed for {source_id}")
            excerpts.append(SourceExcerpt(source_id=source_id, location=location, content=content))
            hits.append(
                RetrievalHit(
                    source_id=source_id,
                    location=location,
                    rank=rank,
                    content_sha256=content_hash,
                )
            )

        index_sha256 = metadata.get("index_sha256")
        if index_sha256 is None:
            raise RetrievalError("reference index fingerprint is missing")
        trace = RetrievalTrace(
            query=query,
            index_sha256=index_sha256,
            hits=tuple(hits),
        )
        return tuple(excerpts), trace


def _safe_match_query(query: str) -> str:
    words = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    terms: list[str] = []
    seen: set[str] = set()
    for word in words:
        if len(word) < 2 or word in _STOP_WORDS or word in seen:
            continue
        seen.add(word)
        terms.append(word)
        if len(terms) == 48:
            break
    if not terms:
        raise RetrievalError("grading question and rubric contain no searchable terms")
    return " OR ".join(f'"{term}"' for term in terms)


def _index_hash(chunks: tuple[ReferenceChunk, ...]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.source_id.encode())
        digest.update(b"\0")
        digest.update(chunk.content_sha256.encode())
        digest.update(b"\0")
    return digest.hexdigest()
