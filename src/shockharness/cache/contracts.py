"""The cached result of the property-contracts phase (``contracts.json``).

The phase is cross-file: its findings depend on every analyzed file and on the project
files its indexes probed or read outside them. The entry keeps the findings with the
log of those probes and reads; ``cache/store.py`` matches the key, and the caller
reuses the findings only when ``contracts.disk.unchanged`` holds for the log.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shockharness.cache.codec import CacheEntryError, from_plain, to_plain
from shockharness.findings import Finding

FINDINGS = "findings"
PROBES = "probes"
READS = "reads"
FINDINGS_HINT = tuple[tuple[str, tuple[Finding, ...]], ...]


@dataclass(frozen=True)
class ContractsResult:
    findings: tuple[tuple[str, tuple[Finding, ...]], ...]  # (path, its findings), sorted
    probes: Mapping[str, bool]  # path -> it was a file
    reads: Mapping[str, str]  # path -> the digest of its text ("" when unreadable)


def encode_contracts(result: ContractsResult) -> dict[str, Any]:
    return {
        FINDINGS: to_plain(result.findings),
        PROBES: dict(sorted(result.probes.items())),
        READS: dict(sorted(result.reads.items())),
    }


def _mapping(data: Any, value_type: type, where: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CacheEntryError(f"{where}: expected an object")
    for key, value in data.items():
        if not isinstance(key, str) or type(value) is not value_type:
            raise CacheEntryError(f"{where}: expected {value_type.__name__} values")
    return dict(data)


def decode_contracts(plain: Any) -> ContractsResult:
    if not isinstance(plain, dict) or set(plain) != {FINDINGS, PROBES, READS}:
        raise CacheEntryError("contracts: expected findings, probes and reads")
    return ContractsResult(
        findings=from_plain(FINDINGS_HINT, plain[FINDINGS], "contracts.findings"),
        probes=_mapping(plain[PROBES], bool, "contracts.probes"),
        reads=_mapping(plain[READS], str, "contracts.reads"),
    )
