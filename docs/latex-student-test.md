# LaTeX skill and first-student test — 2026-10-12

## Installed in the homework agent

The upstream `latex-formatting` package is stored in `agent-skills/latex-formatting/`,
not Codex's global skills. Its provenance is in `SOURCE.md`. The verifier actually loads
`prompts/verifier_latex_skill.md` with its base and mathematical prompts. The analyst and
feedback writer do not load it. Missing required prompts stop startup.

This is prompt guidance for interpreting mathematical LaTeX and preserving exact citations,
not a compiler or an executable tool. Upstream cleanup/checker scripts are not executed.
Commands inside submissions remain untrusted data. Original submissions are never rewritten.

## Automated and packaging checks

- `uv run pytest`: 45 passed.
- `uv run ruff check .`: passed.
- Runtime tests cover verifier-only LaTeX loading, exact raw backslash citations,
  identical grading packets, approved feedback, and failure on missing skill guidance.
- The built wheel includes the verifier's base, mathematics, and LaTeX prompt files.
- HTTP retry tests cover Dahl's numeric 10-second cooldown, malformed-header fallback,
  and safe stopping for cooldowns longer than 60 seconds.

## First student: 403200498

An offline replay used this student's real prepared input, real reference index, and the
two assessments from the previous live report. It ran retrieval, both assessment validation
steps, deterministic scoring, and reconciliation through the current workflow, with the
new LaTeX prompt composed for the verifier.

The replay validated 20 criteria per assessor and 8 retrieved passages. Both received the
same grading data. It reproduced `human_review`: analyst 9.00, verifier 9.25. No final grade
or feedback was released. This is not a new model assessment and does not establish that
the remote model followed the newly added skill.

Original submission SHA-256 before and after testing:
`431d91808cffa6df2b9103012924673c2a78e48ff7b9bbaeb1912a4a6dcff212`.

## Live test remains blocked by the provider

Three full workflow launches against the configured Dahl GLM model returned HTTP 429 before
the analyst could finish. A small provider probe identified `model_concurrency` (model at
capacity), not an authentication failure. Dahl supplied `Retry-After: 10`.

The client previously retried after one second; it now honors the numeric cooldown, and
the final launch's logs confirm a 10-second delay. The second request still returned 429.
Run ID: `e9e038e6a49f413babf92d9b8d2fd69c`.

Logs: `logs/dahl-student-403200498-latex.jsonl`. These include `verifier_skills_loaded` and
prompt hashes, followed by the frozen packet hash and provider errors. No new successful
`403200498-dahl-latex.json` report was produced. The earlier `403200498-dahl.json` remains
unchanged and must not be mistaken for a live test of the new skill.

The GLM default profile was not changed. The owner subsequently authorized the MiniMax
test described below. A successful live first-student run remains outstanding.

```sh
uv run --env-file .env homework-ta data/qft1_hw1/work/403200498.json \
  --reference-db data/qft1_hw1/indexes/references.sqlite3 \
  --output data/qft1_hw1/outputs/403200498-dahl-latex.json \
  --log-file logs/dahl-student-403200498-latex.jsonl
```

## Authorized MiniMax live test

After the owner selected MiniMax, three full workflow launches used
`MiniMaxAI/MiniMax-M2.7` on the same Dahl endpoint. Each exhausted its two bounded transport
attempts: the remote endpoint closed the connection without an HTTP response after roughly
10 seconds. The analyst never completed, so the verifier and reconciliation did not run.
No `403200498-dahl-minimax-latex.json` report was created.

The first launch used the default GLM transport settings. The next two used the isolated
`config/provider.minimax.jsonc` profile: no streaming, no response-format parameter, and no
reasoning-effort parameter. The authoritative schema was still included in the prompt,
with the same local JSON, citation, coverage, and scoring validation. No grading safeguards
were bypassed. The default `config/provider.jsonc` and credentials remained unchanged.

Small diagnostic requests sometimes returned HTTP 200, confirming that this key and model
can be accepted. Those responses included `<think>` text in assistant content, rather than
bare JSON. Other small probes disconnected with plain, JSON-object, JSON-schema, and streaming
settings. A larger output-token allowance succeeded once while a smaller allowance failed.
This mixed evidence does not establish an unsupported setting or a specific server-side
cause. Full-request latency/capacity or gateway behavior are possibilities, not proven facts.
No production parsing was relaxed to accept reasoning text or arbitrary JSON fragments.

Logs: `logs/dahl-student-403200498-minimax-latex.jsonl`. Final run ID:
`b22355036d3f4ba08641a1021b64c051`. Each launch logged the mathematics/LaTeX skill hashes
and the unchanged frozen packet hash before sending the analyst request. The original
submission hash is unchanged. The final regression check still passes all 45 tests, lint,
and formatting.

The MiniMax profile is diagnostic, not confirmed working for grading. Repeat its live test:

```sh
HOMEWORK_TA_PROVIDER_CONFIG=config/provider.minimax.jsonc \
uv run --env-file .env homework-ta data/qft1_hw1/work/403200498.json \
  --model MiniMaxAI/MiniMax-M2.7 \
  --reference-db data/qft1_hw1/indexes/references.sqlite3 \
  --output data/qft1_hw1/outputs/403200498-dahl-minimax-latex.json \
  --log-file logs/dahl-student-403200498-minimax-latex.jsonl
```
