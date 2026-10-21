
import pytest
from test_workflow import FakeLLM, assessment_json, feedback_json, load_input, workflow

from homework_ta.interfaces.report_artifacts import (
    annotated_latex,
    escape_tex,
    markdown_notes,
    remove_annotations,
    review_sections,
    student_folder,
)


def test_student_number_and_traversal(tmp_path):
    assert student_folder(tmp_path, "403200498_name") == tmp_path / "403200498"
    for bad in (None, "..", "../escape", "/absolute", "a/b"):
        with pytest.raises(ValueError):
            student_folder(tmp_path, bad)


def test_annotation_preserves_source_and_marks_review():
    grading_input = load_input()
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier", result_points=0)])
    ).execute(grading_input)
    tex = annotated_latex(grading_input, report)
    assert grading_input.submission.answer in tex
    assert r"\color{red}" in tex
    assert "Provisional:" in tex
    assert remove_annotations(tex) == grading_input.submission.answer
    assert r"\end{document}" in tex
    assert escape_tex(r"\input{secret}%") == r"\textbackslash{}input\{secret\}\%"


@pytest.mark.parametrize(
    "submission_id,folder_name", [(None, "example_input"), ("403200498_name", "403200498")]
)
@pytest.mark.parametrize("export_json", [False, True])
def test_cli_outputs_student_artifacts(
    tmp_path, monkeypatch, submission_id, folder_name, export_json
):
    from homework_ta.interfaces import cli

    llm = FakeLLM(
        [
            assessment_json("analyst"),
            assessment_json("verifier"),
            feedback_json(),
            '{"overall_summary":"Correct method; check the reasoning orally.",'
            '"bottleneck_questions":[],"sections":[{"section_id":"section_0",'
            '"summary":"Valid method and result.","questions":[]}]}',
        ]
    )
    monkeypatch.delenv("HOMEWORK_TA_ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_PROVIDER_CONFIG", raising=False)
    monkeypatch.setattr(cli, "OpenAICompatibleLLM", lambda **kwargs: llm)
    source = tmp_path / "example_input.json"
    grading_input = load_input()
    grading_input = grading_input.model_copy(
        update={
            "submission": grading_input.submission.model_copy(
                update={"submission_id": submission_id}
            )
        }
    )
    source.write_text(grading_input.model_dump_json())
    original = source.read_bytes()
    export_args = ["--output", str(tmp_path / "separate-report.json")] if export_json else []
    assert (
        cli.main(
            [
                str(source),
                "--output-dir",
                str(tmp_path / "outputs"),
                "--log-file",
                str(tmp_path / "run.jsonl"),
                *export_args,
            ]
        )
        == 0
    )
    folder = tmp_path / "outputs" / folder_name
    assert {p.name for p in folder.iterdir()} == {
        f"{folder_name}_notes.md",
        f"{folder_name}_checked.tex",
    }
    notes = (folder / f"{folder_name}_notes.md").read_text()
    assert notes.startswith("# Teaching assistant notes")
    assert "Correct method" in notes
    assert "Complete audit report" not in notes
    assert source.read_bytes() == original
    assert (tmp_path / "separate-report.json").exists() is export_json


def test_cli_rejects_extra_json_inside_student_folder(tmp_path, monkeypatch):
    from homework_ta.interfaces import cli

    llm = FakeLLM([])
    monkeypatch.delenv("HOMEWORK_TA_ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_PROVIDER_CONFIG", raising=False)
    monkeypatch.setattr(cli, "OpenAICompatibleLLM", lambda **kwargs: llm)
    root = tmp_path / "outputs"
    assert (
        cli.main(
            [
                "tests/fixtures/example_input.json",
                "--output-dir",
                str(root),
                "--output",
                str(root / "example_input" / "extra.json"),
                "--log-file",
                str(tmp_path / "run.jsonl"),
            ]
        )
        == 1
    )
    assert not llm.requests
    assert not root.exists()
    assert cli.build_parser().parse_args(["input.json"]).output_dir == cli._default_output_dir()


