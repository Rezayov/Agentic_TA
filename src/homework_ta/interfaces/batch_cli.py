"""Run one assignment for every TeX submission, sequentially and non-destructively."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from homework_ta.interfaces import cli, prepare_cli
from homework_ta.interfaces.report_artifacts import student_folder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assignment", type=Path)
    parser.add_argument("submissions", type=Path, help="directory containing original .tex answers")
    parser.add_argument("--reference-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=cli._default_output_dir())
    parser.add_argument("--router-config", type=Path)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="skip students whose notes and checked TeX already exist",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="preview only; no writes or API calls"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        assignment = args.assignment.resolve(strict=True)
        submissions = args.submissions.resolve(strict=True)
        reference_db = args.reference_db.resolve(strict=True)
        root = args.output_dir.resolve()
        sources = sorted(submissions.glob("*.tex"))
        if not sources:
            raise ValueError("no .tex submissions found")
        plans = []
        used_folders = set()
        for source in sources:
            folder = student_folder(root, source.stem)
            if folder in used_folders:
                raise ValueError(f"multiple submissions map to student folder {folder.name}")
            used_folders.add(folder)
            paths = (folder / f"{folder.name}_notes.md", folder / f"{folder.name}_checked.tex")
            if any(
                path.resolve() in {source.resolve(), assignment, reference_db} for path in paths
            ):
                raise ValueError("output would overwrite original data")
            complete = all(path.is_file() and path.stat().st_size > 0 for path in paths)
            plans.append((source, folder, args.skip_existing and complete))
        for source, folder, skip in plans:
            print(f"{'SKIP' if skip else 'GRADE'} {source.name} -> {folder}", flush=True)
        if args.dry_run:
            print(f"Preview: {len(plans)} students; no files written or requests sent.", flush=True)
            return 0
        run_name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        work = assignment.parent / "work" / f"batch-{run_name}"
        results = []
        print(f"Batch work/log directory: {work}", flush=True)
        for number, (source, folder, skip) in enumerate(plans, start=1):
            started = monotonic()
            print(
                f"\n[{number}/{len(plans)}] Student {folder.name}: "
                f"{'skipping existing outputs' if skip else 'preparing original answer'}",
                flush=True,
            )
            if skip:
                results.append({"student": folder.name, "status": "skipped_existing"})
                continue
            prepared = work / f"{folder.name}.json"
            audit = work / f"{folder.name}-report.json"
            code = prepare_cli.main(
                [
                    str(assignment),
                    str(source),
                    "--submission-id",
                    folder.name,
                    "--output",
                    str(prepared),
                ]
            )
            if code == 0:
                grading_args = [
                    str(prepared),
                    "--original-answer",
                    str(source),
                    "--reference-db",
                    str(reference_db),
                    "--output-dir",
                    str(root),
                    "--output",
                    str(audit),
                    "--log-file",
                    str(work / f"{folder.name}.jsonl"),
                ]
                if args.router_config:
                    grading_args.extend(["--router-config", str(args.router_config)])
                print(
                    f"[{number}/{len(plans)}] Student {folder.name}: grading; "
                    f"log {work / (folder.name + '.jsonl')}",
                    flush=True,
                )
                code = cli.main(grading_args)
            status = "failed"
            if code == 0:
                status = json.loads(audit.read_text())["reconciliation"]["status"]
            print(
                f"[{number}/{len(plans)}] Student {folder.name}: {status} "
                f"({round(monotonic() - started)}s)",
                flush=True,
            )
            results.append(
                {
                    "student": folder.name,
                    "status": status,
                    "source": str(source),
                    "output_folder": str(folder),
                }
            )
        summary = root / "_batch" / f"{run_name}.json"
        cli._write_atomic(
            summary,
            json.dumps({"assignment": str(assignment), "results": results}, indent=2) + "\n",
        )
        failed = sum(result["status"] == "failed" for result in results)
        print(f"Finished {len(results)} students; {failed} failed. Summary: {summary}", flush=True)
        return 1 if failed else 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
