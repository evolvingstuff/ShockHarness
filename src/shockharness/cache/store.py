"""The on-disk content-hash cache of per-file results.

Layout under the cache directory::

    CACHEDIR.TAG                 the Cache Directory Tagging convention marker
    index.json                   {schema_version, tool_version, config_digest, host}
    entries/ab/<sha256(path)>.json   one entry per analyzed file
    contracts.json               the property-contracts phase of the last run


The index header names the tool version, the effective configuration digest and
the host (interpreter and JavaScript grammar) the entries were produced with; any
difference invalidates every entry. An entry carries that header again plus the
language and the SHA-256 of the file's bytes; a lookup is a hit only when every
part of the key is equal. Writes are atomic (temporary file in the same directory,
then ``os.replace``). Nothing here raises for a cache problem: an unreadable,
corrupt or mismatched index or entry is counted, described once, and ignored, and
the file is analyzed afresh. Nothing read from the cache is ever executed.

Cross-file work is recomputed on every run, with one exception: the property-contracts
phase, whose findings are reused when the header, every analyzed file (path, language,
text, rules applied) and every other file the phase probed or read are unchanged
(``contracts.json``; the caller checks the files on disk).
"""

import hashlib
import json
import os
import platform
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.cache.codec import CacheEntryError
from shockharness.config import CACHE_KEY, EffectiveConfig
from shockharness.constants import CACHE_SCHEMA_VERSION, CACHE_SHARD_CHARS
from shockharness.ir.javascript import PARSER_NAME as JAVASCRIPT_PARSER
from shockharness.version import __version__

INDEX_FILENAME = "index.json"
CONTRACTS_FILENAME = "contracts.json"
# coverage.cache.contracts: what the property-contracts phase did with its entry.
CONTRACTS_OFF = "off"  # the phase did not run (the family is off, or no file applies)
CONTRACTS_HIT = "hit"
CONTRACTS_MISS = "miss"  # no entry, another key, or an entry that could not be read
CONTRACTS_STALE = "stale"  # the key matched; a file the phase read or probed has changed
ENTRIES_DIRNAME = "entries"
TAG_FILENAME = "CACHEDIR.TAG"
TAG_CONTENT = (
    "Signature: 8a477f597d28d172789f06886806bc55\n"
    "# This directory is a ShockHarness cache (per-file analysis results).\n"
    "# It can be deleted at any time; see docs/configuration.md, Cache.\n"
)
STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"
STATUS_BYPASSED = "bypassed"
HEADER_KEYS = ("schema_version", "tool_version", "config_digest", "host")
ENTRY_KEYS = ("schema_version", "tool_version", "config_digest", "host", "language", "content")
REASON_ENABLED = "per-file results are read from and written to the cache directory"
REASON_DISABLED = "cache.enabled = false"
REASON_NO_CACHE_FLAG = "--no-cache"
REASON_NO_ROOT = "an in-memory source has no analysis root"
REASON_REVISION = "revision exports are always analyzed afresh"
REASON_BASELINE = "baseline create never reads the cache"


def host_label() -> str:
    """The interpreter and grammar the parse facts depend on; part of every key."""
    return f"{platform.python_implementation()} {platform.python_version()}; {JAVASCRIPT_PARSER}"


def cache_directory(root: Path, config: EffectiveConfig) -> Path:
    """The configured cache directory, resolved against the analysis root."""
    configured = Path(str(config.values[CACHE_KEY]["directory"]))
    if configured.is_absolute():
        return configured
    return root / configured


