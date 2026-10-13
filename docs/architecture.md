# Architecture

Dependencies point inward:

```text
                         +-> retrieval port <- SQLite FTS5 index
                         |
CLI -> workflow -> evidence packet -> analyst + verifier -> reconciliation -> feedback
                                      |
                                      +-> LLM port <- configured OpenAI-compatible provider
```

The domain owns grading contracts and deterministic validation. Application use cases build
isolated model requests and validate the untrusted responses. Infrastructure owns HTTP and
provider-specific response parsing. The CLI owns files, arguments, and process exit codes.

The analyst and verifier each receive only the original grading input. Reconciliation begins
only after both independent calls complete. Feedback is a separate call to the configured model and is generated only
from an approved reconciliation result.

When a reference index is configured, `BuildEvidencePacket` searches with the assignment question
and rubric, applies a strict passage and character budget, and creates one immutable `GradingInput`.
Both assessors receive that exact object. Retrieval metadata is written to the report so every
retrieved source can be traced by rank, location, index fingerprint, and content hash.

For the complete code map, contracts, retry logic, provider transport, and extension guidance,
read [the owner's guide](OWNER_GUIDE.md). Operational commands and current provider settings are
in [the README](../README.md).

