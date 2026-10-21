"""Validated data contracts for grading one homework response."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Immutable model that rejects undeclared input fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceExcerpt(StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=50_000)


class Submission(StrictModel):
    submission_id: str | None = Field(default=None, min_length=1, max_length=200)
    question_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=20_000)
    answer: str = Field(min_length=1, max_length=100_000)


class RubricCriterion(StrictModel):
    criterion_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2_000)
    max_points: Decimal = Field(gt=0, allow_inf_nan=False)


class Rubric(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def criterion_ids_are_unique(self) -> "Rubric":
        ids = [criterion.criterion_id for criterion in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("rubric criterion IDs must be unique")
        return self

    @property
    def max_points(self) -> Decimal:
        return sum((criterion.max_points for criterion in self.criteria), Decimal("0"))


class GradingInput(StrictModel):
    submission: Submission
    rubric: Rubric
    source_material: tuple[SourceExcerpt, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> "GradingInput":
        ids = [source.source_id for source in self.source_material]
        if "student_answer" in ids:
            raise ValueError("source_id 'student_answer' is reserved")
        if len(ids) != len(set(ids)):
            raise ValueError("source IDs must be unique")
        return self


class AssignmentDefinition(StrictModel):
    """Reusable assignment data, kept separate from each student submission."""

    question_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=20_000)
    rubric: Rubric
    source_material: tuple[SourceExcerpt, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> "AssignmentDefinition":
        ids = [source.source_id for source in self.source_material]
        if "student_answer" in ids:
            raise ValueError("source_id 'student_answer' is reserved")
        if len(ids) != len(set(ids)):
            raise ValueError("source IDs must be unique")
        return self

    def with_submission(self, *, submission_id: str, answer: str) -> GradingInput:
        return GradingInput(
            submission=Submission(
                submission_id=submission_id,
                question_id=self.question_id,
                question=self.question,
                answer=answer,
            ),
            rubric=self.rubric,
            source_material=self.source_material,
        )


class RetrievalHit(StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=300)
    rank: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetrievalTrace(StrictModel):
    query: str = Field(min_length=1, max_length=50_000)
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hits: tuple[RetrievalHit, ...] = Field(min_length=1, max_length=20)


class Evidence(StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=2_000)
    explanation: str = Field(min_length=1, max_length=2_000)


class CriterionAssessment(StrictModel):
    criterion_id: str = Field(min_length=1, max_length=100)
    awarded_points: Decimal = Field(ge=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(min_length=1, max_length=4_000)
    evidence: tuple[Evidence, ...] = Field(min_length=1, max_length=20)
    concerns: tuple[str, ...] = Field(default=(), max_length=20)


class Assessment(StrictModel):
    role: Literal["analyst", "verifier"]
    criteria: tuple[CriterionAssessment, ...] = Field(min_length=1, max_length=100)
    overall_summary: str = Field(min_length=1, max_length=4_000)

    @classmethod
    def schema_for_input(cls, grading_input: GradingInput) -> dict[str, Any]:
        """Constrain assessment identifiers to this input's deterministic contract."""

        schema = cls.model_json_schema()
        schema["$defs"]["Evidence"]["properties"]["source_id"]["enum"] = [
            "student_answer",
            *(source.source_id for source in grading_input.source_material),
        ]
        schema["$defs"]["CriterionAssessment"]["properties"]["criterion_id"]["enum"] = [
            criterion.criterion_id for criterion in grading_input.rubric.criteria
        ]
        criterion_count = len(grading_input.rubric.criteria)
        schema["properties"]["criteria"]["minItems"] = criterion_count
        schema["properties"]["criteria"]["maxItems"] = criterion_count
        schema["properties"]["criteria"]["description"] = (
            "Assess every rubric criterion exactly once, including criteria earning zero points."
        )
        # Exact excerpts prevent the provider from paraphrasing evidence. The local scorer
        # still checks that the selected quote belongs to the claimed source.
        quote_property = schema["$defs"]["Evidence"]["properties"]["quote"]
        quote_property["enum"] = citation_quotes(grading_input)
        quote_property["description"] = (
            "Select an exact excerpt from this enum belonging to your cited source_id. "
            "Explain its relevance in explanation; never rewrite the quoted excerpt."
        )
        return schema


