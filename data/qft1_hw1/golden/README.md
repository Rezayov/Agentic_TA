# QFT1 golden evaluation data

`scores.json` is the instructor-labeled evaluation set used by the optional golden
benchmark. Labels must be approved by the course instructor and must describe the
same rubric version and criterion scale as `assignment.json`. Do not populate it
from model reports or unreconciled TA/model grades.

The benchmark deliberately fails closed when no approved cases are present. Until
labels are supplied, run the metric and validation tests with `uv run pytest`; do
not claim a grading-accuracy result. Cases should use anonymous, stable IDs and
criterion-level scores in the rubric's allowed range.

Run after adding reviewed labels:

```console
uv run homework-ta-evaluate data/qft1_hw1/golden/scores.json
```

The command reports quadratic weighted kappa (QWK) and mean absolute error
(MAE), overall and per criterion. `--min-qwk` and `--max-mae` enforce caller-chosen
release gates. The default command reports metrics without claiming that a small
or unapproved dataset is statistically sufficient.
