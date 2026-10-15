"""Score candidate solutions of the ShockHarness skill evaluation corpus.

Each task under ``evals/tasks/<task>/`` has a ``task.md`` prompt, a ``start/`` file set,
the task's own ``tests/`` and an ``expected.json``; ``reference/`` is one solution that
scores clean. A *candidate* is a directory with the same layout as ``start/`` after an
agent (or a person) worked on it. This script does not run agents; it scores their
output. For every (task, candidate) pair it

1. copies the candidate and the task's tests into a fresh workspace,
2. runs ``shockharness check . --format json`` there and counts the findings that are
   not suppressed (rule violations) by rule ID,
3. runs the task's tests (``python -m unittest`` or ``node --test``) and records the
   exit code (behavioral regressions),
4. counts the inline suppressions the candidate added relative to ``start/``,

and writes one JSON scorecard. A task *passes* when the gate exited 0, the tests passed,
the unsuppressed findings do not exceed ``expected.json``'s ``max_findings`` and the
suppressions added do not exceed ``max_suppressions_added``. Exit 0 when every scored
task passes, 1 otherwise. Standard library only; ``shockharness`` must be importable by
the interpreter given with ``--python`` (default: the one running this script).

    python evals/run_evals.py --reference [--output scorecard.json]
    python evals/run_evals.py --candidates DIR [--output scorecard.json]   # DIR/<task>/ per task
    python evals/run_evals.py --task evals/tasks/py-01-http-settings --candidate DIR
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

EXIT_PASS = 0
EXIT_FAIL = 1
SCORECARD_SCHEMA = "shockharness-evals/1"
# The one numeric constant this script needs; MAGIC001 is disabled for this file by a
# declared override in the repository's .shockharness.toml (the script is stdlib-only
# on purpose and therefore cannot import shockharness.constants).
JSON_INDENT = 2
SUPPRESSION = re.compile(r"shockharness:\s*ignore\[")
SOURCE_SUFFIXES = (".py", ".js", ".mjs", ".cjs")
LANGUAGE_PYTHON = "python"
LANGUAGE_JAVASCRIPT = "javascript"
TESTS_DIRNAME = "tests"
COPY_IGNORE = ("__pycache__", "node_modules", ".git", ".pytest_cache")


@dataclass(frozen=True)
class Expected:
    language: str
    max_findings: int
    max_suppressions_added: int
    tests_must_pass: bool


@dataclass(frozen=True)
class Completed:
    exit_code: int
    stdout: str
    stderr: str


def run(command: Sequence[str], cwd: Path, env: dict[str, str]) -> Completed:
    completed = subprocess.run(
        list(command), cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    return Completed(completed.returncode, completed.stdout, completed.stderr)


def load_expected(task_dir: Path) -> Expected:
    document = json.loads((task_dir / "expected.json").read_text(encoding="utf-8"))
    language = document["language"]
    if language not in (LANGUAGE_PYTHON, LANGUAGE_JAVASCRIPT):
        raise SystemExit(f"{task_dir}: unsupported language {language!r} in expected.json")
    return Expected(
        language=language,
        max_findings=int(document["max_findings"]),
        max_suppressions_added=int(document["max_suppressions_added"]),
        tests_must_pass=bool(document["tests_must_pass"]),
    )


def count_suppressions(directory: Path) -> int:
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            total += len(SUPPRESSION.findall(path.read_text(encoding="utf-8")))
    return total


def tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip() != ""]
    if len(lines) == 0:
        return "(no output)"
    return lines[len(lines) - 1]


def analyze(workspace: Path, python: str, env: dict[str, str]) -> dict[str, object]:
    completed = run(
        [python, "-m", "shockharness", "check", ".", "--format", "json"], workspace, env
    )
    result: dict[str, object] = {
        "exit_code": completed.exit_code,
        "findings": None,
        "suppressed": None,
        "unsuppressed_findings": None,
        "by_rule": {},
        "detail": "",
    }
    if completed.exit_code not in (EXIT_PASS, EXIT_FAIL):
        # Exit 2 (configuration) or 3 (tool failure): there is no report to read.
        result["detail"] = tail(completed.stderr + completed.stdout)
        return result
    report = json.loads(completed.stdout)
    summary = report["execution_summary"]
    by_rule: dict[str, int] = {}
    for finding in report["findings"]:
        if finding["suppression"] is not None:
            continue
        rule_id = finding["rule_id"]
        if rule_id not in by_rule:
            by_rule[rule_id] = 0
        by_rule[rule_id] += 1
    result["findings"] = summary["findings"]
    result["suppressed"] = summary["suppressed"]
    result["unsuppressed_findings"] = summary["findings"] - summary["suppressed"]
    result["by_rule"] = by_rule
    result["detail"] = report["gate"]["status"]
    return result


def run_tests(
    workspace: Path, expected: Expected, python: str, node: str | None, env: dict[str, str]
) -> dict[str, object]:
    if expected.language == LANGUAGE_PYTHON:
        test_env = dict(env)
        test_env["PYTHONPATH"] = str(workspace / "src")
        completed = run(
            [python, "-m", "unittest", "discover", "-s", TESTS_DIRNAME],
            workspace,
            test_env,
        )
        return {
            "runner": "unittest",
            "exit_code": completed.exit_code,
            "detail": tail(completed.stderr),
        }
    if node is None:
        return {"runner": "node --test", "exit_code": None, "detail": "node executable not found"}
    test_files = sorted(str(path) for path in (workspace / TESTS_DIRNAME).glob("*.test.js"))
    completed = run([node, "--test", *test_files], workspace, env)
    return {
        "runner": "node --test",
        "exit_code": completed.exit_code,
        "detail": tail(completed.stdout + completed.stderr),
    }


def score_task(
    task_dir: Path, candidate: Path, python: str, node: str | None, workspace_root: Path
) -> dict[str, object]:
    expected = load_expected(task_dir)
    workspace = workspace_root / task_dir.name
    shutil.copytree(candidate, workspace, ignore=shutil.ignore_patterns(*COPY_IGNORE))
    shutil.copytree(task_dir / TESTS_DIRNAME, workspace / TESTS_DIRNAME, dirs_exist_ok=True)
    env = dict(os.environ)

    analysis = analyze(workspace, python, env)
    tests = run_tests(workspace, expected, python, node, env)
    before = count_suppressions(task_dir / "start")
    after = count_suppressions(candidate)
    suppressions = {"start": before, "candidate": after, "added": after - before}

    reasons: list[str] = []
    if analysis["exit_code"] != EXIT_PASS:
        reasons.append(f"analyzer exit {analysis['exit_code']}: {analysis['detail']}")
    unsuppressed = analysis["unsuppressed_findings"]
    if unsuppressed is not None and unsuppressed > expected.max_findings:
        reasons.append(
            f"{unsuppressed} unsuppressed finding(s) > max_findings {expected.max_findings}"
        )
    if expected.tests_must_pass and tests["exit_code"] != EXIT_PASS:
        reasons.append(f"tests exit {tests['exit_code']}: {tests['detail']}")
    if suppressions["added"] > expected.max_suppressions_added:
        reasons.append(
            f"{suppressions['added']} suppression(s) added > max_suppressions_added "
            f"{expected.max_suppressions_added}"
        )
    return {
        "task": task_dir.name,
        "language": expected.language,
        "candidate": str(candidate),
        "expected": {
            "max_findings": expected.max_findings,
            "max_suppressions_added": expected.max_suppressions_added,
            "tests_must_pass": expected.tests_must_pass,
        },
        "analyzer": analysis,
        "tests": tests,
        "suppressions": suppressions,
        "passed": len(reasons) == 0,
        "reasons": reasons,
    }


def task_dirs(tasks_root: Path) -> list[Path]:
    found = sorted(path for path in tasks_root.iterdir() if (path / "expected.json").is_file())
    if len(found) == 0:
        raise SystemExit(f"no tasks (directories with expected.json) under {tasks_root}")
    return found


def pairs(args: argparse.Namespace) -> list[tuple[Path, Path]]:
    if args.task is not None:
        return [(args.task.resolve(), args.candidate.resolve())]
    selected = task_dirs(args.tasks.resolve())
    if args.reference:
        return [(task, task / "reference") for task in selected]
    result: list[tuple[Path, Path]] = []
    for task in selected:
        candidate = args.candidates.resolve() / task.name
        if not candidate.is_dir():
            raise SystemExit(f"no candidate for task {task.name}: {candidate} is not a directory")
        result.append((task, candidate))
    return result


def render_line(scored: dict[str, object]) -> str:
    verdict = "PASS" if scored["passed"] else "FAIL"
    analyzer = scored["analyzer"]
    tests = scored["tests"]
    suppressions = scored["suppressions"]
    line = (
        f"{scored['task']}: {verdict}; analyzer exit {analyzer['exit_code']}, "
        f"unsuppressed findings {analyzer['unsuppressed_findings']}; tests exit "
        f"{tests['exit_code']}; suppressions added {suppressions['added']}"
    )
    if not scored["passed"]:
        line += "; " + "; ".join(scored["reasons"])
    return line


def main(argv: Sequence[str]) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--tasks", type=Path, default=here / "tasks", help="directory of task directories"
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--reference", action="store_true", help="score every task's reference solution"
    )
    selection.add_argument(
        "--candidates", type=Path, default=None, help="directory holding one <task>/ per task"
    )
    selection.add_argument("--task", type=Path, default=None, help="score one task directory")
    parser.add_argument(
        "--candidate", type=Path, default=None, help="the candidate directory for --task"
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter that has shockharness installed (runs the analyzer and Python tests)",
    )
    parser.add_argument(
        "--node", default=shutil.which("node"), help="node executable for JavaScript tests"
    )
    parser.add_argument("--output", type=Path, default=None, help="write the scorecard here")
    parser.add_argument("--keep", action="store_true", help="keep the workspaces for inspection")
    args = parser.parse_args(list(argv))
    if (args.task is None) != (args.candidate is None):
        parser.error("--task and --candidate must be given together")

    workspace_root = Path(tempfile.mkdtemp(prefix="shockharness-evals-"))
    scored = [
        score_task(task, candidate, args.python, args.node, workspace_root)
        for task, candidate in pairs(args)
    ]
    for item in scored:
        print(render_line(item))
    passed = sum(1 for item in scored if item["passed"])
    scorecard = {
        "schema": SCORECARD_SCHEMA,
        "python": args.python,
        "node": args.node,
        "tasks": scored,
        "summary": {
            "tasks": len(scored),
            "passed": passed,
            "failed": len(scored) - passed,
            "unsuppressed_findings": sum(
                item["analyzer"]["unsuppressed_findings"]
                for item in scored
                if item["analyzer"]["unsuppressed_findings"] is not None
            ),
            "test_failures": sum(1 for item in scored if item["tests"]["exit_code"] != EXIT_PASS),
            "suppressions_added": sum(item["suppressions"]["added"] for item in scored),
        },
    }
    rendered = json.dumps(scorecard, indent=JSON_INDENT, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"scorecard written to {args.output}")
    summary = scorecard["summary"]
    print(
        f"evals: {summary['tasks']} task(s), {summary['passed']} passed, "
        f"{summary['failed']} failed, {summary['unsuppressed_findings']} unsuppressed "
        f"finding(s), {summary['suppressions_added']} suppression(s) added"
    )
    if args.keep:
        print(f"workspaces kept: {workspace_root}")
    else:
        shutil.rmtree(workspace_root)
    return EXIT_PASS if summary["failed"] == 0 else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
