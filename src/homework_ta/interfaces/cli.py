"""Command-line interface for grading one structured submission."""

import argparse
import logging
import os
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from homework_ta.application.ports.llm import LanguageModel
from homework_ta.application.ports.reference_retriever import RetrievalError
from homework_ta.application.use_cases._structured import StructuredOutputError
from homework_ta.application.use_cases.analyze_answer import AnalyzeAnswer
from homework_ta.application.use_cases.build_evidence_packet import BuildEvidencePacket
from homework_ta.application.use_cases.generate_feedback import GenerateFeedback
from homework_ta.application.use_cases.generate_instructor_review import GenerateInstructorReview
from homework_ta.application.use_cases.reconcile_assessments import ReconcileAssessments
from homework_ta.application.use_cases.verify_assessment import VerifyAssessment
from homework_ta.application.workflows.grade_submission import GradeSubmission
from homework_ta.config import Settings
from homework_ta.domain.models import GradingInput
from homework_ta.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLM,
    ProviderError,
)
from homework_ta.infrastructure.llm.router import LiteLLMRouter, RouterConfig
from homework_ta.infrastructure.references.sqlite_fts import SQLiteReferenceRetriever
from homework_ta.interfaces.report_artifacts import (
    annotated_latex,
    markdown_notes,
    review_sections,
    student_folder,
)
from homework_ta.observability import configure_logging, log_event

MAX_INPUT_BYTES = 2_000_000
MAX_PROMPT_BYTES = 100_000
LOGGER = logging.getLogger("homework_ta.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="path to the grading input JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional additional JSON report path outside the student artifact folder",
    )
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=_default_prompts_dir(),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="root for per-student artifacts (default: project outputs directory)",
    )
    parser.add_argument(
        "--router-config",
        type=Path,
        help="ordered LiteLLM failover JSONC (or HOMEWORK_TA_ROUTER_CONFIG)",
    )
    parser.add_argument(
        "--original-answer",
        type=Path,
        help="original TeX file to preserve byte-for-byte in the checked copy",
    )
    parser.add_argument("--base-url", help="override HOMEWORK_TA_LLM_BASE_URL")
    parser.add_argument("--model", help="override HOMEWORK_TA_LLM_MODEL")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("logs/homework-ta.jsonl"),
        help="privacy-safe diagnostic log path",
    )
    parser.add_argument(
        "--reference-db",
        type=Path,
        help="optional SQLite FTS5 textbook index built by homework-ta-index",
    )
    parser.add_argument(
        "--retrieval-limit",
        type=int,
        default=8,
        help="maximum textbook passages to share with both assessors (1-20)",
    )
    return parser


def _default_output_dir() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    if (project_root / "pyproject.toml").is_file():
        return project_root / "outputs"
    return Path.cwd() / "outputs"


