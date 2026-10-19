"""What the property contracts read from disk besides the analyzed files.

The contract indexes resolve a callee into a project file that may not be among the
analyzed files: they ask whether a file exists and read its text. Each answer is logged
here (a path relative to the root, never its text), so a cached result can be reused
only while every answer would be the same: each probed path still exists or is still
missing, each read file has the same text, and each unreadable one is still unreadable.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from shockharness.contracts.catalog import read_text

# The digest logged for a file that could not be read.
UNREADABLE = ""


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relative(root: Path, path: Path) -> str:
    if path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    return path.as_posix()


@dataclass
class DiskLog:
    """One run's answers: ``probes`` (path -> it was a file) and ``reads`` (path -> the
    digest of its text, ``UNREADABLE`` when it could not be read)."""

    root: Path
    probes: dict[str, bool]
    reads: dict[str, str]

    def is_file(self, path: Path) -> bool:
        found = path.is_file()
        self.probes[_relative(self.root, path)] = found
        return found

    def read_text(self, path: Path) -> tuple[str | None, str]:
        text, why = read_text(path)
        digest = UNREADABLE
        if text is not None:
            digest = text_digest(text)
        self.reads[_relative(self.root, path)] = digest
        return text, why


def new_log(root: Path) -> DiskLog:
    return DiskLog(root, {}, {})
