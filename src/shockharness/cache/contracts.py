"""The cached result of the property-contracts phase (``contracts.json``), per file.

The phase is cross-file: a file's findings depend on the modules its calls resolved into,
on files the indexes looked for, and, for an override check, on every analyzed class.
Each file's entry keeps its findings with those dependencies (``contracts/deps.py``);
``analysis.py`` reuses an entry only while every one of them is unchanged, and computes
the other files afresh.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shockharness.cache.codec import CacheEntryError, from_plain, to_plain
from shockharness.findings import Finding


@dataclass(frozen=True)
class FileEntry:
    path: str
    digest: str  # of the file's text
    applies: tuple[str, ...]  # the contract rules that apply to it
    complete: bool  # under enforcement = "complete" or complete_paths
    findings: tuple[Finding, ...]
    names: tuple[tuple[str, str], ...]  # a Python name -> the file it resolved to, or ""
    probes: tuple[tuple[str, bool], ...]  # a JavaScript path -> whether it was a file
    contents: tuple[tuple[str, str], ...]  # a module it depends on -> the digest of its text
    classes: bool  # depends on every analyzed class (an override check ran)


@dataclass(frozen=True)
class ContractsResult:
    classes: str  # the digest of every analyzed class, when the entries were made
    files: tuple[FileEntry, ...]


def encode_contracts(result: ContractsResult) -> Any:
    return to_plain(result)


def decode_contracts(plain: Any) -> ContractsResult:
    if not isinstance(plain, dict):
        raise CacheEntryError("contracts: expected an object")
    decoded: ContractsResult = from_plain(ContractsResult, plain, "contracts")
    return decoded


def entries_by_path(result: ContractsResult) -> Mapping[str, FileEntry]:
    return {entry.path: entry for entry in result.files}
