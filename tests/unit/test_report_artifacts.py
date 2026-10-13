from pathlib import Path

import pytest
from test_workflow import FakeLLM, assessment_json, feedback_json, load_input, workflow

from homework_ta.interfaces.report_artifacts import annotated_latex, escape_tex, student_folder


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
    assert "Final score withheld pending human review." in tex
    assert r"\end{document}" in tex
    assert escape_tex(r"\input{secret}%") == r"\textbackslash{}input\{secret\}\%"


def test_cli_outputs_student_artifacts(tmp_path, monkeypatch):
    from homework_ta.interfaces import cli

    llm = FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    monkeypatch.delenv("HOMEWORK_TA_ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("HOMEWORK_TA_PROVIDER_CONFIG", raising=False)
    monkeypatch.setattr(cli, "OpenAICompatibleLLM", lambda **kwargs: llm)
    source = Path("tests/fixtures/example_input.json")
    original = source.read_bytes()
    assert (
        cli.main(
            [
                str(source),
                "--output-dir",
                str(tmp_path / "outputs"),
                "--log-file",
                str(tmp_path / "run.jsonl"),
            ]
        )
        == 0
    )
    folder = tmp_path / "outputs" / "example_input"
    assert {p.name for p in folder.iterdir()} == {
        "grade-report.json",
        "ta-notes.txt",
        "annotated-answer.tex",
    }
    assert source.read_bytes() == original


def test_full_document_inserts_annotations_and_avoids_duplicate_package():
    original = load_input()
    answer = (
        "\\documentclass{article}\n\\usepackage[dvipsnames]{xcolor}\n"
        "\\begin{document}\nx = 4\n\\end{document}\n"
    )
    grading_input = original.model_copy(
        update={"submission": original.submission.model_copy(update={"answer": answer})}
    )
    report = workflow(
        FakeLLM([assessment_json("analyst"), assessment_json("verifier"), feedback_json()])
    ).execute(original)
    tex = annotated_latex(grading_input, report)
    assert tex.count("xcolor") == 1
    assert tex.index("TA annotations") < tex.index(r"\end{document}")
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
