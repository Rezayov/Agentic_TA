"""Deterministic, heading-aware chunking for text-based references."""

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceDocument:
    source_name: str
    display_name: str
    content: str


@dataclass(frozen=True, slots=True)
class ReferenceChunk:
    source_id: str
    location: str
    content: str
    content_sha256: str


_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_LATEX_HEADING = re.compile(r"^\\(?:chapter|section|subsection|subsubsection)\*?\{(.+?)\}\s*$")


def chunk_document(
    document: ReferenceDocument, *, max_characters: int = 2_400
) -> tuple[ReferenceChunk, ...]:
    if not document.source_name.strip():
        raise ValueError("reference source_name cannot be empty")
    if not document.display_name.strip():
        raise ValueError("reference display_name cannot be empty")
    if not document.content.strip():
        raise ValueError(f"reference document is empty: {document.display_name}")
    if not 500 <= max_characters <= 20_000:
        raise ValueError("chunk size must be between 500 and 20000 characters")

    sections = _split_sections(document.content)
    chunks: list[ReferenceChunk] = []
    ordinal = 1
    for heading, section_text in sections:
        body_budget = max_characters - len(heading) - 2
        for body in _pack_paragraphs(section_text, body_budget):
            content = f"{heading}\n\n{body}"
            location = f"{document.display_name} | {heading} | chunk {ordinal}"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            identity = f"{document.source_name}\0{location}\0{content_hash}".encode()
            source_id = f"textbook:{hashlib.sha256(identity).hexdigest()[:24]}"
            chunks.append(
                ReferenceChunk(
                    source_id=source_id,
                    location=location,
                    content=content,
                    content_sha256=content_hash,
                )
            )
            ordinal += 1
    return tuple(chunks)


def _split_sections(content: str) -> tuple[tuple[str, str], ...]:
    heading = "Introduction"
    section_lines: list[str] = []
    sections: list[tuple[str, str]] = []

    def flush() -> None:
        text = "\n".join(section_lines).strip()
        if text:
            sections.append((heading, text))
        section_lines.clear()

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _MARKDOWN_HEADING.match(raw_line) or _LATEX_HEADING.match(raw_line)
        if match:
            flush()
            heading = " ".join(match.group(1).split())[:160]
        else:
            section_lines.append(raw_line.rstrip())
    flush()
    return tuple(sections)


def _pack_paragraphs(text: str, max_characters: int) -> tuple[str, ...]:
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in _split_oversized(paragraph, max_characters):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= max_characters:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return tuple(chunks)


def _split_oversized(text: str, max_characters: int) -> tuple[str, ...]:
    if len(text) <= max_characters:
        return (text,)
    words = text.split()
    pieces: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        added = len(word) + (1 if current else 0)
        if current and current_length + added > max_characters:
            pieces.append(" ".join(current))
            current = []
            current_length = 0
        if len(word) > max_characters:
            if current:
                pieces.append(" ".join(current))
                current = []
                current_length = 0
            pieces.extend(
                word[start : start + max_characters]
                for start in range(0, len(word), max_characters)
            )
            continue
        current.append(word)
        current_length += len(word) + (1 if len(current) > 1 else 0)
    if current:
        pieces.append(" ".join(current))
    return tuple(pieces)
