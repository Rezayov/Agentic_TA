import json
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from homework_ta.application.ports.llm import LLMRequest, LLMResponse
from homework_ta.application.use_cases._structured import (
    StructuredOutputError,
    request_validated,
)
from homework_ta.observability import configure_logging


class ExpectedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    awarded_points: int


class InvalidLLM:
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content='{"points_awarded": 1, "private_answer": "do not log me"}',
            model="wrong-schema-model",
        )


class RetryLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(content='{"points_awarded": 1}', model="retry-model")
        return LLMResponse(content='{"awarded_points": 1}', model="retry-model")


def test_structured_failure_log_records_shape_without_content(tmp_path: Path) -> None:
    log_path = tmp_path / "private" / "homework-ta.jsonl"
    configure_logging(log_path)

    with pytest.raises(StructuredOutputError):
        request_validated(
            InvalidLLM(),
            system_prompt="system",
            data_json='{"student_answer":"also private"}',
            result_type=ExpectedResult,
            validation_retries=0,
        )

    raw_log = log_path.read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw_log.splitlines()]
    failure = next(event for event in events if event["event"] == "structured_validation_failed")
    assert failure["response_shape"]["top_level_keys"] == [
        "points_awarded",
        "private_answer",
    ]
    assert "do not log me" not in raw_log
    assert "also private" not in raw_log
    assert log_path.stat().st_mode & 0o777 == 0o600

    logger = logging.getLogger("homework_ta")
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()


def test_structured_retry_includes_schema_and_concise_validation_feedback() -> None:
    llm = RetryLLM()

    result = request_validated(
        llm,
        system_prompt="system",
        data_json='{"student_answer":"private"}',
        result_type=ExpectedResult,
    )

    assert result.awarded_points == 1
    assert len(llm.requests) == 2
    first_prompt = llm.requests[0].messages[1].content
    retry_prompt = llm.requests[1].messages[1].content
    assert '"awarded_points"' in first_prompt
    assert "points_awarded" in retry_prompt
    assert "Extra inputs are not permitted" in retry_prompt
