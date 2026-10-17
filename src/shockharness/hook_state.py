"""What the edit-time hook remembers between runs, in the cache directory:

* ``hook/state.json``: per analyzed file, the SHA-256 of the content the hook last
  analyzed, so a shell command that did not touch a file does not report it again;
* ``hook/runs.jsonl``: one line per hook run (time, tool, files analyzed, findings,
  exit code, notes and I/O problems), so "clean" and "never ran" can be told apart.

Every I/O failure is recorded in ``problems`` and written to the run's log line, as the
cache does with its counters. A state that cannot be read is no state: every file git
shows as changed is analyzed again, which only means more feedback, never less.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

HOOK_DIRECTORY = "hook"
STATE_FILE = "state.json"
RUNS_FILE = "runs.jsonl"
WRITE = "w"
APPEND = "a"


class HookStore:
    def __init__(self, cache_directory: Path) -> None:
        self.directory = cache_directory / HOOK_DIRECTORY
        self.problems: list[str] = []

    def content_hash(self, path: Path) -> str | None:
        """The SHA-256 of the file's bytes, or None (recorded) when it cannot be read:
        deleted since git listed it, or unreadable."""
        # Boundary (declared in .shockharness.toml): reading a file the agent changed.
        try:
            data = path.read_bytes()
        except OSError as exc:
            self.problems.append(f"{path.name} could not be read ({exc}); not analyzed")
            return None
        return hashlib.sha256(data).hexdigest()

    def _read_state_text(self, path: Path) -> str | None:
        # Boundary (declared in .shockharness.toml): the state file is the hook's own I/O.
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.problems.append(f"hook state could not be read ({exc}); it was ignored")
            return None

    def _parse_state(self, text: str) -> object:
        # Boundary (declared in .shockharness.toml): a corrupt state is no state.
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self.problems.append(f"hook state is not valid JSON ({exc}); it was ignored")
            return None

    def load_state(self) -> dict[str, str]:
        """Path -> hash of the content last analyzed; empty when there is none to read."""
        path = self.directory / STATE_FILE
        if not path.is_file():
            return {}
        text = self._read_state_text(path)
        if text is None:
            return {}
        document = self._parse_state(text)
        if not isinstance(document, dict):
            return {}
        return {str(k): str(v) for k, v in document.items()}

    def _put(self, path: Path, text: str, mode: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with path.open(mode, encoding="utf-8") as stream:
            stream.write(text)

    def _write(self, name: str, text: str, mode: str) -> bool:
        path = self.directory / name
        # Boundary (declared in .shockharness.toml): the hook's state and log are its own
        # files in the cache directory.
        try:
            self._put(path, text, mode)
        except OSError as exc:
            self.problems.append(f"hook {name} could not be written ({exc})")
            return False
        return True

    def save_state(self, state: Mapping[str, str]) -> None:
        self._write(STATE_FILE, json.dumps(dict(sorted(state.items())), indent=1) + "\n", WRITE)

    def log_run(self, record: Mapping[str, object]) -> bool:
        """Append the run's line (with every problem so far); False when it could not be
        written, so the caller can say so."""
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        line = json.dumps({"time": stamp, **record, "problems": list(self.problems)})
        return self._write(RUNS_FILE, line + "\n", APPEND)
