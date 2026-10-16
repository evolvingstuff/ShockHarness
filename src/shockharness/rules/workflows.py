"""GitHub Actions workflows that run ShockHarness, read as text (H2 part 2, VERIFY003).

No YAML library is a dependency, so workflows are read line by line: the top-level
``jobs:`` key, the job keys one indentation level below it, and each job's lines up to
the next job. A job *runs ShockHarness* when any of its non-comment lines mentions
``shockharness`` (an install, a ``shockharness check`` / ``gate`` command, or the reusable
workflow ``evolvingstuff/ShockHarness/.github/workflows/check.yml``).

What :func:`workflow_loosenings` reports, comparing a base and a head version of one
workflow file:

* a job that ran ShockHarness at base and does not exist, or no longer mentions it, at
  head (a deleted workflow file loses all of its jobs);
* in a job that runs ShockHarness at both: an added ``continue-on-error: true``, an added
  ``if: false``, an added ``--exit-zero`` / ``--profile minimal`` / ``--profile
  recommended`` / ``--parse-errors warn``, and an analyzer version pin moved to an
  older version.

Limits (docs/limitations.md): flow-style YAML, anchors and aliases, and jobs defined
by matrix expansion are not interpreted; a job renamed in the same change looks like a
removed job plus a new one.
"""

import re
from dataclasses import dataclass

WORKFLOW_DIRECTORY = ".github/workflows"
WORKFLOW_SUFFIXES = (".yml", ".yaml")
MARKER = "shockharness"
JOBS_KEY = re.compile(r"jobs\s*:\s*(#.*)?$")
KEY_LINE = re.compile(r"(?P<indent>[ ]+)(?P<name>[A-Za-z0-9_.-]+)\s*:\s*(#.*)?$")
CONTINUE_ON_ERROR = re.compile(r"continue-on-error\s*:\s*(true|\$\{\{\s*true\s*\}\})", re.I)
DISABLED_IF = re.compile(r"\bif\s*:\s*(false|\$\{\{\s*false\s*\}\})", re.I)
FLAGS = (
    ("--exit-zero", re.compile(r"--exit-zero\b")),
    ("--profile minimal", re.compile(r"--profile[= ]\s*['\"]?minimal\b")),
    ("--profile recommended", re.compile(r"--profile[= ]\s*['\"]?recommended\b")),
    ("--parse-errors warn", re.compile(r"--parse-errors[= ]\s*['\"]?warn\b")),
)
PINS = (
    re.compile(r"shockharness==(?P<version>[0-9][0-9A-Za-z.]*)", re.I),
    re.compile(r"shockharness-version\s*:\s*['\"]?(?P<version>[0-9][0-9A-Za-z.]*)", re.I),
)
VERSION_PART = re.compile(r"\d+")


@dataclass(frozen=True)
class Job:
    name: str
    line: int  # 1-based line of the job key
    lines: tuple[tuple[int, str], ...]  # (line number, text) of the job's own lines

    @property
    def runs_shockharness(self) -> bool:
        return any(MARKER in _code(text).lower() for _, text in self.lines)


@dataclass(frozen=True)
class WorkflowLoosening:
    item: str  # stable identity within the file: "job lint removed", "job lint: --exit-zero"
    line: int
    message: str


def _code(text: str) -> str:
    """A line without its comment (a ``#`` preceded by whitespace or at the start)."""
    stripped = text.strip()
    if stripped.startswith("#"):
        return ""
    index = text.find(" #")
    if index >= 0:
        return text[:index]
    return text


def _jobs_start(lines: list[str]) -> int | None:
    """The index of the top-level ``jobs:`` line."""
    for index, line in enumerate(lines):
        if not line.startswith((" ", "\t")) and JOBS_KEY.match(line.strip()) is not None:
            return index
    return None


def _job_key(line: str, job_indent: str | None) -> re.Match[str] | None:
    """The match when ``line`` is a job key: a key at the first indentation level seen."""
    match = KEY_LINE.match(line)
    if match is None:
        return None
    if job_indent is not None and match.group("indent") != job_indent:
        return None
    return match


