"""The only place ShockHarness runs ``git``.

Every call is local (no remote is ever contacted) and every failure is returned
as data: a :class:`GitResult` with ``ok = False`` and a reason. Callers decide
what a failure means (a usage error for ``diff``/``gate``, an explicit
``unavailable`` status for history metrics). The three ``try`` blocks here are
the declared git boundaries in ``.shockharness.toml``.
"""

import io
import subprocess
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shockharness.constants import GIT_CHANGE_RECORD_TOKENS, GIT_RENAME_RECORD_TOKENS

GIT = "git"
RECORD_SEPARATOR = "\x1e"
FIELD_SEPARATOR = "\x1f"


@dataclass(frozen=True)
class GitResult:
    ok: bool
    stdout: bytes
    error: str | None


def run_git(cwd: Path, args: Sequence[str]) -> GitResult:
    """Run one git command in ``cwd``; never raises for git or OS failures."""
    command = [GIT, "-c", "core.quotePath=false", *args]
    directory = str(cwd)
    # Boundary (declared in .shockharness.toml): the git subprocess. A non-zero exit
    # (not a repository, unknown revision) and an absent git binary both become data.
    try:
        completed = subprocess.run(command, cwd=directory, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        return GitResult(False, b"", f"git {args[0]} failed (exit {exc.returncode}): {stderr}")
    except OSError as exc:
        return GitResult(False, b"", f"git could not be run: {exc}")
    return GitResult(True, completed.stdout, None)


def decode_output(result: GitResult, what: str) -> tuple[str | None, str | None]:
    """Decode ``result.stdout`` as UTF-8. Returns (text, error); exactly one is set."""
    # Boundary (declared in .shockharness.toml): git output is external bytes.
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"git {what} output is not valid UTF-8: {exc}"
    return text, None


def run_git_text(cwd: Path, args: Sequence[str]) -> tuple[str | None, str | None]:
    """Run git and decode its output. Returns (text, error); exactly one is set."""
    result = run_git(cwd, args)
    if not result.ok:
        return None, result.error
    return decode_output(result, args[0])


@dataclass(frozen=True)
class RepositoryLocation:
    toplevel: Path
    prefix: str  # root relative to toplevel, "" or "a/b/" (trailing slash as git prints it)


def locate_repository(root: Path) -> tuple[RepositoryLocation | None, str | None]:
    text, error = run_git_text(root, ["rev-parse", "--show-toplevel", "--show-prefix"])
    if text is None:
        return None, error
    lines = text.splitlines()
    if len(lines) == 0:
        return None, "git rev-parse printed nothing"
    toplevel = Path(lines[0])
    prefix = lines[1] if len(lines) > 1 else ""
    return RepositoryLocation(toplevel=toplevel, prefix=prefix), None


RENAME_STATUS_PREFIX = "R"
COPY_STATUS_PREFIX = "C"
NUL = "\0"


def renamed_files(
    location: RepositoryLocation, base: str, head: str
) -> tuple[dict[str, str] | None, str | None]:
    """Files git considers renamed between two commits, as root-relative POSIX paths
    ``{head path: base path}`` (H2: VERIFY rules follow a renamed file to its base
    version). Returns (renames, error); exactly one is set. Only files under the
    analysis root (``location.prefix``) are reported."""
    pathspec = location.prefix if location.prefix != "" else "."
    text, error = run_git_text(
        location.toplevel,
        ["diff", "-M", "--name-status", "-z", base, head, "--", pathspec],
    )
    if text is None:
        return None, error
    tokens = [token for token in text.split(NUL) if token != ""]
    renames: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        status = tokens[index]
        if not status.startswith((RENAME_STATUS_PREFIX, COPY_STATUS_PREFIX)):
            index += GIT_CHANGE_RECORD_TOKENS
            continue
        _, old, new = tokens[index : index + GIT_RENAME_RECORD_TOKENS]
        index += GIT_RENAME_RECORD_TOKENS
        if not status.startswith(RENAME_STATUS_PREFIX):
            continue
        if old.startswith(location.prefix) and new.startswith(location.prefix):
            renames[new[len(location.prefix) :]] = old[len(location.prefix) :]
    return renames, None


def resolve_commit(root: Path, ref: str) -> tuple[str | None, str | None]:
    """The full commit hash ``ref`` names, or an error."""
    text, error = run_git_text(
        root, ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"]
    )
    if text is None:
        return None, error
    return text.strip(), None


def canonical_iso(text: str) -> str:
    """Normalize a git strict-ISO date to one spelling regardless of git version.

    Git 2.45 and later print UTC as ``Z`` (``2026-01-01T12:00:00Z``); earlier
    versions print ``+00:00``. Reports must not depend on the host's git, so every
    date is parsed and re-emitted with an explicit numeric offset.
    """
    return datetime.fromisoformat(text.strip()).isoformat()


def commit_date(root: Path, commit: str) -> tuple[str | None, str | None]:
    """The committer date of ``commit`` in canonical ISO 8601, or an error."""
    text, error = run_git_text(root, ["log", "-1", "--format=%cI", "--end-of-options", commit])
    if text is None:
        return None, error
    return canonical_iso(text), None


def export_tree(toplevel: Path, commit: str, destination: Path) -> str | None:
    """Extract the whole tree at ``commit`` into ``destination``. Returns an error or None."""
    result = run_git(toplevel, ["archive", "--format=tar", "--end-of-options", commit])
    if not result.ok:
        return result.error
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        if hasattr(tarfile, "data_filter"):
            archive.extractall(destination, filter=tarfile.data_filter)
        else:
            archive.extractall(destination)
    return None


@dataclass(frozen=True)
class Commit:
    sha: str
    committer_date: str
    author_date: str
    author: str
    paths: tuple[str, ...]  # root-relative POSIX paths of files the commit touched under root


def parse_log(text: str, prefix: str) -> list[Commit]:
    commits: list[Commit] = []
    for record in text.split(RECORD_SEPARATOR):
        if record.strip() == "":
            continue
        lines = record.split("\n")
        sha, committer_date, author_date, author = lines[0].split(FIELD_SEPARATOR)
        paths: list[str] = []
        for line in lines[1:]:
            if line == "":
                continue
            if not line.startswith(prefix):
                continue
            paths.append(line[len(prefix) :])
        commits.append(
            Commit(
                sha=sha,
                committer_date=canonical_iso(committer_date),
                author_date=canonical_iso(author_date),
                author=author,
                paths=tuple(sorted(set(paths))),
            )
        )
    return commits


def log_since(
    root: Path, commit: str, since: datetime, prefix: str
) -> tuple[list[Commit] | None, str | None]:
    """Commits reachable from ``commit`` that touch files under ``root`` and are not older
    than ``since`` (committer date). Renames are not followed (``--no-renames``); merge
    commits list no files and so count for nothing."""
    text, error = run_git_text(
        root,
        [
            "log",
            "--no-renames",
            f"--since={since.isoformat()}",
            f"--format={RECORD_SEPARATOR}%H{FIELD_SEPARATOR}%cI{FIELD_SEPARATOR}%aI"
            f"{FIELD_SEPARATOR}%aE",
            "--name-only",
            "--end-of-options",
            commit,
            "--",
            ".",
        ],
    )
    if text is None:
        return None, error
    kept = [c for c in parse_log(text, prefix) if datetime.fromisoformat(c.committer_date) >= since]
    return kept, None
