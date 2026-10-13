"""Student-facing feedback use case."""

import json

from homework_ta.application.ports.llm import LanguageModel
from homework_ta.application.use_cases._structured import request_validated
from homework_ta.domain.models import (
    GradingInput,
    ReconciliationResult,
    ReconciliationStatus,
    StudentFeedback,
)


class GenerateFeedback:
    def __init__(self, llm: LanguageModel, system_prompt: str) -> None:
        self._llm = llm
        self._system_prompt = system_prompt

    def execute(
        self, reconciliation: ReconciliationResult, grading_input: GradingInput
    ) -> StudentFeedback:
        if reconciliation.status is not ReconciliationStatus.AUTO_APPROVED:
            raise ValueError("feedback cannot be generated before human review is resolved")

        evidence_by_id = {
            criterion.criterion_id: [
                evidence.model_dump(mode="json") for evidence in criterion.evidence
            ]
            for criterion in reconciliation.criteria
        }
        # Deliberately omit every numeric score from the feedback writer's context.
        feedback_context = {
            "question": grading_input.submission.question,
            "student_answer": grading_input.submission.answer,
            "criteria": [
                {
                    "criterion_id": criterion.criterion_id,
                    "description": criterion.description,
                    "evidence": evidence_by_id[criterion.criterion_id],
                }
                for criterion in grading_input.rubric.criteria
            ],
        }
        return request_validated(
            self._llm,
            system_prompt=self._system_prompt,
            data_json=json.dumps(feedback_context, ensure_ascii=False, separators=(",", ":")),
            result_type=StudentFeedback,
        )
