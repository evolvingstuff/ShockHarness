"""Reusing the property-contracts phase file by file.

A file's cached findings are reused when its own text, the contract rules and scope that
apply to it, and everything its findings depended on are unchanged: every name it resolved
resolves to the same file, every JavaScript path it looked for is still there or still
missing, every module it depended on has the same text, and, when an override check ran,
the analyzed classes are the same. Every other file is computed afresh.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from shockharness.cache.contracts import FileEntry
from shockharness.contracts.catalog import probed_module_file, read_text
from shockharness.contracts.deps import Deps
from shockharness.contracts.disk import UNREADABLE, text_digest
from shockharness.contracts.report import ContractFile
from shockharness.findings import Finding
from shockharness.rules.defaults import module_names
from shockharness.source import SourceText

PYTHON = "python"


@dataclass
class Current:
    """What this run knows about the project, and the digests of files read on disk."""

    root: Path
    digests: Mapping[str, str]  # each analyzed file -> the digest of its text
    python_names: Mapping[str, str]  # each name an analyzed Python file answers to
    classes: str  # the digest of every analyzed class
    on_disk: dict[str, str]  # a file outside the analyzed ones -> its digest, read once


def current_of(root: Path, sources: Mapping[str, tuple[str, SourceText]], classes: str) -> Current:
    digests = {path: text_digest(source.text) for path, (_language, source) in sources.items()}
    names: dict[str, str] = {}
    for path, (language, _source) in sorted(sources.items()):
        if language == PYTHON:
            names.update((name, path) for name in module_names(path))
    return Current(root, digests, names, classes, {})


def _resolved(current: Current, dotted: str) -> str:
    """The file a Python name resolves to, as the contracts index resolves it."""
    if dotted in current.python_names:
        return current.python_names[dotted]
    found = probed_module_file(current.root, dotted.split("."), Path.is_file)
    if found is None:
        return ""
    return found.relative_to(current.root).as_posix()


def _exists(current: Current, path: str) -> bool:
    return path in current.digests or (current.root / path).is_file()


def content(current: Current, path: str) -> str:
    if path in current.digests:
        return current.digests[path]
    if path not in current.on_disk:
        text, _why = read_text(current.root / path)
        current.on_disk[path] = UNREADABLE
        if text is not None:
            current.on_disk[path] = text_digest(text)
    return current.on_disk[path]


def reusable(entry: FileEntry, file: ContractFile, current: Current, classes: str) -> bool:
    """Whether ``entry``, made when the classes digest was ``classes``, still holds."""
    if entry.digest != current.digests[file.path]:
        return False
    if entry.applies != tuple(sorted(file.applies)) or entry.complete != file.complete:
        return False
    if entry.classes and classes != current.classes:
        return False
    if any(_resolved(current, name) != path for name, path in entry.names):
        return False
    if any(_exists(current, path) != found for path, found in entry.probes):
        return False
    return all(content(current, path) == digest for path, digest in entry.contents)


def entry_for(
    file: ContractFile, findings: list[Finding], deps: Deps, current: Current
) -> FileEntry:
    return FileEntry(
        path=file.path,
        digest=current.digests[file.path],
        applies=tuple(sorted(file.applies)),
        complete=file.complete,
        findings=tuple(findings),
        names=tuple(sorted(deps.names.items())),
        probes=tuple(sorted(deps.probes.items())),
        contents=tuple((path, content(current, path)) for path in sorted(deps.paths)),
        classes=deps.classes,
    )