def _default_prompts_dir() -> Path:
    project_prompts = Path(__file__).resolve().parents[3] / "prompts"
    if project_prompts.is_dir():
        return project_prompts
    return Path(__file__).resolve().parents[1] / "prompts"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        input_path = args.input.resolve(strict=True)
        output_path = args.output.resolve() if args.output else None
        log_path = args.log_file.resolve()
        if input_path in {output_path, log_path} or output_path == log_path:
            raise ValueError("input, output, and log paths must all be different")
        run_id = configure_logging(log_path, console=True)
        log_event(
            LOGGER,
            logging.INFO,
            "grading_run_started",
            run_id=run_id,
            input_bytes=input_path.stat().st_size,
            reference_index_enabled=args.reference_db is not None,
        )

        grading_input = GradingInput.model_validate_json(_read_bounded(input_path, MAX_INPUT_BYTES))
        if grading_input.submission.submission_id is None:
            grading_input = grading_input.model_copy(
                update={
                    "submission": grading_input.submission.model_copy(
                        update={"submission_id": input_path.stem}
                    )
                }
            )
        log_event(
            LOGGER,
            logging.INFO,
            "grading_input_validated",
            submission_id=grading_input.submission.submission_id,
            question_id=grading_input.submission.question_id,
            criterion_count=len(grading_input.rubric.criteria),
            source_material_count=len(grading_input.source_material),
        )
        router_path = args.router_config or os.environ.get("HOMEWORK_TA_ROUTER_CONFIG")
        if router_path:
            if args.base_url or args.model:
                raise ValueError("edit router-config to override routed endpoints/models")
            settings = Settings(
                minimum_confidence=float(os.environ.get("HOMEWORK_TA_MINIMUM_CONFIDENCE", "0.70"))
            )
            settings.validate()
            llm: LanguageModel = LiteLLMRouter(RouterConfig.load(Path(router_path)))
        else:
            settings = Settings.from_environment(base_url=args.base_url, model=args.model)
            llm = OpenAICompatibleLLM(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
                max_response_bytes=settings.llm_max_response_bytes,
                send_temperature=settings.llm_send_temperature,
                stream=settings.llm_stream,
                response_format=settings.llm_response_format,
                max_tokens=settings.llm_max_tokens,
                reasoning_effort=settings.llm_reasoning_effort,
            )
        prompts_dir = args.prompts_dir.resolve(strict=True)
        evidence_builder = None
        if args.reference_db is not None:
            retriever = SQLiteReferenceRetriever(args.reference_db)
            evidence_builder = BuildEvidencePacket(retriever, max_results=args.retrieval_limit)
        workflow = GradeSubmission(
            analyst=AnalyzeAnswer(
                llm,
                _read_prompt(prompts_dir / "analyst.md")
                + "\n\n"
                + _read_prompt(prompts_dir / "assessment_citations.md"),
            ),
            verifier=VerifyAssessment(
                llm,
                _read_verifier_prompt(prompts_dir)
                + "\n\n"
                + _read_prompt(prompts_dir / "assessment_citations.md"),
            ),
            reconciler=ReconcileAssessments(settings.minimum_confidence),
            feedback_writer=GenerateFeedback(llm, _read_prompt(prompts_dir / "feedback_writer.md")),
            evidence_builder=evidence_builder,
        )
        folder = student_folder(args.output_dir.resolve(), grading_input.submission.submission_id)
        notes_path = folder / f"{folder.name}_notes.md"
        tex_path = folder / f"{folder.name}_checked.tex"
        if output_path is not None and output_path.is_relative_to(folder):
            raise ValueError("optional JSON report must be outside the student artifact folder")
        artifact_paths = {notes_path, tex_path}
        if output_path is not None:
            artifact_paths.add(output_path)
        if input_path in artifact_paths or log_path in artifact_paths:
            raise ValueError("input, log, report, and artifact paths must all be different")
        original_answer = None
        if args.original_answer is None and r"\begin{document}" in grading_input.submission.answer:
            raise ValueError(
                "use --original-answer for a full TeX submission to preserve exact bytes"
            )
        if args.original_answer is not None:
            original_path = args.original_answer.resolve(strict=True)
            if original_path in artifact_paths or original_path == log_path:
                raise ValueError("derived outputs must not overwrite the original answer")
            original_answer = _read_bounded(original_path, MAX_INPUT_BYTES).decode("utf-8")
            if original_answer.strip() != grading_input.submission.answer:
                raise ValueError("original answer does not match the assessed submission")
        report = workflow.execute(grading_input)
        sections = review_sections(grading_input, report, original_answer)
        log_event(LOGGER, logging.INFO, "instructor_review_started")
        review = GenerateInstructorReview(
            llm, _read_prompt(prompts_dir / "instructor_review.md")
        ).execute(report, sections)
        log_event(LOGGER, logging.INFO, "instructor_review_completed")
        notes = markdown_notes(report, review)
        tex = annotated_latex(grading_input, report, review, original_answer)
        log_event(LOGGER, logging.INFO, "artifacts_write_started")
        _write_atomic(notes_path, notes)
        _write_atomic(tex_path, tex)
        if output_path is not None:
            _write_atomic(output_path, report.model_dump_json(indent=2) + "\n")
        log_event(
            LOGGER,
            logging.INFO,
            "grading_run_completed",
            submission_id=report.submission_id,
            status=report.reconciliation.status.value,
        )
        print(f"Wrote {report.reconciliation.status.value} artifacts to {folder}", flush=True)
        return 0
    except (
        OSError,
        ValueError,
        ValidationError,
        ProviderError,
        RetrievalError,
        StructuredOutputError,
    ) as exc:
        log_event(
            LOGGER,
            logging.ERROR,
            "grading_run_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{path} exceeds the {limit}-byte input limit")
    return data


def _read_prompt(path: Path) -> str:
    data = _read_bounded(path, MAX_PROMPT_BYTES)
    prompt = data.decode("utf-8").strip()
    if not prompt:
        raise ValueError(f"prompt file is empty: {path}")
    return prompt


def _read_verifier_prompt(prompts_dir: Path) -> str:
    """Load both project skills into the independent verifier's runtime context."""

    filenames = ("verifier.md", "verifier_math_skill.md", "verifier_latex_skill.md")
    parts = tuple(_read_prompt(prompts_dir / filename) for filename in filenames)
    prompt = "\n\n".join(parts)
    log_event(
        LOGGER,
        logging.INFO,
        "verifier_skills_loaded",
        skills=["math-reasoning", "latex-formatting"],
        prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
        skill_prompt_hashes={
            filename: sha256(part.encode("utf-8")).hexdigest()
            for filename, part in zip(filenames[1:], parts[1:], strict=True)
        },
    )
    return prompt


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
