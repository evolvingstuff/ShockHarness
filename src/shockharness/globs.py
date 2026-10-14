"""Deterministic glob matching for include/exclude/override paths.

Semantics (documented in docs/configuration.md):

* Patterns use forward slashes and are relative to the analysis root.
* ``**`` matches zero or more whole path segments and must be a segment by itself.
* ``*`` matches any run of characters within one segment; ``?`` matches one.
* ``[...]`` is a character class; a leading ``!`` negates it.
* A pattern with no ``/`` matches against the file's basename anywhere in the tree.
  A pattern containing ``/`` matches against the whole relative path.

Validation is separate from compilation so that config errors are reported with
their key path instead of surfacing as regex exceptions.
"""

import re
from dataclasses import dataclass

DOUBLE_STAR = "**"


def validate_glob(pattern: str) -> str | None:
    """Return an error message if ``pattern`` is invalid, else ``None``."""
    if pattern == "":
        return "glob pattern must not be empty"
    if "\\" in pattern:
        return "glob pattern must use forward slashes, not backslashes"
    if "\0" in pattern:
        return "glob pattern must not contain NUL"
    if pattern.startswith("/"):
        return "glob pattern must be relative to the analysis root (no leading '/')"
    depth = 0
    for ch in pattern:
        if ch == "[":
            if depth > 0:
                return "nested '[' in glob pattern"
            depth += 1
        elif ch == "]":
            if depth == 0:
                return "unmatched ']' in glob pattern"
            depth -= 1
    if depth != 0:
        return "unmatched '[' in glob pattern"
    for segment in pattern.split("/"):
        if DOUBLE_STAR in segment and segment != DOUBLE_STAR:
            return "'**' must be a whole path segment (write '**/' or '/**')"
    return None


def _normalize(pattern: str) -> str:
    if pattern.startswith("./"):
        return pattern[len("./") :]
    return pattern


def glob_to_regex(pattern: str) -> str:
    """Compile a *validated* glob to an anchored regular expression source."""
    pattern = _normalize(pattern)
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if pattern.startswith(DOUBLE_STAR, i):
            after = i + len(DOUBLE_STAR)
            if after < n and pattern[after] == "/":
                out.append("(?:.*/)?")
                i = after + 1
            else:
                out.append(".*")
                i = after
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[":
            close = pattern.index("]", i + 1)
            body = pattern[i + 1 : close]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = close + 1
            continue
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class CompiledGlob:
    pattern: str
    basename_only: bool
    regex: re.Pattern[str]

    def matches(self, relative_path: str) -> bool:
        if self.basename_only:
            parts = relative_path.rsplit("/", 1)
            basename = parts[len(parts) - 1]
            return self.regex.fullmatch(basename) is not None
        return self.regex.fullmatch(relative_path) is not None

    def prunes_directory(self, relative_dir: str) -> bool:
        """True when the pattern is ``<dir-glob>/**`` and ``relative_dir`` matches it."""
        if self.basename_only:
            return False
        suffix = "/" + DOUBLE_STAR
        if not self.pattern.endswith(suffix):
            return False
        dir_pattern = self.pattern[: len(self.pattern) - len(suffix)]
        return re.fullmatch(glob_to_regex(dir_pattern), relative_dir) is not None


def compile_glob(pattern: str) -> CompiledGlob:
    normalized = _normalize(pattern)
    return CompiledGlob(
        pattern=normalized,
        basename_only="/" not in normalized,
        regex=re.compile(glob_to_regex(normalized)),
    )


@dataclass(frozen=True)
class GlobSet:
    globs: tuple[CompiledGlob, ...]

    def matches(self, relative_path: str) -> bool:
        return any(g.matches(relative_path) for g in self.globs)

    def first_match(self, relative_path: str) -> str | None:
        for g in self.globs:
            if g.matches(relative_path):
                return g.pattern
        return None

    def prunes_directory(self, relative_dir: str) -> bool:
        return any(g.prunes_directory(relative_dir) for g in self.globs)


def compile_globset(patterns: list[str]) -> GlobSet:
    return GlobSet(globs=tuple(compile_glob(p) for p in patterns))
