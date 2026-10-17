"""``skills install --hook --lock``: a policy file outside the project (spec 21.1 decision 35).

The lock is the project's effective configuration at install time, written as a
``--policy`` file under the user's home directory (``~/.config/shockharness/locks/``), where
a change to the project cannot edit it. The repository can then tighten any key but
loosen none: a loosening is reverted to the lock's value and reported as VERIFY003. The one
list left out is ``rules.exceptions.boundaries``, so a catch boundary stays the agent's to
declare. The person who wants a change edits the lock file.

An agent with unrestricted shell access can still edit a file in the home directory; the
lock is a stronger signal, not a guarantee (Claude Code's sandbox, when on, keeps writes
inside the project).
"""

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shockharness.config import EffectiveConfig
from shockharness.constants import LOCK_DIGEST_HEX
from shockharness.errors import ConfigError

LOCK_DIRECTORY = Path(".config") / "shockharness" / "locks"
TOOL_TABLE = "tool.shockharness"
# (table path, key) of each list the lock leaves to the project.
UNLOCKED = ((("rules", "exceptions"), "boundaries"),)
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def lock_path(project_root: Path, home: Path) -> Path:
    """One lock per project directory: its name plus a digest of its resolved path."""
    resolved = project_root.resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:LOCK_DIGEST_HEX]
    return home / LOCK_DIRECTORY / f"{resolved.name}-{digest}.toml"


def _key(name: str) -> str:
    if BARE_KEY.fullmatch(name) is not None:
        return name
    return json.dumps(name)


def _value(value: Any, where: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item, where) for item in value) + "]"
    if isinstance(value, Mapping):
        fields = ", ".join(f"{_key(k)} = {_value(v, where)}" for k, v in value.items())
        return "{ " + fields + " }"
    raise ConfigError(f"a configuration value of type {type(value).__name__} has no TOML form", where)


def _without_unlocked(values: Mapping[str, Any]) -> dict[str, Any]:
    locked: dict[str, Any] = json.loads(json.dumps(values))
    for table, key in UNLOCKED:
        node: Any = locked
        for part in table:
            node = node[part]
        del node[key]
    return locked


def _table(name: str, values: Mapping[str, Any], lines: list[str]) -> None:
    lines.append(f"[{name}]")
    nested = []
    for key, value in values.items():
        if isinstance(value, Mapping):
            nested.append((key, value))
            continue
        lines.append(f"{_key(key)} = {_value(value, f'{name}.{key}')}")
    for key, value in nested:
        lines.append("")
        _table(f"{name}.{_key(key)}", value, lines)


def render_lock(config: EffectiveConfig, project_root: Path) -> str:
    """The lock file's text: every effective key except the catch boundaries."""
    lines = [
        f"# ShockHarness lock for {project_root.resolve()} (skills install --hook --lock).",
        "# The project's configuration may tighten these keys but not loosen them; edit this",
        "# file to accept a change. rules.exceptions.boundaries is left to the project.",
        "",
    ]
    _table(TOOL_TABLE, _without_unlocked(config.values), lines)
    return "\n".join(lines) + "\n"
