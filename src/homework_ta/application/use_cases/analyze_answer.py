"""Primary assessment use case."""

from homework_ta.application.ports.llm import LanguageModel
from homework_ta.application.use_cases._structured import request_validated
from homework_ta.domain.models import AnalystAssessment, GradingInput, ScoredAssessment
from homework_ta.domain.scoring import validate_and_score


class AnalyzeAnswer:
    def __init__(self, llm: LanguageModel, system_prompt: str) -> None:
        self._llm = llm
        self._system_prompt = system_prompt

    def execute(self, grading_input: GradingInput) -> ScoredAssessment:
        assessment = request_validated(
            self._llm,
            system_prompt=self._system_prompt,
            data_json=grading_input.model_dump_json(),
            result_type=AnalystAssessment,
            validate_result=lambda result: validate_and_score(result, grading_input),
            response_schema=AnalystAssessment.schema_for_input(grading_input),
        )
        return validate_and_score(assessment, grading_input)
