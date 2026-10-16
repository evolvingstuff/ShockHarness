"""File roles (Milestone H1): one label per analyzed file, from configurable globs.

Every file gets exactly one role: the first of ``generated``, ``vendor``, ``config``,
``test``, ``docs`` whose ``[tool.shockharness.file_roles]`` globs match its relative
path, else ``production``. Roles never change which files are discovered or analyzed;
they label files in the report and scope ``[[overrides]]`` (``roles = [...]``) and the
MAGIC001 configuration-file exemption.

The ``config`` role's globs are ``file_roles.config`` merged with the legacy spelling
``rules.magic_numbers.configuration_files`` (see :mod:`shockharness.config`); the
merge happens when the configuration is loaded, so this module only ever reads
``file_roles``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shockharness.globs import GlobSet, compile_globset

ROLE_GENERATED = "generated"
ROLE_VENDOR = "vendor"
ROLE_CONFIG = "config"
ROLE_TEST = "test"
ROLE_DOCS = "docs"
ROLE_PRODUCTION = "production"
# Precedence: the first role whose globs match decides. ``production`` has no globs; it
# is what a file is when nothing else matches.
CLASSIFIED_ROLES = (ROLE_GENERATED, ROLE_VENDOR, ROLE_CONFIG, ROLE_TEST, ROLE_DOCS)
ROLES = (*CLASSIFIED_ROLES, ROLE_PRODUCTION)
FILE_ROLES_KEY = "file_roles"


@dataclass(frozen=True)
class FileRole:
    """``pattern`` is the glob that decided the role as written, ``None`` for production."""

    role: str
    pattern: str | None


PRODUCTION = FileRole(ROLE_PRODUCTION, None)


@dataclass(frozen=True)
class RoleClassifier:
    globs: tuple[tuple[str, GlobSet], ...]  # (role, globs) in precedence order

    def classify(self, relative_path: str) -> FileRole:
        for role, patterns in self.globs:
            matched = patterns.first_match(relative_path)
            if matched is not None:
                return FileRole(role, matched)
        return PRODUCTION

    def pattern_of(self, role: str, relative_path: str) -> str | None:
        """The first glob of ``role`` matching the path, whatever role the file has."""
        for name, patterns in self.globs:
            if name == role:
                return patterns.first_match(relative_path)
        raise ValueError(f"unknown file role {role!r}")


def role_classifier(file_roles: Mapping[str, Any]) -> RoleClassifier:
    """The classifier for a validated ``file_roles`` table."""
    return RoleClassifier(
        globs=tuple(
            (role, compile_globset([str(p) for p in file_roles[role]])) for role in CLASSIFIED_ROLES
        )
    )


def empty_role_counts() -> dict[str, int]:
    return {role: 0 for role in ROLES}
