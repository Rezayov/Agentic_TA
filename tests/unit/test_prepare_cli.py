import json
from pathlib import Path

from homework_ta.domain.models import GradingInput
from homework_ta.interfaces.prepare_cli import main


def test_prepare_cli_combines_assignment_and_answer_without_modifying_sources(
    tmp_path: Path,
) -> None:
    assignment = tmp_path / "assignment.json"
    answer = tmp_path / "student.tex"
    output = tmp_path / "work" / "input.json"
    assignment_text = json.dumps(
        {
            "question_id": "q1",
            "question": "Prove the claim.",
            "rubric": {
                "title": "Proof rubric",
                "criteria": [
                    {
                        "criterion_id": "proof",
                        "description": "Provides a valid proof.",
                        "max_points": 1,
                    }
                ],
            },
            "source_material": [],
        }
    )
    answer_text = "\\begin{proof}Valid work.\\end{proof}\n"
    assignment.write_text(assignment_text, encoding="utf-8")
    answer.write_text(answer_text, encoding="utf-8")

    assert main([str(assignment), str(answer), "--output", str(output)]) == 0

    result = GradingInput.model_validate_json(output.read_text(encoding="utf-8"))
    assert result.submission.submission_id == "student"
    assert result.submission.answer == answer_text.strip()
    assert assignment.read_text(encoding="utf-8") == assignment_text
    assert answer.read_text(encoding="utf-8") == answer_text


def test_prepare_cli_refuses_to_overwrite_the_original_answer(tmp_path: Path) -> None:
    assignment = tmp_path / "assignment.json"
    answer = tmp_path / "student.tex"
    assignment.write_text("{}", encoding="utf-8")
    answer.write_text("answer", encoding="utf-8")

    assert main([str(assignment), str(answer), "--output", str(answer)]) == 1
