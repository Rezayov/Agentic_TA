# Requirements

## Current slice

The system grades one mathematical response represented as structured JSON. It must:

1. assess every rubric criterion with evidence;
2. obtain a second assessment in a fresh context;
3. validate both responses against strict contracts and deterministic rubric constraints;
4. finalize only exact score agreement at or above the configured confidence threshold;
5. route every other case to human review; and
6. create student feedback only for automatically approved results.

When textbook retrieval is enabled, the system must:

1. index UTF-8 Markdown, text, and LaTeX files without modifying them;
2. prefer structural headings when creating bounded chunks;
3. query from the assignment and rubric, excluding the student answer;
4. provide the same frozen evidence packet to both assessors; and
5. record ranks, source locations, content hashes, and the index fingerprint.

## Deferred

PDF extraction, semantic/vector retrieval, LaTeX report insertion and compilation, batch
processing, checkpointing, and instructor-calibrated evaluation are later vertical slices.

