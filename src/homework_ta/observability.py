"""Privacy-safe JSON logging shared across application boundaries."""

import json
import logging
import os
from contextlib import suppress
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

LOGGER_NAME = "homework_ta"
MAX_LOG_BYTES = 5_000_000
BACKUP_COUNT = 3


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


def configure_logging(path: Path) -> str:
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
