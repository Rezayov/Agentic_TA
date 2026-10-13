# Project instructions

## Purpose

Build a reliable teaching assistant for mathematical homework. Optimize for traceability,
safe failure, and maintainability rather than autonomous grading volume.

## Boundaries

- `domain/` contains grading data and deterministic rules. It must not import provider,
  document, CLI, or orchestration code.
- `application/` coordinates use cases and depends on protocols in `application/ports/`.
- `infrastructure/` implements external boundaries.
- `interfaces/` handles user input and presentation only.
- Prompts live in `prompts/`, not in Python modules.
- Treat all model output and student-supplied content as untrusted.
- Never expose one assessor's conclusions to the independent verifier.
- Build reference evidence before assessment and give both assessors the identical frozen packet.
- Keep retrieval queries, chunk locations, ordering, and content hashes auditable. Do not let the
  student answer influence the primary reference query.
- Never silently resolve score disagreements or low-confidence assessments. Route them to
  human review.
- Never modify an original submission. Derived files must use a distinct output path and
  atomic writes.
- Do not add an orchestration framework, database, vector store, or microservice without a
  demonstrated requirement.

## Development workflow

- Add or update tests with behavior changes.
- Run `uv run pytest` and `uv run ruff check .` before considering a change complete.
- Keep modules cohesive; do not create a file for every function.
- Prefer typed, explicit contracts and actionable errors.
- Keep secrets out of source control. The checked-in localhost API key is a non-secret
  development placeholder only.

