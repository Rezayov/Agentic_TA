"""Deterministic instructor notes and escaped red annotations for derived TeX."""

import re
from pathlib import Path

from homework_ta.domain.models import GradeReport, GradingInput


def student_folder(root: Path, submission_id: str | None) -> Path:
    if submission_id is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", submission_id):
        raise ValueError(
            "student output requires a submission ID containing letters, digits, _ or -"
        )
    # Prepared filenames often include a name after the student number.
    match = re.match(r"^(\d+)(?:_|$)", submission_id)
    name = match[1] if match else submission_id
    folder = (root / name).resolve()
    if folder.parent != root.resolve():
        raise ValueError("student output folder must remain inside the output directory")
    return folder


def ta_notes(report: GradeReport) -> str:
    lines = [
        f"TA notes — {report.submission_id}",
        f"Question: {report.question_id}",
        f"Status: {report.reconciliation.status.value}",
    ]
    if report.reconciliation.total_awarded_points is None:
        lines.append("Final score withheld pending human review.")
    else:
        lines.append(
            f"Score: {report.reconciliation.total_awarded_points} / "
            f"{report.reconciliation.max_points}"
        )
    for scored in (report.analyst, report.verifier):
        lines.extend(["", f"{scored.assessment.role}: {scored.assessment.overall_summary}"])
        for criterion in scored.assessment.criteria:
            lines.append(
                f"{criterion.criterion_id}: {criterion.awarded_points} points; "
                f"confidence {criterion.confidence:.2f}. {criterion.reasoning}"
            )
            for evidence in criterion.evidence:
                lines.append(
                    f"  Evidence: {evidence.source_id}, {evidence.location}: "
                    f"{evidence.quote} — {evidence.explanation}"
                )
            lines.extend(f"  Concern: {concern}" for concern in criterion.concerns)
    lines.extend(["", "Review issues:"])
    lines.extend(
        f"{issue.criterion_id}: {issue.code.value} — {issue.detail}"
        for issue in report.reconciliation.review_issues
    )
    if report.feedback:
        lines.extend(
            [
                "",
                "Student feedback:",
                report.feedback.summary,
                *report.feedback.strengths,
                *report.feedback.improvements,
                *report.feedback.diagnostic_questions,
            ]
        )
    return "\n".join(lines) + "\n"


def escape_tex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def annotated_latex(grading_input: GradingInput, report: GradeReport) -> str:
    """Append instructor-only annotations; model text is escaped, never executed as TeX.

    The submitted answer is copied verbatim. This does not compile untrusted TeX.
    Review cases contain provisional assessor comments, explicitly labelled.
    """
    answer = grading_input.submission.answer
    notes = ta_notes(report).replace("—", "--")
    paragraphs = "\n".join(escape_tex(line) + r"\par" for line in notes.splitlines())
    annotation = (
        "\n\\section*{TA annotations (instructor copy)}\n"
        "\\begingroup\\color{red}\n" + paragraphs + "\n\\endgroup\n"
    )
    if r"\begin{document}" in answer:
        if answer.count(r"\end{document}") != 1:
            raise ValueError("submitted TeX must have exactly one end{document}")
        if not re.search(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\bxcolor\b[^}]*\}", answer):
            answer = answer.replace(
                r"\begin{document}", "\\usepackage{xcolor}\n\\begin{document}", 1
            )
        return answer.replace(r"\end{document}", annotation + r"\end{document}", 1)
    return (
        "\\documentclass{article}\n\\usepackage{amsmath,amssymb,xcolor}\n"
        "\\begin{document}\n" + answer + annotation + "\\end{document}\n"
    )
