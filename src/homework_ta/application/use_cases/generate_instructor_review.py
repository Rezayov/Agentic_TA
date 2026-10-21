"""Compress completed assessments into short instructor-only presentation notes."""

import json

from homework_ta.application.ports.llm import LanguageModel
from homework_ta.application.use_cases._structured import request_validated
from homework_ta.domain.models import GradeReport, InstructorReview, ReviewSection


class GenerateInstructorReview:
    def __init__(self, llm: LanguageModel, system_prompt: str) -> None:
        self._llm = llm
        self._prompt = system_prompt

    def execute(self, report: GradeReport, sections: tuple[ReviewSection, ...]) -> InstructorReview:
        expected = [section.section_id for section in sections]

        def check(review: InstructorReview) -> None:
            if [section.section_id for section in review.sections] != expected:
                raise ValueError("review sections must match the supplied IDs and order exactly")

        context = {
            "status": report.reconciliation.status.value,
            "sections": [section.model_dump() for section in sections],
            "assessments": [
                {
                    "summary": scored.assessment.overall_summary,
                    "criteria": [
                        {
                            "criterion_id": c.criterion_id,
                            "reasoning": c.reasoning,
                            "concerns": c.concerns,
                        }
                        for c in scored.assessment.criteria
                    ],
                }
                for scored in (report.analyst, report.verifier)
            ],
            "review_issues": [issue.model_dump() for issue in report.reconciliation.review_issues],
        }
        return request_validated(
            self._llm,
            system_prompt=self._prompt,
            data_json=json.dumps(context),
            result_type=InstructorReview,
            validate_result=check,
        )
