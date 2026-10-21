"""Insertion-only checked homework and concise professor notes."""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from homework_ta.domain.models import (
    GradeReport,
    GradingInput,
    InstructorReview,
    ReviewSection,
    SectionReview,
)


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


ADDITION_START = "% HOMEWORK_TA_ADDITION_BEGIN\n"
ADDITION_END = "% HOMEWORK_TA_ADDITION_END\n"


@dataclass(frozen=True)
class _Region:
    start: int
    end: int
    title: str


def _regions(answer: str) -> tuple[_Region, ...]:
    # Mask comments while retaining exact offsets; commented-out headings are not anchors.
    masked = re.sub(r"(?<!\\)%[^\r\n]*", lambda match: " " * len(match[0]), answer)
    begin = masked.find(r"\begin{document}")
    start = begin + len(r"\begin{document}") if begin >= 0 else 0
    end = masked.find(r"\end{document}") if begin >= 0 else len(answer)
    if end < start or (begin >= 0 and masked.count(r"\end{document}") != 1):
        raise ValueError("submitted TeX must have exactly one end{document}")
    headings = []
    for match in re.finditer(r"\\(?:section|subsection|subsubsection)\*?(?:\[[^\]]*\])?\{", masked):
        if not start <= match.start() < end:
            continue
        depth = 1
        index = match.end()
        while index < end and depth:
            if masked[index] == "{" and (index == 0 or masked[index - 1] != "\\"):
                depth += 1
            elif masked[index] == "}" and masked[index - 1] != "\\":
                depth -= 1
            index += 1
        if depth:
            raise ValueError("cannot locate annotations: unbalanced section title")
        headings.append((match.start(), answer[match.end() : index - 1]))
    boundaries = [(start, "Answer"), *headings, (end, "")]
    return tuple(
        _Region(offset, boundaries[i + 1][0], title)
        for i, (offset, title) in enumerate(boundaries[:-1])
    )


def _source(grading_input: GradingInput, original_answer: str | None) -> str:
    answer = grading_input.submission.answer if original_answer is None else original_answer
    if answer.strip() != grading_input.submission.answer.strip():
        raise ValueError("original answer does not match the assessed submission")
    if ADDITION_START in answer or ADDITION_END in answer:
        raise ValueError("original answer contains reserved annotation markers")
    return answer


def review_sections(
    grading_input: GradingInput, report: GradeReport, original_answer: str | None = None
) -> tuple[ReviewSection, ...]:
    answer = _source(grading_input, original_answer)
    regions = _regions(answer)
    groups: dict[int, list[str]] = {}
    for criterion in grading_input.rubric.criteria:
        candidates = []
        for scored in (report.analyst, report.verifier):
            assessed = next(
                c for c in scored.assessment.criteria if c.criterion_id == criterion.criterion_id
            )
            for evidence in assessed.evidence:
                if evidence.source_id != "student_answer":
                    continue
                for match in re.finditer(re.escape(evidence.quote), answer):
                    for index, region in enumerate(regions):
                        if region.start <= match.start() < region.end:
                            words = set(re.findall(r"[a-z0-9]+", evidence.location.lower()))
                            title_words = set(re.findall(r"[a-z0-9]+", region.title.lower()))
                            candidates.append((len(words & title_words), -match.start(), index))
        if not candidates:
            raise ValueError(
                f"cannot place {criterion.criterion_id}: no exact student evidence anchor"
            )
        index = max(candidates)[2]
        groups.setdefault(index, []).append(criterion.criterion_id)
    return tuple(
        ReviewSection(
            section_id=f"section_{index}",
            title=regions[index].title,
            criterion_ids=tuple(groups[index]),
        )
        for index in sorted(groups)
    )


def _default_review(report: GradeReport, sections: tuple[ReviewSection, ...]) -> InstructorReview:
    # Offline rendering fallback. Live CLI uses the dedicated concise review writer.
    return InstructorReview(
        overall_summary=report.analyst.assessment.overall_summary[:450],
        bottleneck_questions=(),
        sections=tuple(
            SectionReview(section_id=s.section_id, summary="Assessment recorded.") for s in sections
        ),
    )


