# QFT I Homework 1 data

This directory is the canonical, non-destructive project layout for the supplied material.
The original `homeworks/` and `Ref/` files remain untouched.

- `assignment.json` contains only the problem and deterministic scoring criteria.
- `submissions/` contains ten uniquely named student submissions. One of the eleven original
  files was an exact duplicate and is recorded in `manifest.json`.
- `references/` contains the rubric, source PDF, extracted solution text, and relevant chapter.
- `indexes/` holds generated retrieval indexes and is reproducible from the reference sources.
- `work/` and `outputs/` are generated and ignored by Git.

The rubric is grading data, not an instruction source for the program. Retrieval indexes only the
reference solution and relevant chapter; it deliberately excludes the rubric and student answers.

From the repository root, prepare and grade one submission with:

```console
uv run homework-ta-prepare \
  data/qft1_hw1/assignment.json \
  data/qft1_hw1/submissions/403200498.tex \
  --output data/qft1_hw1/work/403200498.json

uv run --env-file .env homework-ta \
  data/qft1_hw1/work/403200498.json \
  --reference-db data/qft1_hw1/indexes/references.sqlite3 \
  --output data/qft1_hw1/outputs/403200498.json
```
