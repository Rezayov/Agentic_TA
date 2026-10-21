import json
from pathlib import Path

from homework_ta.interfaces import batch_cli, cli


def inputs(tmp_path):
    assignment = tmp_path / "assignment.json"
    assignment.write_text("{}")
    references = tmp_path / "references.sqlite3"
    references.write_bytes(b"placeholder")
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    for student in ("123_name", "456"):
        (submissions / f"{student}.tex").write_text("Original answer")
    return [
        str(assignment),
        str(submissions),
        "--reference-db",
        str(references),
        "--output-dir",
        str(tmp_path / "outputs"),
    ]


def test_dry_run_has_no_writes_or_calls(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    before = set(tmp_path.rglob("*"))
    monkeypatch.setattr(
        batch_cli.prepare_cli,
        "main",
        lambda args: (_ for _ in ()).throw(AssertionError("unexpected preparation")),
    )
    assert batch_cli.main([*args, "--dry-run"]) == 0
    assert set(tmp_path.rglob("*")) == before


def test_batch_continues_after_failure_and_saves_review_status(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    originals = {p: p.read_bytes() for p in (tmp_path / "submissions").glob("*.tex")}
    calls = []
    monkeypatch.setattr(batch_cli.prepare_cli, "main", lambda args: 0)

    def grade(argv):
        calls.append(argv)
        student = Path(argv[0]).stem
        if student == "123":
            return 1
        audit = Path(argv[argv.index("--output") + 1])
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text(json.dumps({"reconciliation": {"status": "human_review"}}))
        assert "--original-answer" in argv
        return 0

    monkeypatch.setattr(batch_cli.cli, "main", grade)
    assert batch_cli.main(args) == 1
    assert len(calls) == 2
    summary = next((tmp_path / "outputs/_batch").glob("*.json"))
    assert [r["status"] for r in json.loads(summary.read_text())["results"]] == [
        "failed",
        "human_review",
    ]
    assert all(p.read_bytes() == raw for p, raw in originals.items())


def test_duplicate_student_folders_fail_before_calls(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    (tmp_path / "submissions/123_other.tex").write_text("Another original")
    monkeypatch.setattr(
        batch_cli.prepare_cli,
        "main",
        lambda args: (_ for _ in ()).throw(AssertionError("must preflight first")),
    )
    assert batch_cli.main(args) == 1
    assert not (tmp_path / "outputs").exists()


def test_skip_existing_requires_both_files(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    folder = tmp_path / "outputs/123"
    folder.mkdir(parents=True)
    (folder / "123_notes.md").write_text("existing notes")
    (folder / "123_checked.tex").write_text("existing checked")
    called = []
    monkeypatch.setattr(batch_cli.prepare_cli, "main", lambda args: called.append(args) or 1)
    assert batch_cli.main([*args, "--skip-existing"]) == 1
    assert len(called) == 1
    assert "456" in called[0]


def test_default_output_root_does_not_depend_on_current_directory(tmp_path, monkeypatch):
    expected = cli._default_output_dir()
    monkeypatch.chdir(tmp_path)
    assert cli._default_output_dir() == expected
    assert (
        batch_cli.build_parser().parse_args(["a", "b", "--reference-db", "c"]).output_dir
        == expected
    )