def ta_notes(report: GradeReport, review: InstructorReview | None = None) -> str:
    summary = review.overall_summary if review else report.analyst.assessment.overall_summary[:450]
    lines = [f"TA notes — {report.submission_id}", summary]
    if report.reconciliation.total_awarded_points is None:
        lines.append("Final score withheld pending human review.")
    if review and review.bottleneck_questions:
        lines.extend(["", "Questions for the student:"])
        lines.extend(f"- {question}" for question in review.bottleneck_questions)
    return "\n".join(lines) + "\n"


def markdown_notes(report: GradeReport, review: InstructorReview | None = None) -> str:
    notes = ta_notes(report, review)
    runs = re.findall(r"`+", notes)
    fence = "`" * max(3, max((len(run) + 1 for run in runs), default=3))
    return f"# Teaching assistant notes\n\n{fence}text\n{notes}{fence}\n"


def _addition(text: str) -> str:
    return ADDITION_START + text + ADDITION_END


def annotated_latex(
    grading_input: GradingInput,
    report: GradeReport,
    review: InstructorReview | None = None,
    original_answer: str | None = None,
) -> str:
    answer = _source(grading_input, original_answer)
    regions = _regions(answer)
    sections = review_sections(grading_input, report, original_answer)
    review = review or _default_review(report, sections)
    if [s.section_id for s in review.sections] != [s.section_id for s in sections]:
        raise ValueError("review sections do not match evidence placements")
    insertions: list[tuple[int, str]] = []
    reconciled = {c.criterion_id: c for c in report.reconciliation.criteria}
    for section, comment in zip(sections, review.sections, strict=True):
        criteria = [reconciled[c] for c in section.criterion_ids]
        maximum = sum((c.max_points for c in criteria), Decimal(0))
        approved = report.reconciliation.total_awarded_points is not None and all(
            c.awarded_points is not None for c in criteria
        )
        if approved:
            points = sum((c.awarded_points for c in criteria), Decimal(0))
            score = f"Score: {points}/{maximum}"
        else:
            analyst = sum((c.analyst_points for c in criteria), Decimal(0))
            verifier = sum((c.verifier_points for c in criteria), Decimal(0))
            score = (
                f"Provisional: {analyst}/{maximum}"
                if analyst == verifier
                else f"Provisional: analyst {analyst}/{maximum}; verifier {verifier}/{maximum}"
            )
        text = f"AI review ({', '.join(section.criterion_ids)}): {comment.summary} {score}."
        if comment.questions:
            text += " Ask: " + " ".join(comment.questions)
        block = (
            "\n"
            + r"\par\begingroup\color{red}\small\noindent "
            + escape_tex(text)
            + r"\par\endgroup"
            + "\n"
        )
        index = int(section.section_id.removeprefix("section_"))
        insertions.append((regions[index].end, _addition(block)))
    if r"\begin{document}" in answer:
        if not re.search(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\bxcolor\b[^}]*\}", answer):
            insertions.append(
                (answer.index(r"\begin{document}"), _addition(r"\usepackage{xcolor}" + "\n"))
            )
    else:
        insertions.append(
            (
                0,
                _addition(
                    r"\documentclass{article}"
                    + "\n"
                    + r"\usepackage{amsmath,amssymb,xcolor}"
                    + "\n"
                    + r"\begin{document}"
                    + "\n"
                ),
            )
        )
        insertions.append((len(answer), _addition("\n" + r"\end{document}" + "\n")))
    # Slice-insert only: every original character, including trailing newlines, is retained.
    result = answer
    for offset, text in reversed(sorted(insertions, key=lambda item: item[0])):
        result = result[:offset] + text + result[offset:]
    return result


def remove_annotations(checked: str) -> str:
    """Verification helper: recovering original source must be exact."""
    return re.sub(
        re.escape(ADDITION_START) + r".*?" + re.escape(ADDITION_END), "", checked, flags=re.DOTALL
    )
