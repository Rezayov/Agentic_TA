# Dahl workflow diagnosis

Diagnostic work performed on 2026-10-12 using `zai-org/GLM-5.3-Flash` at
`https://inference.dahl.global/v1`. Credentials remain only in the ignored `.env`.

## Findings and fixes

1. A plain chat completion succeeded with the replacement key. The earlier key encountered
   HTTP 429 `model_concurrency`; a model-list response alone is not authentication evidence,
   because Dahl's model catalog is public.
2. Non-streaming assessment requests repeatedly disconnected after roughly 11 seconds.
   Explicit streaming produced complete responses. The client now accepts bounded OpenAI SSE,
   collects assistant content, ignores reasoning chunks, and requires a normal stop and `[DONE]`.
3. An early streaming assessment ended without a normal completion. The provider profile now
   sets a 16,384-token output budget and lower reasoning effort, with a bounded 10 MB transport
   allowance for SSE framing. Non-normal completions remain errors rather than partial grades.
4. Structurally valid assessments contained unknown citation IDs, altered quotes, and missing
   rubric criteria. Input-specific schemas now enumerate the source and criterion IDs, require
   the full criterion count, and include a deterministic catalog of exact excerpts from each
   source. The original full student answer and source passages remain available for assessment.
5. Deterministic citation/scoring failures previously stopped immediately. Assessors now get
   one fresh validation retry with the relevant error; repeatedly invalid output still fails
   closed. Neither rejected output nor the analyst's conclusions enter the verifier context.
6. A verifier stream ended without a complete usable response after the analyst had passed.
   Incomplete streams now receive bounded transport retries within the same workflow, preserving
   the validated analyst result. Diagnostic metadata records normal stop/DONE markers, token
   usage, and content/reasoning lengths without recording the text itself.

The optional temperature override is omitted for this provider. Small probes were inconsistent
with explicit sampling parameters; the main confirmed transport fix is streaming. No automatic
model switch or permissive JSON/quote repair was introduced.

## Audit and regression checks

The one-student input is submission `403200498`, question `qft1-hw1-problem4`, with 20 rubric
criteria worth 10 points total. Its frozen packet includes eight retrieved passages. Retrieval
queries use the question and rubric only, excluding the student answer.

- Frozen packet SHA-256: `10031aa5e298230af283a322c320b9b53ac3179924aae702c6d4bc3af95e602c`.
- Original submission SHA-256: `431d91808cffa6df2b9103012924673c2a78e48ff7b9bbaeb1912a4a6dcff212`.
- A separately prepared input matched the existing input exactly.
- Regression tests cover stream completeness and size limits, citation retry exhaustion,
  assessor independence, shared evidence, exact source excerpts, and provider settings.

## Completed one-student result

Run `e6329ae572714342b6fcbadeb8ad5785` completed successfully and atomically wrote
`data/qft1_hw1/outputs/403200498-dahl.json`. Both independent assessments passed JSON, exact
quote/source, complete criterion coverage, and score-limit validation for all 20 criteria.
The analyst completed on its first attempt; the verifier recovered from a connection failure
on its second transport attempt. The run took approximately seven minutes.

The final status is **human_review**, an intentional completed workflow outcome:

- Analyst proposed 9.00/10; verifier proposed 9.25/10. Neither is an approved final grade.
- D5 and D6 had minimum confidence 0.60, below the 0.70 threshold.
- D6 differed: analyst 0.25/0.5; verifier 0.5/0.5.
- The final score and student feedback were withheld as required by the grading policy.

An independent post-run check revalidated both saved assessments against a rebuilt frozen
packet, recomputed reconciliation, verified all eight retrieval hits, and confirmed the original
submission hash was unchanged. Report and credential files have `0600` permissions, and the
credential scan found no Dahl key outside `.env`. All 40 tests, Ruff lint, and formatting checks
passed. The auto-approved feedback branch is covered by regression tests; this real student
correctly exercised the human-review branch rather than generating feedback prematurely.

Logs record workflow stages, packet/response hashes, stream progress, and actionable validation
errors. They omit credentials, prompts, student answers, full model responses, and reasoning text.

## Reproduce the run

From the project root:

```console
uv run --env-file .env homework-ta \
  data/qft1_hw1/work/403200498.json \
  --reference-db data/qft1_hw1/indexes/references.sqlite3 \
  --output data/qft1_hw1/outputs/403200498-dahl.json \
  --log-file logs/dahl-student-403200498.jsonl
```

The endpoint, model, transport options, and token budget are in `config/provider.jsonc`.
An `auto_approved` report includes student feedback. A `human_review` report preserves assessor
disagreements or concerns and withholds the final score and student feedback until human review.
Provider load can still affect availability and latency; a successful run is not an assessment
accuracy benchmark or a guarantee of future service availability.

References: [Dahl API](https://inference.dahl.global/docs/api/) and
[vLLM GLM-5.3-Flash recipe](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash).