def cache_coverage_without_cache(status: str, directory: str, reason: str) -> dict[str, Any]:
    """The ``coverage.cache`` block of a run that did not open the cache."""
    return {
        "status": status,
        "directory": directory,
        "reason": reason,
        "hits": 0,
        "misses": 0,
        "invalidated": 0,
        "errors": 0,
        "problems": [],
        "contracts": CONTRACTS_OFF,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class _Counters:
    hits: int
    misses: int
    invalidated: int
    errors: int
    problems: list[str]

    def problem(self, message: str) -> None:
        self.errors += 1
        if message not in self.problems:
            self.problems.append(message)


class FileCache:
    """One run's view of the cache directory. ``open`` validates the index, ``lookup``
    and ``store`` serve the per-file phase, ``coverage`` reports what happened."""

    def __init__(self, directory: Path, configured: str, config_digest: str) -> None:
        self.directory = directory
        self.configured = configured
        self.header: dict[str, str] = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "tool_version": __version__,
            "config_digest": config_digest,
            "host": host_label(),
        }
        self.counters = _Counters(0, 0, 0, 0, [])
        self.writable = False
        self.contracts = CONTRACTS_OFF

    # --- opening -----------------------------------------------------------------------

    def open(self) -> None:
        index = self.directory / INDEX_FILENAME
        if not index.is_file():
            self._initialize()  # a new cache directory
            return
        document = self._read_json(index, "index.json")
        if document is None:
            self._initialize()  # unreadable or corrupt: already counted and described
            return
        if not isinstance(document, dict) or set(document) != set(HEADER_KEYS):
            self.counters.problem(
                "index.json does not have the expected shape; the cache was rebuilt"
            )
            self._initialize()
            return
        if document != self.header:
            self._initialize()  # another tool version, configuration or host
            return
        self.writable = True

    def _initialize(self) -> None:
        """Discard every entry and write a fresh index for the current header."""
        self.counters.invalidated += self._remove_entries()
        if not self._write_atomic(self.directory / TAG_FILENAME, TAG_CONTENT.encode("utf-8")):
            return
        payload = json.dumps(self.header, indent=1, sort_keys=True).encode("utf-8")
        if not self._write_atomic(self.directory / INDEX_FILENAME, payload):
            return
        self.writable = True

    def _remove_entries(self) -> int:
        entries = self.directory / ENTRIES_DIRNAME
        if not entries.is_dir():
            return 0
        removed = 0
        for shard in sorted(entries.iterdir()):
            if not shard.is_dir():
                continue
            for entry in sorted(shard.iterdir()):
                # Boundary (declared in .shockharness.toml): deleting a stale cache entry.
                try:
                    entry.unlink()
                except OSError as exc:
                    self.counters.problem(
                        f"stale cache entry {entry.name} could not be removed: {exc}"
                    )
                    continue
                removed += 1
        return removed

    # --- per-file ------------------------------------------------------------------------

    def _entry_path(self, relative_path: str) -> Path:
        digest = _sha256(relative_path.encode("utf-8"))
        return self.directory / ENTRIES_DIRNAME / digest[:CACHE_SHARD_CHARS] / f"{digest}.json"

    def _key(self, language: str, content: bytes) -> dict[str, str]:
        return {**self.header, "language": language, "content": _sha256(content)}

    def lookup(
        self,
        relative_path: str,
        language: str,
        content: bytes,
        decode: Callable[[Any], Any],
    ) -> Any | None:
        """The decoded entry for ``relative_path`` when its key matches, else ``None``
        (a miss, an invalidated entry, or a counted and described problem)."""
        path = self._entry_path(relative_path)
        if not path.is_file():
            self.counters.misses += 1
            return None
        document = self._read_json(path, f"the cache entry for {relative_path}")
        if document is None:
            self.counters.misses += 1
            return None
        if not isinstance(document, dict) or set(document) != {"key", "path", "pending"}:
            self.counters.problem(
                f"the cache entry for {relative_path} does not have the expected shape; "
                "the file was analyzed afresh"
            )
            self.counters.misses += 1
            return None
        if document["key"] != self._key(language, content) or document["path"] != relative_path:
            self.counters.invalidated += 1
            self.counters.misses += 1
            return None
        # Boundary (declared in .shockharness.toml): an entry's content is external data.
        try:
            decoded = decode(document["pending"])
        except CacheEntryError as exc:
            self.counters.problem(
                f"the cache entry for {relative_path} could not be decoded ({exc}); the "
                "file was analyzed afresh"
            )
            self.counters.misses += 1
            return None
        self.counters.hits += 1
        return decoded

    def store(self, relative_path: str, language: str, content: bytes, plain: Any) -> None:
        if not self.writable:
            return
        document = {"key": self._key(language, content), "path": relative_path, "pending": plain}
        payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._write_atomic(self._entry_path(relative_path), payload)

    # --- the property-contracts phase ----------------------------------------------------

    def lookup_contracts(self, key: Mapping[str, str], decode: Callable[[Any], Any]) -> Any | None:
        """The decoded result of the last run's contracts phase when ``key`` (with the
        header) matches; ``None`` otherwise. The caller still checks the files on disk."""
        self.contracts = CONTRACTS_MISS
        path = self.directory / CONTRACTS_FILENAME
        if not path.is_file():
            return None
        document = self._read_json(path, "the property-contracts entry")
        if document is None:
            return None
        if not isinstance(document, dict) or set(document) != {"key", "result"}:
            self.counters.problem(
                "the property-contracts entry does not have the expected shape; the phase "
                "ran afresh"
            )
            return None
        if document["key"] != {**self.header, **key}:
            return None
        # Boundary (declared in .shockharness.toml): an entry's content is external data.
        try:
            decoded = decode(document["result"])
        except CacheEntryError as exc:
            self.counters.problem(
                f"the property-contracts entry could not be decoded ({exc}); the phase ran afresh"
            )
            return None
        return decoded

    def contracts_status(self, status: str) -> None:
        self.contracts = status

    def store_contracts(self, key: Mapping[str, str], plain: Any) -> None:
        if not self.writable:
            return
        document = {"key": {**self.header, **key}, "result": plain}
        payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._write_atomic(self.directory / CONTRACTS_FILENAME, payload)

    # --- I/O ---------------------------------------------------------------------------

    def _read_json(self, path: Path, label: str) -> Any | None:
        # Boundary (declared in .shockharness.toml): cache files are external data.
        try:
            raw = path.read_bytes()
        except OSError as exc:
            self.counters.problem(f"{label} could not be read ({exc}); it was ignored")
            return None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self.counters.problem(f"{label} is not valid UTF-8 ({exc}); it was ignored")
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self.counters.problem(f"{label} is not valid JSON ({exc}); it was ignored")
            return None

    def _write_atomic(self, path: Path, payload: bytes) -> bool:
        """Write ``payload`` to ``path`` through a temporary file in the same directory."""
        # Boundary (declared in .shockharness.toml): writing into the cache directory.
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.counters.problem(f"cache directory {path.parent} could not be created ({exc})")
            return False
        try:
            handle, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        except OSError as exc:
            self.counters.problem(f"temporary cache file next to {path.name} failed ({exc})")
            return False
        try:
            self._fill_and_replace(handle, temporary, payload, path)
        except OSError as exc:
            self.counters.problem(f"cache file {path.name} could not be written ({exc})")
            self._discard(temporary)
            return False
        return True

    def _fill_and_replace(self, handle: int, temporary: str, payload: bytes, path: Path) -> None:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)

    def _discard(self, temporary: str) -> None:
        # Boundary (declared in .shockharness.toml): best-effort removal of a temp file.
        try:
            os.unlink(temporary)
        except OSError as exc:
            self.counters.problem(f"temporary cache file {temporary} was left behind ({exc})")

    # --- reporting -------------------------------------------------------------------------

    def coverage(self) -> dict[str, Any]:
        counters = self.counters
        return {
            "status": STATUS_ENABLED,
            "directory": self.configured,
            "reason": REASON_ENABLED,
            "hits": counters.hits,
            "misses": counters.misses,
            "invalidated": counters.invalidated,
            "errors": counters.errors,
            "problems": list(counters.problems),
            "contracts": self.contracts,
        }


def open_cache(root: Path, config: EffectiveConfig) -> FileCache:
    """Open (creating or rebuilding as needed) the cache configured for ``root``."""
    cache = FileCache(
        cache_directory(root, config), str(config.values[CACHE_KEY]["directory"]), config.digest
    )
    cache.open()
    return cache


def cache_settings(config: EffectiveConfig) -> Mapping[str, Any]:
    return config.values[CACHE_KEY]
