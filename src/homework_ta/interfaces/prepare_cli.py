"""Prepare a validated grading input from an assignment and an untouched answer file."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from homework_ta.domain.models import AssignmentDefinition

MAX_ASSIGNMENT_BYTES = 2_000_000
MAX_ANSWER_BYTES = 1_000_000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assignment", type=Path, help="reusable assignment JSON")
    parser.add_argument("answer", type=Path, help="student answer text or LaTeX file")
    parser.add_argument("--submission-id", help="stable ID; defaults to the answer filename stem")
    parser.add_argument("--output", type=Path, required=True, help="new grading-input JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        assignment_path = args.assignment.resolve(strict=True)
        answer_path = args.answer.resolve(strict=True)
        output_path = args.output.resolve()
        if output_path in {assignment_path, answer_path}:
            raise ValueError("output path must not overwrite an assignment or original submission")

        assignment = AssignmentDefinition.model_validate_json(
            _read_bounded(assignment_path, MAX_ASSIGNMENT_BYTES)
        )
        answer = _read_bounded(answer_path, MAX_ANSWER_BYTES).decode("utf-8").strip()
        if not answer:
            raise ValueError(f"answer file is empty: {answer_path}")
        submission_id = (args.submission_id or answer_path.stem).strip()
        grading_input = assignment.with_submission(
            submission_id=submission_id,
            answer=answer,
        )
        _write_atomic(output_path, grading_input.model_dump_json(indent=2) + "\n")
        print(f"Prepared {submission_id} at {output_path}")
        return 0
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{path} exceeds the {limit}-byte input limit")
    return data


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
