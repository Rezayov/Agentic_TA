from decimal import Decimal

import pytest

from homework_ta.domain.models import (
    Assessment,
    CriterionAssessment,
    Evidence,
    GradingInput,
    ReconciliationStatus,
    Rubric,
    RubricCriterion,
    Submission,
)
from homework_ta.domain.scoring import GradingValidationError, reconcile, validate_and_score


def grading_input() -> GradingInput:
    return GradingInput(
        submission=Submission(question_id="q1", question="What is 1+1?", answer="2"),
        rubric=Rubric(
            title="Addition",
            criteria=(
                RubricCriterion(
                    criterion_id="correctness", description="Correct result", max_points=2
                ),
            ),
        ),
    )


def assessment(
    role: str,
    *,
    points: str = "2",
    confidence: float = 0.9,
    source_id: str = "student_answer",
    concerns: tuple[str, ...] = (),
) -> Assessment:
    return Assessment(
        role=role,
        overall_summary="The response is correct.",
        criteria=(
            CriterionAssessment(
                criterion_id="correctness",
                awarded_points=Decimal(points),
                confidence=confidence,
                reasoning="The computed sum is correct.",
                evidence=(
                    Evidence(
                        source_id=source_id,
                        location="answer",
                        quote="2",
                        explanation="This is the correct sum.",
                    ),
                ),
                concerns=concerns,
            ),
        ),
    )


def test_validate_and_score_rejects_over_allocation() -> None:
    with pytest.raises(GradingValidationError, match="above maximum"):
        validate_and_score(assessment("analyst", points="3"), grading_input())


def test_validate_and_score_rejects_unknown_evidence_source() -> None:
    with pytest.raises(GradingValidationError, match="unknown source"):
        validate_and_score(assessment("analyst", source_id="invented"), grading_input())


def test_validate_and_score_rejects_fabricated_quote() -> None:
    fabricated = assessment("analyst").model_copy(
        update={
            "criteria": (
                assessment("analyst")
                .criteria[0]
                .model_copy(
                    update={
                        "evidence": (
                            Evidence(
                                source_id="student_answer",
                                location="answer",
                                quote="three",
                                explanation="Not present in the answer.",
                            ),
                        )
                    }
                ),
            )
        }
    )

    with pytest.raises(GradingValidationError, match="quote not found"):
        validate_and_score(fabricated, grading_input())


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        (r"The result is \frac{1}{2}.", r"\frac{ 1 }{ 2 }"),
        (r"The result is \sqrt{4}.", r"\sqrt { 4 }"),
    ],
)
def test_validate_and_score_accepts_tex_whitespace_variants(source: str, quote: str) -> None:
    data = grading_input().model_copy(
        update={"submission": grading_input().submission.model_copy(update={"answer": source})}
    )
    item = assessment("analyst").criteria[0].model_copy(
        update={"evidence": (Evidence(source_id="student_answer", location="answer", quote=quote,
                                      explanation="A quoted mathematical expression."),)}
    )
    result = validate_and_score(
        assessment("analyst").model_copy(update={"criteria": (item,)}), data
    )
    assert result.total_awarded_points == Decimal("2")


def test_reconcile_auto_approves_exact_confident_agreement() -> None:
    data = grading_input()
    analyst = validate_and_score(assessment("analyst"), data)
    verifier = validate_and_score(assessment("verifier"), data)

    result = reconcile(analyst, verifier, data)

    assert result.status is ReconciliationStatus.AUTO_APPROVED
    assert result.total_awarded_points == Decimal("2")
    assert result.review_issues == ()


def test_reconcile_fails_closed_on_disagreement() -> None:
    data = grading_input()
    analyst = validate_and_score(assessment("analyst", points="2"), data)
    verifier = validate_and_score(assessment("verifier", points="1"), data)

    result = reconcile(analyst, verifier, data)

    assert result.status is ReconciliationStatus.HUMAN_REVIEW
    assert result.total_awarded_points is None
    assert result.criteria[0].awarded_points is None
    assert result.review_issues[0].code.value == "score_disagreement"


def test_reconcile_routes_low_confidence_and_concerns_to_review() -> None:
    data = grading_input()
    analyst = validate_and_score(
        assessment("analyst", confidence=0.6, concerns=("ambiguous notation",)), data
    )
    verifier = validate_and_score(assessment("verifier"), data)

    result = reconcile(analyst, verifier, data)

    assert result.status is ReconciliationStatus.HUMAN_REVIEW
    assert {issue.code.value for issue in result.review_issues} == {
        "low_confidence",
        "assessor_concern",
    }
