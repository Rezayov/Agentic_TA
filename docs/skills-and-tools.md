# Skills and tools review

Reviewed on 2026-10-12 against the current Homework TA code, the public skills catalog, upstream
skill sources, official library documentation, and the available app-integration catalog.
Recommendations below are proposed additions, not already implemented capabilities.

## Three places a capability can live

| Location | What it helps | Does it automatically change grading runtime? |
| --- | --- | --- |
| Codex development skill/tool | Writing, testing, inspecting documents, reviewing mathematics while developing. | No. |
| Application prompt guidance | Model instructions explicitly included by the Homework TA code. | Yes, only where the prompt is actually loaded. |
| Application runtime tool | A real bounded callable component integrated through an application port/use case. | Yes, after implementation and tests. |

This distinction prevents a common misunderstanding: installing a SymPy skill or Wolfram app for
Codex does not make the verifier call it during `uv run homework-ta`. The current language-model
port has messages/schema and completion text; it has no tool-call protocol or execution loop.

## Already useful in the project

| Capability | Current status and role |
| --- | --- |
| Math-reasoning instructions | Vendored at `agent-skills/math-reasoning/`; curated runtime guidance is in `prompts/verifier_math_skill.md`, verifier only. |
| LaTeX instructions | Now vendored at `agent-skills/latex-formatting/`; `prompts/verifier_latex_skill.md` is explicitly loaded into the verifier runtime. |
| Pydantic | Runtime contracts and schema generation; not a mathematical correctness checker. |
| SQLite FTS5 | Local reference retrieval before either assessor, with a frozen shared packet. |
| pytest / Ruff | Declared development dependencies for behavior checks and code quality. |
| Standard-library HTTP, logging, hashing, Decimal | Bounded provider integration and audit/scoring mechanics. |
| Codex PDF skill | Available in this development environment for document work; not an automatic application PDF parser. |

