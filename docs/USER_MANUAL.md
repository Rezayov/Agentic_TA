# Homework TA user manual

## Where your results go

The default destination is the project's `outputs/` directory, regardless of your
terminal's current directory. Each student has one folder with two files:

```text
Agentic_TA/
  outputs/
    403200498/
      403200498_checked.tex
      403200498_notes.md
    404210037/
      404210037_checked.tex
      404210037_notes.md
    _batch/
      <run-time>.json
```

The checked homework preserves every original character and adds short red reviews,
section scores, and bottleneck questions beside the assessed sections. The professor
note contains only an overall summary and questions to ask the student. The original
submission is never edited. The application produces TeX source, not an exported PDF.

The `_batch` file is the class-run status summary, outside student folders. Prepared
inputs, diagnostic logs, and full assessment audits go into the assignment's
`work/batch-<run-time>/` directory. Earlier test results under
`data/qft1_hw1/outputs/` are historical; new commands below use project `outputs/`.

## 1. Set up once

Open a terminal in the project:

```sh
cd /Users/rezayov/projects/Agentic_TA
uv sync
```

Keep your existing `.env`; do not overwrite it. If starting from a new checkout,
copy `.env.example` to `.env` and enter your own keys. Keys stay in `.env`; endpoint
and model settings stay in `config/router.jsonc`. The commands below load `.env`
automatically with `--env-file .env`.

Your configured order is GCAT (Gemini, then GPT), AgentRouter, Dahl, Hormouz.
The router retries each model up to three times before moving on. GCAT uses a
32,768-token budget to avoid truncating the long homework assessments.

Check connectivity without any student material:

```sh
uv run --env-file .env homework-ta-check-provider --prompt "hey there"
```

## 2. Prepare the reference index

The QFT assignment already has `data/qft1_hw1/indexes/references.sqlite3`.
Rebuild it after changing reference materials:

```sh
uv run homework-ta-index data/qft1_hw1/indexes/references.sqlite3 \
  data/qft1_hw1/references/reference_solution.txt \
  data/qft1_hw1/references/relevant_chapter.tex
```

Use only solution/textbook references in the index. The assignment JSON supplies
the question and rubric; student answers do not belong in the reference index.

## 3. Run one student

Prepare the input using the original answer:

```sh
uv run homework-ta-prepare \
  data/qft1_hw1/assignment.json \
  data/qft1_hw1/submissions/403200498.tex \
  --submission-id 403200498 \
  --output data/qft1_hw1/work/403200498.json
```

Then grade it:

```sh
uv run --env-file .env homework-ta \
  data/qft1_hw1/work/403200498.json \
  --original-answer data/qft1_hw1/submissions/403200498.tex \
  --reference-db data/qft1_hw1/indexes/references.sqlite3
```

Read `outputs/403200498/403200498_notes.md` and open
`outputs/403200498/403200498_checked.tex` in the LaTeX editor.
`--original-answer` is required for complete TeX documents so the checked copy
preserves the exact source bytes, including newline style and final whitespace.

## 4. Run every student

The batch command finds all `.tex` files directly inside the submissions directory,
prepares each input, and grades students one at a time. It reuses the same assignment
and reference index. A failed student does not stop the remaining students.

First preview the class. This performs no API calls or file writes:

```sh
uv run homework-ta-batch \
  data/qft1_hw1/assignment.json \
  data/qft1_hw1/submissions \
  --reference-db data/qft1_hw1/indexes/references.sqlite3 \
  --skip-existing --dry-run
```

Then run it:

```sh
uv run --env-file .env homework-ta-batch \
  data/qft1_hw1/assignment.json \
  data/qft1_hw1/submissions \
  --reference-db data/qft1_hw1/indexes/references.sqlite3 \
  --skip-existing
```

`--skip-existing` skips a student only when both the notes and checked TeX files
already exist and are nonempty. It checks file presence, not whether the source,
rubric, or configuration has changed. Remove this flag to reassess everyone after
such changes. Reruns replace derived files only after a successful completion.
Files are individually atomic; the two-file update is not transactional.

Student IDs come from filenames: `403200498.tex` and `403200498_name.tex` both
produce `outputs/403200498/`. If a filename has no number, its stem is used as the
folder name. The supplied class has ten unique submissions, including four files
named without student numbers. Use the one-student command with `--submission-id`
when you need to assign a known number to one of those files; numbers are never guessed.
Two sources mapping to the same folder stop the batch before any grading calls.

