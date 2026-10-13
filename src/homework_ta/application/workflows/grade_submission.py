"""End-to-end workflow for one structured homework response."""

import logging
from datetime import UTC, datetime
from hashlib import sha256

from homework_ta.application.use_cases.analyze_answer import AnalyzeAnswer
from homework_ta.application.use_cases.build_evidence_packet import BuildEvidencePacket
from homework_ta.application.use_cases.generate_feedback import GenerateFeedback
from homework_ta.application.use_cases.reconcile_assessments import ReconcileAssessments
from homework_ta.application.use_cases.verify_assessment import VerifyAssessment
from homework_ta.domain.models import (
    GradeReport,
    GradingInput,
    ReconciliationStatus,
)
from homework_ta.observability import log_event

LOGGER = logging.getLogger("homework_ta.workflow")


class GradeSubmission:
    def __init__(
        self,
        analyst: AnalyzeAnswer,
        verifier: VerifyAssessment,
        reconciler: ReconcileAssessments,
        feedback_writer: GenerateFeedback,
        evidence_builder: BuildEvidencePacket | None = None,
    ) -> None:
        self._analyst = analyst
        self._verifier = verifier
        self._reconciler = reconciler
        self._feedback_writer = feedback_writer
        self._evidence_builder = evidence_builder

    def execute(self, grading_input: GradingInput) -> GradeReport:
        retrieval = None
        if self._evidence_builder is not None:
            packet = self._evidence_builder.execute(grading_input)
            grading_input = packet.grading_input
            retrieval = packet.retrieval

        log_event(
            LOGGER,
            logging.INFO,
            "evidence_packet_frozen",
            packet_sha256=sha256(grading_input.model_dump_json().encode("utf-8")).hexdigest(),
            source_count=len(grading_input.source_material),
            retrieved_passage_count=len(retrieval.hits) if retrieval else 0,
        )

        log_event(LOGGER, logging.INFO, "assessment_started", role="analyst")
        analyst_result = self._analyst.execute(grading_input)
        log_event(LOGGER, logging.INFO, "assessment_completed", role="analyst")
        log_event(LOGGER, logging.INFO, "assessment_started", role="verifier")
        verifier_result = self._verifier.execute(grading_input)
        log_event(LOGGER, logging.INFO, "assessment_completed", role="verifier")
        reconciliation = self._reconciler.execute(analyst_result, verifier_result, grading_input)
        log_event(
            LOGGER,
            logging.INFO,
            "reconciliation_completed",
            status=reconciliation.status.value,
            review_issue_count=len(reconciliation.review_issues),
        )
        feedback = None
        if reconciliation.status is ReconciliationStatus.AUTO_APPROVED:
            feedback = self._feedback_writer.execute(reconciliation, grading_input)
            log_event(LOGGER, logging.INFO, "feedback_completed")
        else:
            log_event(LOGGER, logging.INFO, "feedback_withheld_for_human_review")

        return GradeReport(
            submission_id=grading_input.submission.submission_id,
            question_id=grading_input.submission.question_id,
            generated_at=datetime.now(UTC),
            retrieval=retrieval,
            analyst=analyst_result,
            verifier=verifier_result,
            reconciliation=reconciliation,
            feedback=feedback,
        )
