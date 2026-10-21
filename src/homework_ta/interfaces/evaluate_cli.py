"""Evaluate archived predictions against instructor-approved criterion labels."""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


class EvaluationDataError(ValueError):
    """Raised when a golden evaluation file is malformed or not approved."""


def _scores(values: list[float], *, name: str) -> None:
    if not values:
        raise EvaluationDataError(f"{name} must not be empty")
    if any(not math.isfinite(value) for value in values):
        raise EvaluationDataError(f"{name} must contain finite numbers")


def quadratic_weighted_kappa(actual: list[float], predicted: list[float]) -> float:
    """Compute quadratic weighted Cohen's kappa for equally spaced ordinal scores."""
    if len(actual) != len(predicted):
        raise EvaluationDataError("actual and predicted score counts must match")
    _scores(actual, name="actual scores")
    _scores(predicted, name="predicted scores")
    if len(actual) == 1:
        if actual[0] != predicted[0]:
            raise EvaluationDataError("QWK is undefined for a single disagreeing observation")
        return 1.0
    labels = sorted(set(actual) | set(predicted))
    if len(labels) < 2:
        raise EvaluationDataError("QWK requires at least two distinct score values")
    index = {label: position for position, label in enumerate(labels)}
    size = len(labels)
    observed = [[0.0] * size for _ in labels]
    actual_hist = [0] * size
    predicted_hist = [0] * size
    for truth, guess in zip(actual, predicted, strict=True):
        i, j = index[truth], index[guess]
        observed[i][j] += 1
        actual_hist[i] += 1
        predicted_hist[j] += 1
    denominator = 0.0
    numerator = 0.0
    normalizer = (size - 1) ** 2
    for i in range(size):
        for j in range(size):
            weight = ((i - j) ** 2) / normalizer
            numerator += weight * observed[i][j]
            denominator += weight * actual_hist[i] * predicted_hist[j] / len(actual)
    if denominator == 0:
        raise EvaluationDataError("QWK is undefined when expected disagreement is zero")
    return 1 - numerator / denominator


def mean_absolute_error(actual: list[float], predicted: list[float]) -> float:
    """Compute mean absolute error for paired score lists."""
    if len(actual) != len(predicted):
        raise EvaluationDataError("actual and predicted score counts must match")
    _scores(actual, name="actual scores")
    _scores(predicted, name="predicted scores")
    return sum(abs(a - p) for a, p in zip(actual, predicted, strict=True)) / len(actual)


def load_cases(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate dataset structure and rubric-aligned approved criterion scores."""
    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationDataError(f"cannot read evaluation dataset {path}: {exc}") from exc
    if not isinstance(dataset, dict) or dataset.get("schema_version") != 1:
        raise EvaluationDataError("evaluation dataset must use schema_version 1")
    if dataset.get("approval_status") != "instructor_approved":
        raise EvaluationDataError("evaluation dataset is not instructor_approved")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationDataError("approved evaluation dataset must contain at least one case")
    ids: set[str] = set()
    criteria: set[str] | None = None
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise EvaluationDataError("each case must have a string case_id")
        if case["case_id"] in ids:
            raise EvaluationDataError(f"duplicate case_id {case['case_id']!r}")
        ids.add(case["case_id"])
        gold, predicted = case.get("gold"), case.get("predicted")
        if not isinstance(gold, dict) or not isinstance(predicted, dict) or not gold:
            raise EvaluationDataError(
                f"case {case['case_id']!r} needs non-empty gold and predicted maps"
            )
        if gold.keys() != predicted.keys():
            raise EvaluationDataError(f"criterion coverage mismatch in case {case['case_id']!r}")
        if criteria is None:
            criteria = set(gold)
        elif set(gold) != criteria:
            raise EvaluationDataError("all cases must cover the same criteria")
        for criterion, value in (*gold.items(), *predicted.items()):
            if (
                not isinstance(criterion, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
            ):
                raise EvaluationDataError(f"invalid score for criterion {criterion!r}")
            if not math.isfinite(value) or value not in (0, 0.5):
                raise EvaluationDataError(f"score for {criterion!r} must be 0 or 0.5")
    return dataset, cases


def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Return overall and per-criterion metrics for validated cases."""
    gold: dict[str, list[float]] = defaultdict(list)
    predicted: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        for criterion, score in case["gold"].items():
            gold[criterion].append(score)
            predicted[criterion].append(case["predicted"][criterion])
    flat_gold = [score for criterion in sorted(gold) for score in gold[criterion]]
    flat_predicted = [score for criterion in sorted(gold) for score in predicted[criterion]]
    return {
        "cases": len(cases),
        "criterion_count": len(gold),
        "overall": {
            "qwk": quadratic_weighted_kappa(flat_gold, flat_predicted),
            "mae": mean_absolute_error(flat_gold, flat_predicted),
        },
        "by_criterion": {
            criterion: {
                "qwk": quadratic_weighted_kappa(gold[criterion], predicted[criterion]),
                "mae": mean_absolute_error(gold[criterion], predicted[criterion]),
            }
            for criterion in sorted(gold)
            if len(set(gold[criterion]) | set(predicted[criterion])) > 1
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--min-qwk", type=float, help="fail if overall QWK is below this value")
    parser.add_argument("--max-mae", type=float, help="fail if overall MAE is above this value")
    args = parser.parse_args(argv)
    try:
        dataset, cases = load_cases(args.dataset)
        metrics = evaluate(cases)
    except EvaluationDataError as exc:
        parser.error(str(exc))
    metrics["dataset_id"] = dataset.get("dataset_id")
    metrics["rubric_version"] = dataset.get("rubric_version")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    if args.min_qwk is not None and metrics["overall"]["qwk"] < args.min_qwk:
        print("QWK is below --min-qwk", file=sys.stderr)
        return 1
    if args.max_mae is not None and metrics["overall"]["mae"] > args.max_mae:
        print("MAE is above --max-mae", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
