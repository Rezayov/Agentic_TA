import json

import pytest

from homework_ta.interfaces.evaluate_cli import (
    EvaluationDataError,
    evaluate,
    load_cases,
    mean_absolute_error,
    quadratic_weighted_kappa,
)


def test_qwk_perfect_and_linear_penalty() -> None:
    assert quadratic_weighted_kappa([0, 0.5, 1], [0, 0.5, 1]) == 1
    assert quadratic_weighted_kappa([0, 0.5, 1], [0.5, 0, 1]) == pytest.approx(0.5)


def test_mae() -> None:
    assert mean_absolute_error([0, 0.5, 0.5], [0.5, 0.5, 0]) == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    ("actual", "predicted"),
    [([], []), ([0], [0.5]), ([0, 1], [0])],
)
def test_qwk_rejects_undefined_or_mismatched_samples(actual, predicted) -> None:
    with pytest.raises(EvaluationDataError):
        quadratic_weighted_kappa(actual, predicted)


def test_load_cases_rejects_unapproved_empty_dataset(tmp_path) -> None:
    data = {
        "schema_version": 1,
        "approval_status": "awaiting_instructor_labels",
        "cases": [],
    }
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(data))
    with pytest.raises(EvaluationDataError, match="not instructor_approved"):
        load_cases(path)


def test_load_cases_validates_coverage_and_evaluation() -> None:
    cases = [
        {"case_id": "a", "gold": {"A1": 0, "A2": 0.5}, "predicted": {"A1": 0, "A2": 0}},
        {"case_id": "b", "gold": {"A1": 0.5, "A2": 0}, "predicted": {"A1": 0.5, "A2": 0}},
    ]
    metrics = evaluate(cases)
    assert metrics["cases"] == 2
    assert metrics["overall"]["qwk"] == pytest.approx(0.5)
    assert metrics["overall"]["mae"] == pytest.approx(0.125)
    assert metrics["by_criterion"]["A1"]["qwk"] == 1
