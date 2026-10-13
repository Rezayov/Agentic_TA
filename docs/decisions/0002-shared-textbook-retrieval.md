# ADR 0002: Shared lexical textbook retrieval before assessment

## Status

Accepted.

## Decision

Build a single evidence packet before either assessor runs. Retrieve heading-aware textbook
chunks using SQLite FTS5 and a query derived only from the question and rubric. Give the analyst
and verifier the identical packet and record a retrieval trace in the grade report.

## Consequences

- Assessment disagreement is not confounded by different retrieved evidence.
- Student text cannot directly manipulate the primary textbook query.
- Indexes are small, local, reproducible, and require no new service or embedding model.
- Lexical retrieval will miss some semantically related passages. Embeddings or hybrid retrieval
  should be added only after an evaluation set demonstrates that failure mode.
- PDF extraction remains a separate future boundary.