To retry one failed student, follow section 3 with that student's file and ID.
To restart an interrupted class run, repeat the batch command with `--skip-existing`.
A partially written pair is rerun unless both files already exist; inspect the
latest batch summary if a previous run failed while older outputs were present.

The batch handles one shared question/assignment per run. For another homework,
use its own assignment JSON, submission directory, and reference index. It does
not automatically split multiple questions from a student's document.

## 5. Read the outcome

- `auto_approved`: mechanical agreement checks passed; review the instructor artifacts.
- `human_review`: artifacts were produced, but final grade is withheld. Scores in
  the checked homework are provisional. Inspect the concerns before approving anything.
- `failed`: no new validated checked homework was produced for that student. Earlier
  outputs, if any, may remain; inspect the corresponding log in `work/batch-<run-time>/`.
- `skipped_existing`: both output files were already present and no API call was made.

The batch summary lists the outcome for each student. The command exits with code 1
if any student failed, and code 0 when all students completed or were skipped.
Human review is a completed assessment, not a provider failure.

## 6. Change the destination or router

To save this homework under another root, add the same option to the single or batch command:

```sh
--output-dir outputs/qft1_hw1
```

Results then go to `outputs/qft1_hw1/<student-number>/`. Use separate output roots
for different assignments to prevent one homework's checked files replacing another's.

To select a different router configuration, add:

```sh
--router-config config/router.jsonc
```

For a single run, an optional complete audit JSON can be saved outside the student
folder with `--output data/qft1_hw1/work/403200498-report.json`. Batch runs save
these audit files automatically in their separate work directory.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Missing provider key | Check `.env` variable names against each `api_key_env` in the router. |
| HTTP 401 | Check that provider's key/account. |
| HTTP 429 | Wait or rely on the configured fallback models. |
| HTTP 500 or stream error | Inspect the provider attempt log and retry later. |
| `finish_reason=length` | Increase that provider's supported token budget; never accept partial JSON. |
| Original answer mismatch | Reprepare the JSON from the exact file passed to `--original-answer`. |
| No exact evidence anchor | Review the assessment citation; the renderer refuses guessed placement. |
| Wrong output folder | Preview with `--dry-run` and inspect `--output-dir`. |

## Live progress while grading

Single-student and batch commands now show live progress automatically:

```text
[2/10] Student 404210037: grading; log .../404210037.jsonl
[14:30:00] Starting analyst assessment
[14:30:00] AnalystAssessment: gcat/agy/gemini-3.8-flash-high, attempt 1/3
[14:30:15] AnalystAssessment: waiting on gcat/agy/gemini-3.8-flash-high (15s elapsed)
[14:30:30] AnalystAssessment: waiting on gcat/agy/gemini-3.8-flash-high (30s elapsed)
```

Waiting messages appear every 15 seconds while the provider call or stream is
running. They show elapsed time, not an estimated completion time. Long reasoning
requests can take several minutes. After each response, the console shows
validation, retries or fallback, independent verifier progress, assessment
comparison, compact note generation, and artifact saving. Provider failures show
HTTP status or a safe local reason such as `finish_reason=length`; prompts, answer
text, keys and raw provider exception bodies are not printed in progress messages.

The detailed JSON log is still saved at the per-student path printed by the batch.
To watch an already-running older process, run `tail -f` on its printed `.jsonl`
file in a second terminal. Code changes do not update an already-running Python
process. New progress output appears when you restart the command. Restart with
`--skip-existing` to avoid repeating students whose two output files are complete.
The provider timeout is a transport/read timeout; a stream that continues sending
chunks can remain active longer than that setting.

## Evidence-selection errors and corrected retries

A successful greeting proves connectivity, but not that a provider can produce a
valid long assessment. The `schema_mismatch` log now shows the rule and field path.
The previously repeated failure at `criteria.19.evidence.0.quote` was a quote
outside the frozen whitelist, not a connection error.

Assessments now select `quote_id` values from a deterministic citation catalog.
The application resolves these to exact original excerpts and verifies that each
ID belongs to its claimed source. Analyst and verifier receive identical catalogs;
no rejected assessor text or conclusions are shared. The saved assessment report
still contains actual quotes and citation locations.

On local formatting/schema failures, router retries receive only the failed rule
and field path as correction guidance. Unknown IDs, source mismatches, invalid
scores, incomplete responses, and disagreements remain subject to the strict
validation and human-review policies. HTTP 500 remains a separate provider failure.

Restart an older running process to load these changes. The same batch command
with `--skip-existing` can resume completed students. No model priorities or provider
endpoints were changed by the evidence-ID fix.
