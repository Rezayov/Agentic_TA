"""Reconcile two already validated assessments."""

from homework_ta.domain.models import (
    GradingInput,
    ReconciliationResult,
    ScoredAssessment,
)
from homework_ta.domain.scoring import reconcile


class ReconcileAssessments:
    def __init__(self, minimum_confidence: float = 0.70) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")
        self._minimum_confidence = minimum_confidence

    def execute(
        self,
        analyst: ScoredAssessment,
        verifier: ScoredAssessment,
        grading_input: GradingInput,
    ) -> ReconciliationResult:
        return reconcile(
            analyst,
            verifier,
            grading_input,
            minimum_confidence=self._minimum_confidence,
        )