def test_markdown_notes_keep_untrusted_text_inside_fences():
    report = workflow(
        FakeLLM(
            [
                assessment_json("analyst", summary="```<script>bad</script>"),
                assessment_json("verifier", result_points=0),
            ]
        )
    ).execute(load_input())
    notes = markdown_notes(report)
    assert "````text\n" in notes
    assert "```<script>bad</script>" in notes
    assert "Final score withheld pending human review." in notes
    assert "Complete audit report" not in notes


def test_full_document_inserts_annotations_and_avoids_duplicate_package():
    original = load_input()
    answer = (
        "\\documentclass{article}\n\\usepackage[dvipsnames]{xcolor}\n"
        "\\begin{document}\n" + original.submission.answer + "\n\\end{document}\n"
    )
    grading_input = original.model_copy(
        update={"submission": original.submission.model_copy(update={"answer": answer})}
    )
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    tex = annotated_latex(grading_input, report)
    assert tex.count("xcolor") == 1
    assert tex.index("AI review") < tex.index(r"\end{document}")
    assert remove_annotations(tex) == answer
    assert grading_input.submission.answer == answer


def test_malformed_document_rejected():
    original = load_input()
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    grading_input = original.model_copy(
        update={
            "submission": original.submission.model_copy(
                update={"answer": r"\begin{document}x = 4"}
            )
        }
    )
    with pytest.raises(ValueError, match="exactly one"):
        annotated_latex(grading_input, report)


def test_comments_follow_their_sections_and_source_is_exact():
    from homework_ta.domain.models import InstructorReview, SectionReview

    original = load_input()
    answer = (
        "\\documentclass{article}\r\n\\begin{document}\r\n"
        "\\section{A1}\r\nSubtracting 3 preserves equality.\r\n"
        "\\section{A1-1}\r\nx = 4\r\n\\end{document}\r\n"
    )
    grading_input = original.model_copy(
        update={"submission": original.submission.model_copy(update={"answer": answer.strip()})}
    )
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    sections = review_sections(grading_input, report, answer)
    assert [s.criterion_ids for s in sections] == [("method",), ("result",)]
    review = InstructorReview(
        overall_summary="Valid work.",
        bottleneck_questions=(),
        sections=(
            SectionReview(section_id=sections[0].section_id, summary="METHOD COMMENT"),
            SectionReview(section_id=sections[1].section_id, summary="RESULT COMMENT"),
        ),
    )
    checked = annotated_latex(grading_input, report, review, answer)
    assert (
        checked.index("Subtracting 3")
        < checked.index("METHOD COMMENT")
        < checked.index(r"\section{A1-1}")
    )
    assert (
        checked.index("x = 4") < checked.index("RESULT COMMENT") < checked.index(r"\end{document}")
    )
    assert remove_annotations(checked).encode() == answer.encode()
    assert "Score: 2/2" in checked
    assert "Score: 1/1" in checked


def test_unlocatable_evidence_refuses_to_guess():
    original = load_input()
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    grading_input = original.model_copy(
        update={"submission": original.submission.model_copy(update={"answer": "Unrelated source"})}
    )
    with pytest.raises(ValueError, match="no exact student evidence"):
        review_sections(grading_input, report)


def test_review_writer_uses_completed_assessments_without_original_answer():
    import json

    from homework_ta.application.use_cases.generate_instructor_review import (
        GenerateInstructorReview,
    )

    original = load_input()
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    sections = review_sections(original, report)
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "overall_summary": "Valid reasoning.",
                    "bottleneck_questions": [],
                    "sections": [
                        {
                            "section_id": sections[0].section_id,
                            "summary": "Correct.",
                            "questions": [],
                        }
                    ],
                }
            )
        ]
    )
    GenerateInstructorReview(llm, "instructor prompt").execute(report, sections)
    payload = llm.requests[0].messages[1].content
    assert original.submission.answer not in payload
    assert "StudentFeedback" not in payload


def test_wrong_original_answer_is_rejected():
    original = load_input()
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    with pytest.raises(ValueError, match="does not match"):
        annotated_latex(original, report, original_answer="different submission")
