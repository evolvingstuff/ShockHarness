"""CALL001: a call across a boundary the project declared."""

from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import ConfigError, load_config
from shockharness.loosening import loosenings

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
HEADER = '[tool.shockharness]\nprofile = "strict"\ninclude = ["app/**/*.py", "web/**/*.js"]\n'
TABLE = "[[tool.shockharness.rules.call_boundaries.forbidden]]\n"
DISK = (
    TABLE + 'callers = ["app/**"]\nallowed_callers = ["app/storage/writer.py"]\n'
    'calls = ["@disk_writes"]\nreason = "plaintext never touches disk"\n'
)
NETWORK = (
    TABLE + 'callers = ["web/**"]\nallowed_callers = ["web/net/**"]\n'
    'calls = ["@network"]\nreason = "one client"\n'
)


def found(root: Path, files: dict[str, str], config: str = HEADER + DISK + NETWORK) -> list[str]:
    for name, text in {".shockharness.toml": config, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return sorted(
        f"{f.path}:{f.span.line} {f.status} {f.confidence} {f.message}"
        for f in report.findings
        if f.rule_id == "CALL001"
    )


NOTES = """import os
import shutil as sh
from pathlib import Path


def save(path, text, mode):
    with open(path, "w") as handle:
        handle.write(text)
    with open(path) as handle:
        handle.read()
    open(path, mode)
    Path(path).write_text(text)
    sh.copy(path, path + ".bak")
    os.path.join(path, "x")
    text.replace("a", "b")


def shadowed(open):
    return open("x", "w")
"""


def test_python_calls_resolved_through_imports_with_modes_and_methods(tmp_path: Path) -> None:
    files = {"app/__init__.py": "", "app/notes.py": NOTES}
    assert found(tmp_path, files) == [
        "app/notes.py:11 unknown exact calls open with a mode the analysis cannot read; if "
        "it writes, only app/storage/writer.py may call: plaintext never touches disk",
        "app/notes.py:12 violation approximate calls Path(path).write_text, which only "
        "app/storage/writer.py may call: plaintext never touches disk",
        "app/notes.py:13 violation exact calls shutil.copy, which only app/storage/writer.py "
        "may call: plaintext never touches disk",
        "app/notes.py:7 violation exact calls open, which only app/storage/writer.py may "
        "call: plaintext never touches disk",
    ]


def test_allowed_and_unbound_files_call_freely(tmp_path: Path) -> None:
    writer = "def write(path, text):\n    open(path, 'w').write(text)\n"
    files = {
        "app/__init__.py": "",
        "app/storage/__init__.py": "",
        "app/storage/writer.py": writer,
        "web/net/client.js": "export const get = (u) => fetch(u);\n",
    }
    assert found(tmp_path, files) == []


PAGE = """import { writeFile } from 'fs/promises';
import fs from 'node:fs';
export async function load(p) {
  const r = await fetch('/api');
  window.fetch('/b');
  const s = new WebSocket('wss://x');
  await writeFile(p, 'x');
  fs.openSync(p, 'r');
  fs.openSync(p, 'w');
  return [r, s];
}
export function local() {
  const fetch = (u) => u;
  return fetch('/c');
}
"""


def test_javascript_globals_constructors_imports_and_flags(tmp_path: Path) -> None:
    config = HEADER + NETWORK + DISK.replace('callers = ["app/**"]', 'callers = ["web/**"]')
    lines = [line.split(" ", 3)[:3] for line in found(tmp_path, {"web/page.js": PAGE}, config)]
    assert lines == [
        ["web/page.js:4", "violation", "exact"],
        ["web/page.js:5", "violation", "exact"],
        ["web/page.js:6", "violation", "exact"],
        ["web/page.js:7", "violation", "exact"],
        ["web/page.js:9", "violation", "exact"],
    ]


def test_a_project_name_and_no_entry(tmp_path: Path) -> None:
    config = (
        HEADER
        + TABLE
        + ('callers = ["app/**"]\ncalls = ["os.system", "subprocess"]\nreason = "no processes"\n')
    )
    code = (
        "import os\nimport subprocess\n\n\ndef run(c):\n    os.system(c)\n    subprocess.run(c)\n"
    )
    files = {"app/__init__.py": "", "app/run.py": code}
    lines = [line.split(" ")[0] for line in found(tmp_path, files, config)]
    assert lines == ["app/run.py:6", "app/run.py:7"]
    assert found(tmp_path, files, HEADER) == []
    report = analyze_paths([tmp_path], tmp_path, load_config(tmp_path, None), OPTIONS)
    assert all("CALL001" not in f.rules_applied for f in report.files)


def _invalid(root: Path, entry: str) -> str:
    (root / ".shockharness.toml").write_text(HEADER + entry, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_config(root, None)
    return str(raised.value)


@pytest.mark.parametrize("call", ["@disk", "open/mode=read", "shutil copy", "./x"])
def test_a_call_is_a_name_or_a_catalog(tmp_path: Path, call: str) -> None:
    entry = TABLE + f'callers = ["app/**"]\ncalls = ["{call}"]\nreason = "r"\n'
    assert "rules.call_boundaries.forbidden[0].calls[0]" in _invalid(tmp_path, entry)


def test_an_entry_binds_callers_and_forbids_calls(tmp_path: Path) -> None:
    empty = TABLE + 'callers = []\ncalls = []\nreason = "r"\n'
    message = _invalid(tmp_path, empty)
    assert "forbidden[0].callers: must list at least one" in message
    assert "forbidden[0].calls: must list at least one" in message


def _entry(callers: str, allowed: str, calls: str) -> str:
    return (
        TABLE + f"callers = [{callers}]\nallowed_callers = [{allowed}]\n"
        f'calls = [{calls}]\nreason = "plaintext never touches disk"\n'
    )


def test_forbidding_less_is_a_loosening(tmp_path: Path) -> None:
    def keys(after: str) -> list[str]:
        config = tmp_path / ".shockharness.toml"
        before_entry = _entry('"app/**"', '"app/w.py"', '"@disk_writes", "fetch"')
        config.write_text(HEADER + before_entry, encoding="utf-8")
        before = load_config(tmp_path, None)
        config.write_text(HEADER + after, encoding="utf-8")
        later = load_config(tmp_path, None)
        return [
            i.key
            for i in loosenings(before.values, before.deviations, later.values, later.deviations)
        ]

    loosened = ["rules.call_boundaries.forbidden"]
    assert keys("") == loosened
    assert keys(_entry('"app/**"', '"app/w.py"', '"@disk_writes"')) == loosened
    assert keys(_entry('"app/**"', '"app/w.py", "app/x.py"', '"@disk_writes", "fetch"')) == loosened
    assert keys(_entry('"app/a/**"', '"app/w.py"', '"@disk_writes", "fetch"')) == loosened
    assert keys(_entry('"app/**", "lib/**"', "", '"@disk_writes", "fetch", "@network"')) == []


def test_dropping_a_name_from_a_catalog_is_a_deviation(tmp_path: Path) -> None:
    config = HEADER + '[tool.shockharness.rules.call_boundaries]\npython_network = ["httpx"]\n'
    (tmp_path / ".shockharness.toml").write_text(config, encoding="utf-8")
    deviations = load_config(tmp_path, None).deviations
    assert any("call_boundaries.python_network" in line for line in deviations)
