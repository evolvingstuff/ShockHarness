"""Exercise the consumer examples against the wheel built from this checkout.

For each example under ``examples/``: copy it into a temporary directory, make it a
git repository with one commit, create a virtual environment, install the locally
built ``shockharness`` wheel (never the PyPI release), and require

1. ``shockharness version`` to report the wheel's version,
2. the example's two analyzer pins (``pyproject.toml`` and the workflow input) to agree,
3. ``shockharness check .`` to exit 0 on the clean example,
4. after one injected violation is committed, ``shockharness check .`` and
   ``shockharness gate --base HEAD~1 --head HEAD`` to exit 1.

Standard library only. Exit 0 only when every step held; a one-line-per-step report
is printed either way. Nothing is read from the environment; everything is an
argument. Network access happens only if ``--wheelhouse`` is omitted (then pip
resolves the wheel's dependencies from its index as usual).

    python scripts/consumer_upgrade_check.py --dist dist --examples examples \\
        [--wheelhouse DIR] [--keep]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

EXIT_PASS = 0
EXIT_VIOLATIONS = 1
EXIT_FAILURE = 1

GIT_IDENTITY = (
    "-c",
    "user.name=ShockHarness upgrade check",
    "-c",
    "user.email=upgrade-check@example.invalid",
)
COPY_IGNORE = ("node_modules", ".venv", "__pycache__", ".git", ".pytest_cache", "dist")
PARENT_REVISION = "HEAD~1"

# One deliberate violation per example: a numeric literal appended to an analyzed file.
VIOLATIONS: dict[str, tuple[str, str]] = {
    "python": ("src/example_service/pages.py", "\nDEFAULT_PAGE_SIZE = 25\n"),
    "js": ("src/pages.js", "\nexport const DEFAULT_PAGE_SIZE = 25;\n"),
}
# Where each example pins the analyzer; both pins must name the same version.
PYPROJECT_PIN = re.compile(r'"shockharness==([^"]+)"')
WORKFLOW_PIN = re.compile(r'shockharness-version:\s*"([^"]+)"')
WHEEL_VERSION = re.compile(r"^shockharness-([^-]+)-py3-none-any\.whl$")


@dataclass(frozen=True)
class Step:
    example: str
    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        verdict = "ok" if self.ok else "FAILED"
        return f"{self.example}: {self.name}: {self.detail}: {verdict}"


@dataclass(frozen=True)
class Completed:
    exit_code: int
    output: str


def run(command: Sequence[str], cwd: Path) -> Completed:
    completed = subprocess.run(list(command), cwd=cwd, capture_output=True, text=True, check=False)
    return Completed(completed.returncode, completed.stdout + completed.stderr)


def git(repo: Path, *args: str) -> Completed:
    return run(["git", *GIT_IDENTITY, *args], repo)


def find_wheel(dist: Path) -> Path:
    wheels = sorted(dist.glob("shockharness-*.whl"))
    if len(wheels) != 1:
        found = ", ".join(w.name for w in wheels)
        raise SystemExit(
            f"expected exactly one shockharness wheel in {dist} (run `python -m build "
            f"--wheel` first); found: [{found}]"
        )
    return wheels[0]


def wheel_version(wheel: Path) -> str:
    match = WHEEL_VERSION.fullmatch(wheel.name)
    if match is None:
        raise SystemExit(f"cannot read a version from wheel file name {wheel.name!r}")
    return match.group(1)


def venv_python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def copy_example(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*COPY_IGNORE))


def pinned_versions(example_dir: Path) -> list[str]:
    """Every analyzer pin the example declares (pyproject.toml, workflow input)."""
    pins: list[str] = []
    pyproject = example_dir / "pyproject.toml"
    if pyproject.is_file():
        pins.extend(PYPROJECT_PIN.findall(pyproject.read_text(encoding="utf-8")))
    workflows = example_dir / ".github" / "workflows"
    if workflows.is_dir():
        for workflow in sorted(workflows.glob("*.yml")):
            pins.extend(WORKFLOW_PIN.findall(workflow.read_text(encoding="utf-8")))
    return pins


def introduce_violation(repo: Path, example_name: str) -> Path:
    relative, text = VIOLATIONS[example_name]
    target = repo / relative
    target.write_text(target.read_text(encoding="utf-8") + text, encoding="utf-8")
    return target


def tail(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip() != ""]
    if len(lines) == 0:
        return "(no output)"
    return lines[len(lines) - 1]


def shockharness(python: Path, repo: Path, *args: str) -> Completed:
    return run([str(python), "-m", "shockharness", *args], repo)


def check_example(
    example_dir: Path, wheel: Path, wheelhouse: Path | None, workspace: Path
) -> list[Step]:
    name = example_dir.name
    steps: list[Step] = []
    repo = workspace / name
    copy_example(example_dir, repo)

    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "clean")):
        result = git(repo, *args)
        if result.exit_code != 0:
            steps.append(Step(name, "git " + args[0], False, tail(result.output)))
            return steps
    steps.append(Step(name, "git init + commit", True, "clean example committed"))

    env_dir = workspace / f"venv-{name}"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    python = venv_python(env_dir)
    install = [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    if wheelhouse is not None:
        install.extend(["--no-index", "--find-links", str(wheelhouse)])
    install.append(str(wheel))
    result = run(install, repo)
    steps.append(Step(name, "install wheel", result.exit_code == 0, tail(result.output)))
    if result.exit_code != 0:
        return steps

    expected_version = wheel_version(wheel)
    result = shockharness(python, repo, "version")
    reported = result.output.strip()
    steps.append(
        Step(
            name,
            "shockharness version",
            reported == f"shockharness {expected_version}",
            f"{reported} (wheel {expected_version})",
        )
    )

    pins = pinned_versions(example_dir)
    steps.append(
        Step(
            name,
            "analyzer pins agree",
            len(pins) > 0 and len(set(pins)) == 1,
            "pins: " + ", ".join(pins),
        )
    )

    result = shockharness(python, repo, "check", ".", "--format", "text")
    steps.append(
        Step(name, "check . (clean)", result.exit_code == EXIT_PASS, f"exit {result.exit_code}")
    )

    changed = introduce_violation(repo, name)
    result = git(repo, "commit", "-q", "-a", "-m", "introduce a violation")
    if result.exit_code != 0:
        steps.append(Step(name, "git commit violation", False, tail(result.output)))
        return steps
    result = shockharness(python, repo, "check", ".", "--format", "text")
    steps.append(
        Step(
            name,
            f"check . (after violation in {changed.relative_to(repo)})",
            result.exit_code == EXIT_VIOLATIONS,
            f"exit {result.exit_code}; {tail(result.output)}",
        )
    )
    result = shockharness(python, repo, "gate", "--base", PARENT_REVISION, "--head", "HEAD")
    steps.append(
        Step(
            name,
            f"gate --base {PARENT_REVISION} --head HEAD",
            result.exit_code == EXIT_VIOLATIONS,
            f"exit {result.exit_code}; {tail(result.output)}",
        )
    )
    return steps


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dist", type=Path, required=True, help="directory holding the wheel")
    parser.add_argument(
        "--examples", type=Path, required=True, help="directory holding the example projects"
    )
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        default=None,
        help="directory of dependency wheels; when given, pip runs with --no-index",
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the temporary workspace for inspection"
    )
    args = parser.parse_args(list(argv))

    wheel = find_wheel(args.dist.resolve())
    wheelhouse: Path | None = None
    if args.wheelhouse is not None:
        wheelhouse = args.wheelhouse.resolve()
    examples = [args.examples / name for name in sorted(VIOLATIONS)]
    for example in examples:
        if not example.is_dir():
            raise SystemExit(f"example directory is missing: {example}")

    workspace = Path(tempfile.mkdtemp(prefix="shockharness-upgrade-"))
    print(f"wheel under test: {wheel}")
    print(f"workspace: {workspace}")
    steps: list[Step] = []
    for example in examples:
        steps.extend(check_example(example.resolve(), wheel, wheelhouse, workspace))
    for step in steps:
        print(step.render())
    failed = [step for step in steps if not step.ok]
    print(
        f"consumer upgrade check: {len(examples)} example(s), {len(steps)} step(s), "
        f"{len(failed)} failed"
    )
    if args.keep:
        print(f"workspace kept: {workspace}")
    else:
        shutil.rmtree(workspace)
    return EXIT_PASS if len(failed) == 0 else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
