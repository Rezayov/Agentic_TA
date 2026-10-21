"""Privacy-safe JSON logging shared across application boundaries."""

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

LOGGER_NAME = "homework_ta"
MAX_LOG_BYTES = 5_000_000
BACKUP_COUNT = 3


class ProgressFormatter(logging.Formatter):
    """Allowlisted terminal progress; never print prompts or raw exception bodies."""

    def format(self, record: logging.LogRecord) -> str:
        data = getattr(record, "event_data", {})
        event = record.getMessage()
        schema = data.get("schema_name", "completion")
        route = f"{data.get('provider', '')}/{data.get('model', '')}"
        student = data.get("submission_id")
        provider = data.get("provider")
        source_count = data.get("source_count")
        attempt, limit = data.get("attempt"), data.get("attempt_limit")
        elapsed = data.get("elapsed_seconds")
        status, issues = data.get("status"), data.get("review_issue_count")
        messages = {
            "grading_input_validated": f"Student {student}: input validated",
            "evidence_packet_frozen": f"Reference packet ready ({source_count} sources)",
            "assessment_started": f"Starting {data.get('role')} assessment",
            "assessment_completed": f"{data.get('role')} assessment validated",
            "provider_request_started": f"{schema}: {route}, attempt {attempt}/{limit}",
            "provider_request_waiting": f"{schema}: waiting on {route} ({elapsed}s elapsed)",
            "router_correction_requested": f"{schema}: retry will correct the failed response rule",
            "router_completion": f"{schema}: response received from {route}",
            "model_failover": f"Model exhausted: {route}; trying next configured model",
            "provider_failover": f"Provider exhausted: {provider}; trying next provider",
            "provider_skipped": f"Skipping {provider}: missing key",
            "structured_validation_succeeded": f"{schema}: validation passed",
            "structured_validation_failed": f"{schema}: schema check failed",
            "assessment_validation_failed": f"{schema}: grading/citation check failed",
            "reconciliation_completed": f"Assessment comparison: {status} ({issues} review issues)",
            "feedback_started": "Writing approved student feedback",
            "feedback_completed": "Student feedback ready",
            "feedback_withheld_for_human_review": "Student feedback withheld pending human review",
            "instructor_review_started": "Writing compact professor notes and section comments",
            "instructor_review_completed": "Professor notes validated",
            "artifacts_write_started": "Saving checked LaTeX and professor notes",
            "grading_run_completed": f"Student {student}: outputs saved ({status})",
            "grading_run_failed": f"Run failed ({data.get('error_type')}); see diagnostic log",
        }
        if event == "router_attempt_failed":
            details = data.get("response_diagnostics") or {}
            reason = details.get("reason") or data.get("error_type")
            if details.get("finish_reason"):
                reason = f"{reason}, finish_reason={details['finish_reason']}"
            if details.get("validator"):
                reason = f"{reason}, rule={details['validator']}"
            if details.get("path"):
                path = ".".join(str(part) for part in details["path"])
                reason = f"{reason}, field={path}"
            if data.get("http_status"):
                reason = f"{reason}, HTTP {data['http_status']}"
            messages[event] = f"{schema}: attempt {attempt} failed on {route}: {reason}"
        message = messages.get(event)
        return (
            f"[{datetime.fromtimestamp(record.created).strftime('%H:%M:%S')}] {message}"
            if message
            else ""
        )


class ProgressHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        if self.format(record):
            super().emit(record)


@contextmanager
def completion_progress(
    logger: logging.Logger, *, interval_seconds: float = 15, **fields: object
) -> Iterator[None]:
    """Report waits even before the SDK returns its first stream chunk."""
    if interval_seconds <= 0:
        raise ValueError("progress interval must be positive")
    finished = Event()
    started = monotonic()

    def heartbeat() -> None:
        while not finished.wait(interval_seconds):
            log_event(
                logger,
                logging.INFO,
                "provider_request_waiting",
                elapsed_seconds=round(monotonic() - started),
                **fields,
            )

    thread = Thread(target=heartbeat, daemon=True, name="homework-ta-progress")
    thread.start()
    try:
        yield
    finally:
        finished.set()
        thread.join()


class JsonLineFormatter(logging.Formatter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "run_id": self._run_id,
            "event": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(event_data)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_logging(path: Path, *, console: bool = False) -> str:
    """Configure bounded local logs and return a correlation ID for this run."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        path.parent.chmod(0o700)

    run_id = uuid4().hex
    handler = RotatingFileHandler(
        path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(JsonLineFormatter(run_id))
    try:
        os.chmod(path, 0o600)
    except OSError:
        handler.close()
        raise

    logger = logging.getLogger(LOGGER_NAME)
    for existing in logger.handlers:
        existing.close()
    logger.handlers.clear()
    logger.addHandler(handler)
    if console:
        progress = ProgressHandler()
        progress.setFormatter(ProgressFormatter())
        logger.addHandler(progress)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return run_id


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: object,
) -> None:
    logger.log(level, event, extra={"event_data": fields})