The existing math skill originates from
[lingzhi227/agent-research-skills](https://github.com/lingzhi227/agent-research-skills), a community
repository with approximately 393 stars at review time. Its catalog install count could not be
verified during this review. Its research-paper/LaTeX output instructions should not be injected
wholesale into a strict JSON grader; the current curated verifier adaptation is appropriate.

## Recommended order

### 1. Instructor-labeled evaluation cases and review resolution

This has the highest immediate value. Use the existing pytest/fixture workflow to assemble known
correct, partly correct, incorrect, ambiguous, and alternative-method answers. Include convergence,
normalization, units, limiting cases, and attempts to manipulate the grading prompt.

Record expected criterion judgments and instructor decisions. Measure per-criterion agreement,
unsafe automatic approvals, review rate, quote validity, and whether retrieved passages actually
cover the relevant material. A successful provider request and 40 passing mechanical tests do not
answer those evaluation questions.

Implement an explicit human-review decision record/use case before treating review reports as final
student grades. Keep both model assessments intact. This is a product capability rather than a
skill installation, and it fits the current architecture without another orchestration framework.

### 2. A small local SymPy checker for selected claims

[SymPy](https://docs.sympy.org/) is the most relevant potential computation library for symbolic
algebra, derivatives, expansions, limits, and expression comparison. Its
[assumption system](https://docs.sympy.org/latest/guides/assumptions.html) matters: an identity valid
for positive real variables is not necessarily valid for arbitrary complex variables.

**Proposed integration:** verifier mathematical checking, or instructor-authored reference checks
before packet construction. Introduce a narrow application port and an infrastructure adapter.
Requests should specify an allowed operation, structured expression, variable assumptions, and
resource limits. Results should preserve the expression, assumptions, method, and an explicit
`verified`, `disproved`, or `inconclusive` outcome. Treat unsupported checks as inconclusive and
retain human-review policy.

Do not execute arbitrary model/student Python or directly feed untrusted text into string parsers.
The official [SymPy parsing documentation](https://docs.sympy.org/latest/modules/parsing.html)
states that `parse_expr` uses `eval`. A future checker needs an allowlisted expression grammar
that constructs symbolic objects, bounded work, and tested operations. CAS output should not
silently settle an assessor disagreement.

An existing skill worth adapting is
[`K-Dense-AI/scientific-agent-skills@sympy`](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/sympy).
The skills CLI reported about **1.8K installs**, and the
[source repository](https://github.com/K-Dense-AI/scientific-agent-skills) showed about **48.5K stars**
at review time. It is a third-party scientific skill, not an official SymPy package. Its
[source instructions](https://raw.githubusercontent.com/K-Dense-AI/scientific-agent-skills/main/skills/sympy/SKILL.md)
cover assumptions and input trust. Adapt the relevant verification subset instead of adding
general plotting, code generation, or publication formatting to the assessor prompt.

Optional future skill installation command, **not executed in this review**:

```console
npx skills add K-Dense-AI/scientific-agent-skills --skill sympy
```

Inspect the selected installation target and source first. This command installs guidance for a
supported coding agent; it does not add SymPy to `pyproject.toml` or implement a Homework TA port.
The library has not been installed or compatibility-tested in this project's runtime here.

### 3. Reproducible PDF extraction with page provenance

This would turn the supplied PDF/text preparation into a proper ingestion boundary. Keep original
PDFs immutable; produce a distinct extracted artifact with document hash, page locations, extraction
method/version, and enough provenance to inspect quoted mathematics.

[PyMuPDF's text extraction](https://pymupdf.readthedocs.io/en/latest/the-basics.html) is a candidate
for digital PDFs. Its [OCR support](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html) handles
image-based text through Tesseract. Start with digital text and add OCR only when needed. Inspect
equations, subscripts, fractions, and reading order before trusting extracted content as references.

**Proposed role:** preparation/indexing infrastructure, not assessor decision-making. Preserve
verified page/span provenance through chunking and retrieval; update contracts/tests as needed.
Current locations are text heading/chunk labels rather than exact original PDF page offsets.

An established development skill is
[`anthropics/skills@pdf`](https://github.com/anthropics/skills/tree/main/skills/pdf), with approximately
**209.3K installs** on its [catalog page](https://skills.sh/anthropics/skills/pdf) and **180K+ source
repository stars** at review time. Its
[instructions](https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md) describe
PDF processing. Codex already has a PDF skill available here, so another development installation
is unnecessary unless it fills a specific missing need.

For reference only, a future installation command is:

```console
npx skills add anthropics/skills --skill pdf
```

Neither skill installation provides a tested runtime ingestion pipeline automatically.

### 4. Hypothesis and a static type checker for development

[Hypothesis](https://hypothesis.readthedocs.io/en/latest/) generates test inputs, including edge
cases, from stated ranges. It is a useful prospective development dependency for score bounds,
duplicate IDs, quote normalization, chunking, and malformed configuration. Complement the existing
specific regression tests with invariant checks such as “an unapproved result never has a final
total” or “invalid citations cannot produce a scored assessment.”

[mypy](https://mypy.readthedocs.io/en/stable/getting_started.html) could check the existing typed
contracts and adapters before execution. Add/configure it deliberately and resolve findings rather
than claiming the currently untyped HTTP boundaries are already statically verified. Neither
Hypothesis nor mypy is currently a declared project dependency.

### 5. Optional Wolfram integration for instructor/developer checking

The available integration catalog returned **Wolfram**, offering Wolfram Language/Wolfram|Alpha
computation. It was **not installed or connected** when reviewed, and no Wolfram computation was
performed. An optional suggestion was made; using it requires installing/connecting it in Codex.

Its most natural near-term use is an instructor/developer checking a difficult reference result.
Automated grading integration would be a separate implementation, with explicit requests, input
limits, assumptions, source/provenance, and recorded results. A Codex connection does not give the
Python verifier runtime access. Compare a local SymPy checker first when it covers the needed
operation without another external service.

## What should stay out for now

- Broad research/publication skill packs in the assessor context: they add unrelated formats,
  scripts, and instructions that can conflict with the JSON grading contract.
- Unrestricted code-execution tools: the current mathematical task calls for narrow checks.
- New orchestration frameworks, microservices, or vector stores without a measured requirement.
- Grading-time web search for arbitrary references: it would introduce changing evidence unless
  source approval, snapshotting, and traceability are designed explicitly.

Popularity is a discovery signal, not a correctness or security guarantee. Install/star counts
above are snapshots, not stable project requirements. Only specific relevant instructions should
be adapted, with provenance and regression checks.

## What happened in this review

The existing math skill/runtime prompts and declared dependencies were inspected. The skills
leaderboard and upstream sources were checked. The skills CLI search initially encountered an
npm/pnpm engine conflict in the workspace; running the catalog search from a temporary directory
succeeded. The plugin catalog found Wolfram as the relevant optional computation integration.

The initial discovery review added no grading skill, runtime dependency, CAS adapter, PDF ingestion
implementation, or external tool connection. The later LaTeX addition below integrates a skill
without changing runtime dependencies. The recommended
next implementation is evaluation/review handling, followed by a narrowly scoped mathematical
checker or PDF provenance according to your immediate workload.

## LaTeX runtime addition

At the owner's request, `lingzhi227/agent-research-skills@latex-formatting` was installed into this
project on 2026-10-12. The catalog reported approximately 2.1K installs; the source repository had
approximately 393 stars. See the project-local `agent-skills/latex-formatting/SOURCE.md` for origin
and content hash. The package was not installed into Codex's global skill directory.

The actual runtime adaptation is `prompts/verifier_latex_skill.md`, composed with the verifier's
existing mathematical guidance in the grading CLI. It covers LaTeX interpretation, notation
uncertainty, exact source citations, and JSON escaping. It excludes publication templates, automatic
file fixes, external input directives, shell execution, and compilation. Tests verify runtime
loading, verifier-only isolation, raw LaTeX citation validation, approved feedback, and fail-closed
startup when the required prompt is absent.
