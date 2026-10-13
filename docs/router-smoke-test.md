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
