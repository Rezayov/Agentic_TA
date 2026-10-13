"""Build a deterministic SQLite FTS5 index from text-based reference files."""

import argparse
import hashlib
import sys
from pathlib import Path

from homework_ta.application.ports.reference_retriever import RetrievalError
from homework_ta.infrastructure.references.chunking import ReferenceDocument
from homework_ta.infrastructure.references.sqlite_fts import build_reference_index

MAX_REFERENCE_BYTES = 20_000_000
SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".tex"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="output SQLite database")
    parser.add_argument("references", type=Path, nargs="+", help="Markdown, text, or LaTeX files")
    parser.add_argument(
        "--chunk-characters",
        type=int,
        default=2_400,
        help="maximum characters per heading-aware chunk",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        database_path = args.database.resolve()
        documents: list[ReferenceDocument] = []
        for reference in args.references:
            path = reference.resolve(strict=True)
            if path == database_path:
                raise ValueError("reference database must not overwrite an input file")
            if not path.is_file() or path.suffix.casefold() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"unsupported reference file: {path}")
            content = _read_text_bounded(path)
            documents.append(
                ReferenceDocument(
                    source_name=(
                        f"{path.name}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
                    ),
                    display_name=path.name,
                    content=content,
                )
            )
        fingerprint = build_reference_index(
            database_path,
            tuple(documents),
            chunk_characters=args.chunk_characters,
        )
        print(
            f"Indexed {len(documents)} reference file(s) into {database_path} ({fingerprint[:12]})"
        )
        return 0
    except (OSError, UnicodeDecodeError, ValueError, RetrievalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _read_text_bounded(path: Path) -> str:
    with path.open("rb") as handle:
        data = handle.read(MAX_REFERENCE_BYTES + 1)
    if len(data) > MAX_REFERENCE_BYTES:
        raise ValueError(f"{path} exceeds the reference-file size limit")
    return data.decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
