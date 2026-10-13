# ADR 0001: Start with an OpenAI-compatible localhost provider

## Status

Accepted for the first slice.

## Decision

Use a small provider adapter for `POST /chat/completions`, configured by environment variables
and defaulting to `http://localhost:8000/v1`. Keep the application dependent on a local protocol,
not the provider payload.

## Consequences

Local servers can be exchanged without changing grading logic. Provider-specific capabilities
remain isolated. JSON Schema response formatting is requested, but every response is still
validated locally. A future provider can implement the same application port.

