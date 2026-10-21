# Provider verification — 2026-10-13

The configured chain is AgentRouter (`deepseek-v4-flash`) then Dahl
(`zai-org/GLM-5.3-Flash`). No Kenrai configuration was present.

AgentRouter's [official Hermes guide](https://agentrouter.org/docs/hermes.html)
confirms the OpenAI Chat Completions endpoint `https://agentrouter.org/v1`
and lists `deepseek-v4-flash`. Its supported models can change.

A live synthetic test sent only `2 + 3 * 4`, requesting a JSON answer.
No submission or grading prompts were sent. AgentRouter returned authentication
errors (HTTP 401 in the direct connectivity probe) three times. The router then
selected Dahl, which returned `InternalServerError` three times. The router
terminated with `ProviderError`, without generating a grade.

This verifies the live attempt counts, fallback ordering, and safe exhaustion.
It does **not** verify DeepSeek availability or grading quality. A working
AgentRouter credential/account and a healthy Dahl endpoint are still needed.
Diagnostics are in the ignored `logs/synthetic-router-smoke.jsonl` file.
The key is stored only in the ignored local `.env`, not in this document or code.

The complete grading smoke test was blocked by automatic approval review because
it would transmit fixture submission content and grading prompts externally.
Output generation, assessor isolation, grading policies and routing are covered
by local tests with simulated responses instead.

After loading `.env`, rerun the privacy-safe check with:

```sh
uv run homework-ta-check-provider --provider agentrouter
uv run homework-ta-check-provider
```

## Homework failure investigation

A targeted GCAT Gemini assessment reproduced `finish_reason=length` with the
16,384-token configured budget. Only 3,443 characters of visible answer text
were available; the response began with a JSON code fence and was incomplete.
This confirms truncation, not merely a connectivity failure. The high-reasoning
model's token allocation is the likely explanation for the small visible response,
but reasoning-token usage was not captured in this probe.

GCAT's budget was increased to 32,768. The router now removes a single complete
JSON code fence before schema validation, while refusing truncated streams,
unclosed fences, surrounding commentary, or schema-invalid contents. Diagnostic
logs distinguish finish reasons, JSON parsing errors, schema validator/path,
and provider HTTP status without recording model content.

### Verified rerun

After the budget and wrapper changes, the full router run for student 403200498
completed on GCAT `agy/gemini-3.8-flash-high`. Both the analyst and independent
verifier passed schema and deterministic citation/score checks on their first
attempt. Both proposed 8.5/10; three assessor concerns correctly resulted in
`human_review`, with final score and student feedback withheld.

The successful artifacts are in `data/qft1_hw1/outputs/403200498/`:
`grade-report.json`, `ta-notes.txt`, and `annotated-answer.tex`. The red annotation
block and preserved answer body were checked locally. Original submission and
prepared input hashes were unchanged. The LaTeX source was checked structurally,
not compiled. Prior failed-test artifacts remain as an audit trail.

Diagnostics: `logs/student-403200498-investigation.jsonl`.
Validation: 86 tests passed; Ruff passed.

## Updated configuration connection check — 2026-10-13

The updated configuration added `g-cat` for `https://core.g-cat.ir/v1` and a separate
`gcat` entry for `https://core.gcat.ir/v1`. Initial loading failed locally because
hyphenated provider names were rejected, before any network request. The loader
now accepts short names containing letters, digits, underscores and hyphens,
while still rejecting path separators, whitespace, and control characters.

Live checks after the fix:

- Full router with literal `hey there`: passed on `g-cat`, Gemini, attempt 1.
- Isolated `gcat` / `core.gcat.ir` with literal `hey there`: passed, Gemini, attempt 1.
- Full router with the synthetic arithmetic JSON check: passed on `g-cat`, attempt 1.

No fallbacks or failed attempts occurred in these checks. No student content was
sent. These checks establish connectivity and small-response validation; they do
not establish that lengthy homework responses will fit the token budget.

Detailed logs: `logs/router-new-config-hello.jsonl`,
`logs/router-new-host-hello.jsonl`, and `logs/router-new-config-json.jsonl`.
The provider-check command now displays live progress and supports `--log-file`.
Regression checks: 111 tests passed; Ruff passed.

## Student 404210037: quote-whitelist failure and verified fix

The class-run log `batch-20261013T142359535093Z/404210037.jsonl` showed three GPT
schema rejections at `criteria[19].evidence[0].quote`, validator `enum`. All attempts
repeated the original prompt without correction feedback. Gemini separately returned
HTTP 500. The greeting check did not exercise those assessment constraints.

Adding failure feedback alone reproduced the same quote error. Assessment requests
were then changed to use frozen evidence IDs. The application resolves IDs to exact
quotes, enforces their source association, and keeps existing score and citation
checks. Raw report quotes and original submissions are not altered. Both assessors
receive identical catalogs; rejected response content is never added to retries.

A targeted run using `core.g-cat.ir` / `cx/gpt-6-luna-medium` completed:
analyst validation passed after one transient HTTP 500; independent verifier passed
after one invalid-JSON response was corrected; instructor notes passed. Scores
9.25/10 and 9/10 plus four review issues correctly produced `human_review`, not an
approved grade. The checked copy reconstructs the original student file exactly.

Artifacts are in `outputs/router-investigation/404210037/`; the detailed log is
`logs/404210037-evidence-id-investigation.jsonl`. This was a targeted GPT test,
not a claim that the Gemini/provider server errors were repaired.
Regression checks: 117 tests passed; Ruff passed.
