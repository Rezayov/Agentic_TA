"""Rubric helpers kept separate from provider-facing orchestration."""

from homework_ta.domain.models import Rubric


def criterion_order(rubric: Rubric) -> tuple[str, ...]:
    """Return the instructor-defined criterion order."""

    return tuple(item.criterion_id for item in rubric.criteria)
