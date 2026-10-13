"""Deterministic score validation and conservative reconciliation."""

from decimal import Decimal

from homework_ta.domain.models import (
    Assessment,
    Evidence,
    GradingInput,
    ReconciledCriterion,
    ReconciliationResult,
    ReconciliationStatus,
    ReviewCode,
    ReviewIssue,
    ScoredAssessment,
)


class GradingValidationError(ValueError):
    """Raised when an assessment violates the rubric or evidence contract."""


def validate_and_score(assessment: Assessment, grading_input: GradingInput) -> ScoredAssessment:
    """Validate rubric coverage, score limits, and evidence references."""

    rubric_by_id = {
        criterion.criterion_id: criterion for criterion in grading_input.rubric.criteria
    }
    assessments_by_id = {item.criterion_id: item for item in assessment.criteria}

    if len(assessments_by_id) != len(assessment.criteria):
        raise GradingValidationError("assessment contains duplicate criterion IDs")

    expected = set(rubric_by_id)
    actual = set(assessments_by_id)
    if expected != actual:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise GradingValidationError(
            f"criterion coverage mismatch; missing={missing}, unexpected={unexpected}"
        )

    source_content = {source.source_id: source.content for source in grading_input.source_material}
    source_content["student_answer"] = grading_input.submission.answer
    total = Decimal("0")

    for criterion_id, item in assessments_by_id.items():
        maximum = rubric_by_id[criterion_id].max_points
        if item.awarded_points > maximum:
            raise GradingValidationError(
                f"criterion {criterion_id!r} awards {item.awarded_points} above maximum {maximum}"
            )
        for evidence in item.evidence:
            if evidence.source_id not in source_content:
                raise GradingValidationError(
                    f"criterion {criterion_id!r} cites unknown source {evidence.source_id!r}"
                )
            if _normalize_quote(evidence.quote) not in _normalize_quote(
                source_content[evidence.source_id]
            ):
                raise GradingValidationError(
                    f"criterion {criterion_id!r} contains a quote not found in "
                    f"source {evidence.source_id!r}"
                )
        total += item.awarded_points

    return ScoredAssessment(
        assessment=assessment,
        total_awarded_points=total,
        max_points=grading_input.rubric.max_points,
    )


def reconcile(
    analyst: ScoredAssessment,
    verifier: ScoredAssessment,
    grading_input: GradingInput,
    *,
    minimum_confidence: float = 0.70,
) -> ReconciliationResult:
    """Approve exact, confident agreement; route every uncertain result to a human."""

    analyst_by_id = {item.criterion_id: item for item in analyst.assessment.criteria}
    verifier_by_id = {item.criterion_id: item for item in verifier.assessment.criteria}
    reconciled: list[ReconciledCriterion] = []
    issues: list[ReviewIssue] = []

    for rubric_item in grading_input.rubric.criteria:
        criterion_id = rubric_item.criterion_id
        analyst_item = analyst_by_id[criterion_id]
        verifier_item = verifier_by_id[criterion_id]
        confidence = min(analyst_item.confidence, verifier_item.confidence)
        agreed = analyst_item.awarded_points == verifier_item.awarded_points

        if not agreed:
            issues.append(
                ReviewIssue(
                    criterion_id=criterion_id,
                    code=ReviewCode.SCORE_DISAGREEMENT,
                    detail=(
                        f"analyst awarded {analyst_item.awarded_points}; "
                        f"verifier awarded {verifier_item.awarded_points}"
                    ),
                )
            )
        if confidence < minimum_confidence:
            issues.append(
                ReviewIssue(
                    criterion_id=criterion_id,
                    code=ReviewCode.LOW_CONFIDENCE,
                    detail=f"minimum assessor confidence is {confidence:.2f}",
                )
            )
        if analyst_item.concerns or verifier_item.concerns:
            issues.append(
                ReviewIssue(
                    criterion_id=criterion_id,
                    code=ReviewCode.ASSESSOR_CONCERN,
                    detail="; ".join((*analyst_item.concerns, *verifier_item.concerns)),
                )
            )

        evidence = _merge_evidence(analyst_item.evidence, verifier_item.evidence)
        reconciled.append(
            ReconciledCriterion(
                criterion_id=criterion_id,
                awarded_points=analyst_item.awarded_points if agreed else None,
                max_points=rubric_item.max_points,
                analyst_points=analyst_item.awarded_points,
                verifier_points=verifier_item.awarded_points,
                confidence=confidence,
                evidence=evidence,
            )
        )

    status = ReconciliationStatus.HUMAN_REVIEW if issues else ReconciliationStatus.AUTO_APPROVED
    total = None
    if status is ReconciliationStatus.AUTO_APPROVED:
        total = sum(
            (item.awarded_points for item in reconciled if item.awarded_points is not None),
            Decimal("0"),
        )

    return ReconciliationResult(
        status=status,
        criteria=tuple(reconciled),
        total_awarded_points=total,
        max_points=grading_input.rubric.max_points,
        review_issues=tuple(issues),
    )


def _merge_evidence(
    analyst_evidence: tuple[Evidence, ...], verifier_evidence: tuple[Evidence, ...]
) -> tuple[Evidence, ...]:
    merged: list[Evidence] = []
    seen: set[tuple[str, str, str, str]] = set()
    for evidence in (*analyst_evidence, *verifier_evidence):
        key = (evidence.source_id, evidence.location, evidence.quote, evidence.explanation)
        if key not in seen:
            seen.add(key)
            merged.append(evidence)
    return tuple(merged)


def _normalize_quote(value: str) -> str:
    return " ".join(value.split()).casefold()
