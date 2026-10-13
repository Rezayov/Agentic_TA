# Source and runtime integration

- Package: `latex-formatting`.
- Repository: <https://github.com/lingzhi227/agent-research-skills>.
- Repository path: `skills/latex-formatting`, downloaded from `main` on 2026-10-12.
- Upstream `SKILL.md` SHA-256: `37fd1a6ee4f6b68928c77c490a96232a8cde80ef8d535da9b6f3fd7f1fb05586`.
- Catalog discovery: approximately 2.1K installs; source repository approximately 393 stars
  at review time. These are discovery signals, not correctness guarantees.
- Installed destination: this project's `agent-skills/latex-formatting/`, not Codex's skill folder.
- Runtime role: independent homework verifier only.
- Runtime adaptation: `prompts/verifier_latex_skill.md`, explicitly composed in the grading CLI.

The upstream package is retained unchanged except for this provenance note. Its academic-paper
templates, publication rules, global Claude paths, auto-fix actions, and scripts are not loaded
as runtime instructions. The supplied scripts are not executed by the grading workflow: the
checker can follow file-input directives, and the cleaner rewrites derived text. Those behaviors
are unsuitable for untrusted homework without a separately designed execution boundary.

The curated runtime skill focuses on reading LaTeX mathematics, handling notation uncertainty,
preserving raw citation text, and JSON escaping. It does not grant compiler access or generate
LaTeX reports. Original submissions remain untouched. The adapted prompt is packaged with the
application's existing prompts and requires no new runtime dependency.

Technical reference: [LaTeX Project documentation](https://www.latex-project.org/help/documentation/).