def parse_jobs(text: str) -> dict[str, Job]:
    lines = text.splitlines()
    start = _jobs_start(lines)
    if start is None:
        return {}
    starts: dict[str, int] = {}
    collected: dict[str, list[tuple[int, str]]] = {}
    job_indent: str | None = None
    current: str | None = None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        blank = line.strip() == "" or line.strip().startswith("#")
        if not blank and not line.startswith((" ", "\t")):
            break  # the next top-level key ends the jobs mapping
        match = None
        if not blank:
            match = _job_key(line, job_indent)
        if match is not None:
            job_indent = match.group("indent")
            current = match.group("name")
            starts[current] = index + 1
            collected[current] = []
        if current is not None:
            collected[current].append((index + 1, line))
    return {name: Job(name, starts[name], tuple(collected[name])) for name in collected}


def _matching_lines(job: Job, pattern: re.Pattern[str]) -> list[int]:
    return [number for number, text in job.lines if pattern.search(_code(text)) is not None]


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in VERSION_PART.findall(version))


def _pins(job: Job) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, text in job.lines:
        for pattern in PINS:
            for match in pattern.finditer(_code(text)):
                found.append((number, match.group("version")))
    return found


def _added_occurrences(base: Job, head: Job, pattern: re.Pattern[str]) -> list[int]:
    """Head lines matching ``pattern`` beyond the number of base lines that match."""
    base_count = len(_matching_lines(base, pattern))
    head_lines = _matching_lines(head, pattern)
    return head_lines[base_count:]


def _removed(name: str, after: Job | None, head_text: str | None) -> WorkflowLoosening | None:
    """A job that ran ShockHarness at base and is gone, or no longer runs it, at head."""
    if after is None:
        where = "the workflow file was deleted" if head_text is None else "the job was removed"
        return WorkflowLoosening(
            f"job {name} removed", 1, f"job {name!r} ran ShockHarness at base; {where}"
        )
    if not after.runs_shockharness:
        return WorkflowLoosening(
            f"job {name} no longer runs shockharness",
            after.line,
            f"job {name!r} ran ShockHarness at base and no longer does",
        )
    return None


def _added_settings(name: str, before: Job, after: Job) -> list[WorkflowLoosening]:
    found = [
        WorkflowLoosening(
            f"job {name}: continue-on-error",
            line,
            f"continue-on-error: true added to job {name!r}, which runs ShockHarness: a "
            "failing gate no longer fails the workflow",
        )
        for line in _added_occurrences(before, after, CONTINUE_ON_ERROR)
    ]
    found.extend(
        WorkflowLoosening(
            f"job {name}: if false",
            line,
            f"a condition that is always false was added to job {name!r}, which runs "
            "ShockHarness: the step or job no longer runs",
        )
        for line in _added_occurrences(before, after, DISABLED_IF)
    )
    for label, pattern in FLAGS:
        found.extend(
            WorkflowLoosening(
                f"job {name}: {label}",
                line,
                f"{label} added to a ShockHarness invocation in job {name!r}",
            )
            for line in _added_occurrences(before, after, pattern)
        )
    return found


def _pin_downgrades(name: str, before: Job, after: Job) -> list[WorkflowLoosening]:
    base_versions = [version for _, version in _pins(before)]
    if len(base_versions) == 0:
        return []
    newest = max(base_versions, key=_version_key)
    return [
        WorkflowLoosening(
            f"job {name}: pin {version}",
            line,
            f"the ShockHarness version pin in job {name!r} moved from {newest} "
            f"to the older {version}",
        )
        for line, version in _pins(after)
        if version not in base_versions and _version_key(version) < _version_key(newest)
    ]


def workflow_loosenings(base_text: str | None, head_text: str | None) -> list[WorkflowLoosening]:
    """What got looser in one workflow file; ``None`` for a side where it does not exist."""
    base_jobs: dict[str, Job] = {}
    if base_text is not None:
        base_jobs = parse_jobs(base_text)
    head_jobs: dict[str, Job] = {}
    if head_text is not None:
        head_jobs = parse_jobs(head_text)
    found: list[WorkflowLoosening] = []
    for name in sorted(base_jobs):
        before = base_jobs[name]
        if not before.runs_shockharness:
            continue
        after: Job | None = None
        if name in head_jobs:
            after = head_jobs[name]
        removed = _removed(name, after, head_text)
        if removed is not None:
            found.append(removed)
            continue
        assert after is not None
        found.extend(_added_settings(name, before, after))
        found.extend(_pin_downgrades(name, before, after))
    return found