def citation_quotes(grading_input: GradingInput) -> list[str]:
    """Build a bounded, deterministic quote catalog from the frozen input only."""

    sources = [
        grading_input.submission.answer,
        *(source.content for source in grading_input.source_material),
    ]
    quotes: list[str] = []
    seen: set[str] = set()
    for content in sources:
        # Every source retains a slot even if a preceding document is very long.
        source_quotes = [line.strip()[:300] for line in content.splitlines() if line.strip()]
        if not source_quotes:
            source_quotes = [content.strip()[:300]]
        useful = [quote for quote in source_quotes if len(quote) >= 12]
        candidates = useful or source_quotes
        stride = max(1, (len(candidates) + 63) // 64)
        for quote in candidates[::stride][:64]:
            if quote not in seen:
                quotes.append(quote)
                seen.add(quote)
    return quotes


class AnalystAssessment(Assessment):
    role: Literal["analyst"]


class VerifierAssessment(Assessment):
    role: Literal["verifier"]


class ScoredAssessment(StrictModel):
    assessment: Assessment
    total_awarded_points: Decimal = Field(ge=0, allow_inf_nan=False)
    max_points: Decimal = Field(gt=0, allow_inf_nan=False)


class ReviewCode(StrEnum):
    SCORE_DISAGREEMENT = "score_disagreement"
    LOW_CONFIDENCE = "low_confidence"
    ASSESSOR_CONCERN = "assessor_concern"


class ReviewIssue(StrictModel):
    criterion_id: str
    code: ReviewCode
    detail: str


class ReconciliationStatus(StrEnum):
    AUTO_APPROVED = "auto_approved"
    HUMAN_REVIEW = "human_review"


class ReconciledCriterion(StrictModel):
    criterion_id: str
    awarded_points: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_points: Decimal = Field(gt=0, allow_inf_nan=False)
    analyst_points: Decimal = Field(ge=0, allow_inf_nan=False)
    verifier_points: Decimal = Field(ge=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)


class ReconciliationResult(StrictModel):
    status: ReconciliationStatus
    criteria: tuple[ReconciledCriterion, ...] = Field(min_length=1)
    total_awarded_points: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_points: Decimal = Field(gt=0, allow_inf_nan=False)
    review_issues: tuple[ReviewIssue, ...] = ()


class StudentFeedback(StrictModel):
    summary: str = Field(min_length=1, max_length=4_000)
    strengths: tuple[str, ...] = Field(max_length=20)
    improvements: tuple[str, ...] = Field(max_length=20)
    diagnostic_questions: tuple[str, ...] = Field(min_length=2, max_length=4)


class GradeReport(StrictModel):
    submission_id: str | None = None
    question_id: str
    generated_at: datetime
    retrieval: RetrievalTrace | None = None
    analyst: ScoredAssessment
    verifier: ScoredAssessment
    reconciliation: ReconciliationResult
    feedback: StudentFeedback | None


class ReviewSection(StrictModel):
    section_id: str
    title: str
    criterion_ids: tuple[str, ...]


class SectionReview(StrictModel):
    section_id: str
    summary: str = Field(min_length=1, max_length=220)
    questions: tuple[str, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def short_questions(self) -> "SectionReview":
        if any(not question or len(question) > 180 for question in self.questions):
            raise ValueError("review questions must contain 1 to 180 characters")
        return self


class InstructorReview(StrictModel):
    overall_summary: str = Field(min_length=1, max_length=450)
    bottleneck_questions: tuple[str, ...] = Field(max_length=4)
    sections: tuple[SectionReview, ...]

    @model_validator(mode="after")
    def bounded_questions(self) -> "InstructorReview":
        if any(not question or len(question) > 180 for question in self.bottleneck_questions):
            raise ValueError("bottleneck questions must contain 1 to 180 characters")
        return self
