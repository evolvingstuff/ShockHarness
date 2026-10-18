"""``contracts install`` and ``contracts install --check`` (spec §6.1, P1a: Python).

The runtime file is copied into the project, which then owns it: nothing is published
and the project does not depend on ``shockharness``. The copy is recorded in
``.shockharness-contracts.json`` at the project root, in the manifest format ``skills
install`` writes (package version, SHA-256 per file; ``agent`` is ``contracts`` and each
entry is keyed by language). An edited copy (its hash differs from the manifest) is never
overwritten without ``--force``; ``--check`` writes nothing and exits 1 when a copy is
edited, missing, or older than the runtime this package ships.
"""

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from shockharness.constants import EXIT_OK, EXIT_VIOLATIONS, SKILLS_MANIFEST_SCHEMA_VERSION
from shockharness.errors import UsageError
from shockharness.skills.install import (
    STATUS_EDITED,
    STATUS_MISSING,
    STATUS_STALE,
    STATUS_UP_TO_DATE,
    STATUS_WRITTEN,
    Manifest,
    ManifestEntry,
    load_manifest,
    read_bytes,
    render_manifest,
    sha256_hex,
    write_bytes,
)
from shockharness.version import __version__

CONTRACTS_MANIFEST = ".shockharness-contracts.json"
MANIFEST_AGENT = "contracts"
RUNTIME_PACKAGE = "shockharness.contracts"
RUNTIME_DIRECTORY = "runtime"
PYTHON = "python"
JAVASCRIPT = "javascript"
TYPES = "javascript-types"
# The shipped files, keyed as the manifest records them, and the files of each language:
# the JavaScript module gets its type declarations beside it (``x.js`` -> ``x.d.ts``).
RUNTIME_FILES = {PYTHON: "contracts.py", JAVASCRIPT: "contracts.js", TYPES: "contracts.d.ts"}
LANGUAGE_FILES = {PYTHON: (PYTHON,), JAVASCRIPT: (JAVASCRIPT, TYPES)}
LANGUAGES = tuple(LANGUAGE_FILES)
DECLARATION_SUFFIXES = {".js": ".d.ts", ".mjs": ".d.mts"}


@dataclass(frozen=True)
class InstalledFile:
    language: str
    path: Path
    status: str
    detail: str


@dataclass(frozen=True)
class ContractsResult:
    manifest_path: Path
    files: tuple[InstalledFile, ...]
    exit_code: int


def runtime_bytes(key: str) -> bytes:
    """The exact bytes of a shipped runtime file (LF line endings on every platform)."""
    if key not in RUNTIME_FILES:
        raise UsageError(f"no runtime file {key!r}", None)
    name = RUNTIME_FILES[key]
    raw = resources.files(RUNTIME_PACKAGE).joinpath(RUNTIME_DIRECTORY).joinpath(name).read_bytes()
    return raw.replace(b"\r\n", b"\n")


def _relative(project: Path, destination: Path) -> str:
    resolved = (project / destination).resolve()
    if not resolved.is_relative_to(project.resolve()):
        raise UsageError(
            "the runtime file must be installed inside the project, where the analyzer "
            "resolves runtime_module",
            str(destination),
        )
    return resolved.relative_to(project.resolve()).as_posix()


def _manifest(project: Path) -> Manifest:
    path = project / CONTRACTS_MANIFEST
    if not path.is_file():
        return Manifest(SKILLS_MANIFEST_SCHEMA_VERSION, __version__, MANIFEST_AGENT, {})
    manifest = load_manifest(path)
    if manifest.agent != MANIFEST_AGENT:
        raise UsageError(f"not a contracts manifest (agent {manifest.agent!r})", str(path))
    return manifest


def _refusal(manifest: Manifest, relative: str, target: Path) -> str:
    """Why an existing file at ``target`` may not be replaced without --force ("" if it may)."""
    if not target.exists():
        return ""
    recorded = [entry for entry in manifest.skills.values() if entry.path == relative]
    if len(recorded) == 0:
        return "the file exists and this manifest did not write it"
    if sha256_hex(read_bytes(target)) != recorded[0].sha256:
        return "the file was edited since it was installed"
    return ""


def _destinations(language: str, destination: Path) -> list[tuple[str, Path]]:
    """(manifest key, destination) for each file of ``language``."""
    if language not in LANGUAGE_FILES:
        raise UsageError(f"no runtime for language {language!r}", None)
    if language == PYTHON:
        return [(PYTHON, destination)]
    if destination.suffix not in DECLARATION_SUFFIXES:
        raise UsageError("the JavaScript runtime is an ES module: --dest ends in .js or .mjs", None)
    types = destination.with_suffix("").with_suffix(DECLARATION_SUFFIXES[destination.suffix])
    return [(JAVASCRIPT, destination), (TYPES, types)]


def install_runtime(
    project: Path, language: str, destination: Path, force: bool
) -> ContractsResult:
    """Copy the runtime file(s) for ``language`` to ``destination`` (relative to
    ``project``) and record them in the manifest. Nothing is written when any target was
    edited or not installed here, unless ``force``."""
    manifest = _manifest(project)
    planned = []
    for key, path in _destinations(language, destination):
        relative = _relative(project, path)
        refusal = _refusal(manifest, relative, project / relative)
        if refusal != "" and not force:
            raise UsageError(f"{refusal}; pass --force to replace it", str(project / relative))
        planned.append((key, relative))
    entries = dict(manifest.skills)
    written: list[InstalledFile] = []
    for key, relative in planned:
        data = runtime_bytes(key)
        write_bytes(project / relative, data)
        entries[key] = ManifestEntry(path=relative, sha256=sha256_hex(data))
        written.append(
            InstalledFile(key, project / relative, STATUS_WRITTEN, f"from {__version__}")
        )
    updated = Manifest(SKILLS_MANIFEST_SCHEMA_VERSION, __version__, MANIFEST_AGENT, entries)
    manifest_path = project / CONTRACTS_MANIFEST
    write_bytes(manifest_path, render_manifest(updated).encode("utf-8"))
    return ContractsResult(manifest_path, tuple(written), EXIT_OK)


def _status(project: Path, language: str, entry: ManifestEntry) -> InstalledFile:
    target = project / entry.path
    if not target.is_file():
        return InstalledFile(language, target, STATUS_MISSING, "in the manifest but absent")
    current = sha256_hex(read_bytes(target))
    if current != entry.sha256:
        return InstalledFile(language, target, STATUS_EDITED, "differs from the manifest hash")
    if language in RUNTIME_FILES and sha256_hex(runtime_bytes(language)) != entry.sha256:
        detail = f"unchanged since install; {__version__} ships a newer runtime"
        return InstalledFile(language, target, STATUS_STALE, detail)
    return InstalledFile(language, target, STATUS_UP_TO_DATE, "")


def check_runtime(project: Path) -> ContractsResult:
    """Every recorded runtime file against the manifest and the shipped runtime; exit 1
    when any is edited, missing or stale. Writes nothing."""
    manifest_path = project / CONTRACTS_MANIFEST
    if not manifest_path.is_file():
        raise UsageError(
            "no contracts manifest here; run `shockharness contracts install --language "
            f"python --dest <path>` first (it writes {CONTRACTS_MANIFEST})",
            str(project),
        )
    manifest = _manifest(project)
    files = tuple(
        _status(project, language, entry) for language, entry in sorted(manifest.skills.items())
    )
    drifted = any(file.status != STATUS_UP_TO_DATE for file in files)
    return ContractsResult(manifest_path, files, EXIT_VIOLATIONS if drifted else EXIT_OK)
