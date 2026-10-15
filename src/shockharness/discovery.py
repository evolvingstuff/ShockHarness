"""File discovery: explicit targets, include/exclude globs, language routing.

Deterministic: the result is sorted by relative path. Symlinks are not followed
unless ``follow_symlinks`` is configured, so analysis never escapes the root
through a link by accident. Targets outside the root are a usage error rather
than a silently relative-less path.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.cache.store import cache_directory
from shockharness.config import SUPPORTED_EXTENSIONS, EffectiveConfig
from shockharness.errors import UsageError
from shockharness.globs import GlobSet, compile_globset

GIT_DIR = ".git"

STATUS_EXCLUDED = "excluded"


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    relative: str
    language: str


@dataclass(frozen=True)
class SkippedFile:
    relative: str
    reason: str


@dataclass(frozen=True)
class DiscoveryResult:
    """``unsupported`` lists the files ``include`` matched (and ``exclude`` kept) whose
    extension no adapter parses; ``unsupported_sources`` decides what they mean."""

    files: tuple[DiscoveredFile, ...]
    explicit_excluded: tuple[SkippedFile, ...]
    unsupported: tuple[SkippedFile, ...]
    counts: Mapping[str, int]

    def counts_json(self) -> dict[str, Any]:
        return dict(sorted(self.counts.items()))


def relative_posix(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise UsageError(
            f"target is outside the analysis root {resolved_root}; pass --root", str(path)
        )
    return resolved.relative_to(resolved_root).as_posix()


def language_for(path: Path) -> str | None:
    suffix = path.suffix
    if suffix in SUPPORTED_EXTENSIONS:
        return SUPPORTED_EXTENSIONS[suffix]
    return None


def _walk_directory(
    root: Path,
    directory: Path,
    include: GlobSet,
    exclude: GlobSet,
    follow_symlinks: bool,
    cache_dir: Path,
    found: dict[str, DiscoveredFile],
    unsupported: dict[str, SkippedFile],
    counts: dict[str, int],
) -> None:
    for current, dirnames, filenames in os.walk(directory, followlinks=follow_symlinks):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            if name == GIT_DIR:
                continue
            child = current_path / name
            if child.resolve() == cache_dir:
                continue  # never analyzed, whatever include says; not counted, like .git
            if not follow_symlinks and child.is_symlink():
                counts["symlinks_skipped"] += 1
                continue
            if exclude.prunes_directory(relative_posix(root, child)):
                counts["directories_pruned"] += 1
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            child = current_path / name
            if not follow_symlinks and child.is_symlink():
                counts["symlinks_skipped"] += 1
                continue
            relative = relative_posix(root, child)
            language = language_for(child)
            if language is None:
                counts["unsupported_extension"] += 1
                if include.matches(relative) and not exclude.matches(relative):
                    counts["unsupported_sources"] += 1
                    unsupported[relative] = SkippedFile(
                        relative, f"extension {child.suffix!r} is not a supported language"
                    )
                continue
            if not include.matches(relative):
                counts["not_included"] += 1
                continue
            if exclude.matches(relative):
                counts["excluded"] += 1
                continue
            found[relative] = DiscoveredFile(path=child, relative=relative, language=language)


def discover(root: Path, targets: list[Path], config: EffectiveConfig) -> DiscoveryResult:
    include = compile_globset(list(config.values["include"]))
    exclude = compile_globset(list(config.values["exclude"]))
    follow_symlinks = bool(config.values["follow_symlinks"])
    cache_dir = cache_directory(root, config).resolve()
    found: dict[str, DiscoveredFile] = {}
    unsupported: dict[str, SkippedFile] = {}
    explicit_excluded: list[SkippedFile] = []
    counts: dict[str, int] = {
        "not_included": 0,
        "excluded": 0,
        "unsupported_extension": 0,
        "unsupported_sources": 0,
        "symlinks_skipped": 0,
        "directories_pruned": 0,
    }
    if len(targets) == 0:
        raise UsageError("at least one file or directory to analyze is required", None)
    for target in targets:
        if not target.exists():
            raise UsageError("path does not exist", str(target))
        if target.is_dir():
            _walk_directory(
                root,
                target,
                include,
                exclude,
                follow_symlinks,
                cache_dir,
                found,
                unsupported,
                counts,
            )
            continue
        relative = relative_posix(root, target)
        language = language_for(target)
        if language is None:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise UsageError(f"unsupported file type (supported: {supported})", str(target))
        if exclude.matches(relative):
            pattern = exclude.first_match(relative)
            explicit_excluded.append(SkippedFile(relative, f"matches exclude pattern {pattern!r}"))
            continue
        found[relative] = DiscoveredFile(path=target, relative=relative, language=language)
    ordered = tuple(found[key] for key in sorted(found))
    return DiscoveryResult(
        files=ordered,
        explicit_excluded=tuple(sorted(explicit_excluded, key=lambda s: s.relative)),
        unsupported=tuple(unsupported[key] for key in sorted(unsupported)),
        counts=counts,
    )
