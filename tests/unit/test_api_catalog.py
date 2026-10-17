"""H5 API-catalog rules: PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001,
STUB003."""

from collections.abc import Callable
from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
H5 = ("PROCESS001", "RESULT001", "TYPE001", "SLEEP001", "RETRY001", "BATCH001", "STUB003")


def run(config: EffectiveConfig, path: str, text: str) -> FileResult:
    language = "python" if path.endswith(".py") else "javascript"
    return analyze_text(path, language, text, config, OPTIONS)


def rows(result: FileResult, rule: str) -> list[tuple[int, str]]:
    return [(f.span.line, f.severity) for f in result.findings if f.rule_id == rule]


def test_process001_python(strict_config: EffectiveConfig) -> None:
    text = (
        "import os\nimport subprocess\nimport subprocess as sp\n\n\n"
        "def f(cmd, path):\n"
        "    subprocess.run(f'ls {cmd}', shell=True)\n"  # 7 injection
        "    subprocess.run('ls ' + path, shell=True)\n"  # 8 injection
        "    os.system('rm -rf ' + path)\n"  # 9 injection (always a shell)
        "    subprocess.run(['ls', path], check=True)\n"
        "    sp.run(['ls'])\n"  # 11 status ignored (discarded, no check)
        "    subprocess.run(['ls'], check=False)\n"  # 12 status ignored
        "    subprocess.call(['ls'])\n"  # 13 status ignored
        "    os.system('ls')\n"  # 14 status ignored
        "    subprocess.check_output(['ls'])\n"
        "    subprocess.run('ls', shell=True, check=True)\n"  # literal command: fine
        "\n\n"
        "def g():\n"
        "    result = subprocess.run(['ls'])\n"
        "    if result.returncode != 0:\n        raise RuntimeError('ls failed')\n"
        "    return result\n\n\n"
        "def h(app):\n    app.run(['ls'])\n"  # not a process API
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.py", text), "PROCESS001")] == [
        7,
        8,
        9,
        11,
        12,
        13,
        14,
    ]


def test_process001_javascript(strict_config: EffectiveConfig) -> None:
    text = (
        'import { exec, execSync, spawnSync, execFile } from "node:child_process";\n'
        "export function f(cmd) {\n"
        "  exec(`ls ${cmd}`);\n"  # 3
        '  execSync("ls " + cmd);\n'  # 4
        "  execFile(`ls ${cmd}`);\n"  # no shell
        '  spawnSync("ls", [cmd], { shell: true });\n'  # 6 discarded status
        "  spawnSync(`ls ${cmd}`, [], { shell: true });\n"  # 7 injection
        '  const r = spawnSync("ls", []);\n'  # 8 status not read
        "}\n"
        "export function g() {\n"
        '  const r = spawnSync("ls", []);\n'
        '  if (r.status !== 0) { throw new Error("ls failed"); }\n'
        "}\n"
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.js", text), "PROCESS001")] == [
        3,
        4,
        6,
        7,
        8,
    ]


def test_result001(strict_config: EffectiveConfig) -> None:
    py = (
        "import copy\nimport os\n\n\n"
        "def f(name, items, path, other):\n"
        "    name.strip()\n"  # 6 approximate
        "    sorted(items)\n"  # 7 exact
        "    copy.deepcopy(items)\n"  # 8 exact
        "    os.replace(path, other)\n"  # a module function, not a method
        "    items.sort()\n"
        "    name = name.strip()\n"
        "    return name\n"
    )
    result = run(strict_config, "src/a.py", py)
    found = [(f.span.line, f.confidence) for f in result.findings if f.rule_id == "RESULT001"]
    assert found == [(6, "approximate"), (7, "exact"), (8, "exact")]
    js = (
        "export function f(items, name) {\n"
        "  items.map((i) => i.id);\n"  # 2
        "  name.trim();\n"  # 3
        "  items.forEach((i) => use(i));\n"
        "  structuredClone(items);\n"  # 5
        "  return items;\n"
        "}\n"
    )
    assert [r[0] for r in rows(run(strict_config, "tests/a.test.js", js), "RESULT001")] == [2, 3, 5]


def test_result001_counts_arguments_and_skips_validation(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    # MetaList: methods of other classes that share a name with a pure one.
    py = (
        "def f(name, worker, path, target, parts, host):\n"
        "    name.replace('a', 'b')\n"  # 2: str.replace takes 2-3 arguments
        "    worker.join(timeout=5)\n"  # Thread.join: no positional argument
        "    worker.join()\n"  # Thread.join(): str.join needs 1
        "    path.replace(target)\n"  # Path.replace renames
        "    ', '.join(parts)\n"  # 6: a string literal's method is str.join
        "    name.join(parts)\n"  # 7: .join is not in the defaults (Thread.join(3))
        "    layout.split(*parts)\n"  # unpacked: the count is unknown
        "    try:\n"
        "        host.encode('idna')\n"  # run for what it raises
        "    except UnicodeError:\n"
        "        return None\n"
        "    return name\n"
    )
    config = make_config("")
    assert [r[0] for r in rows(run(config, "src/a.py", py), "RESULT001")] == [2, 6]
    js = (
        "export function f(name, store, tab) {\n"
        "  window.location.replace(url);\n"  # navigation
        "  tab.location.replace(url);\n"
        "  store.replaceAll({ a: 1 });\n"  # a project method
        "  name.replace('a', 'b');\n"  # 5
        "  try { name.trim(); } catch (error) { return null; }\n"
        "  return name;\n"
        "}\n"
    )
    assert [r[0] for r in rows(run(config, "src/a.js", js), "RESULT001")] == [5]
    wider = make_config(
        '[tool.shockharness.rules.results]\npython_must_use = [".join/1", ".replace"]\n'
    )
    assert [r[0] for r in rows(run(wider, "src/a.py", py), "RESULT001")] == [2, 5, 6, 7]
    removed = next(d for d in wider.deviations if "python_must_use no longer lists" in d)
    assert "'sorted'" in removed
    assert "'.replace/2-3'" not in removed  # ".replace" covers it: any number of arguments


def test_type001_kinds_and_switches(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = (
        "import typing\nfrom typing import Any, cast\n\n\n"
        "def f(raw: Any, other: typing.Any) -> dict[str, Any]:\n"  # 5: three Any
        "    value = cast(int, raw)  # type: ignore[arg-type]\n"  # 6: cast + ignore
        "    total: Any = typing.cast(int, other)\n"  # 7: Any + cast
        "    return {'v': value, 't': total}\n"
    )
    default = run(make_config(""), "src/a.py", text)
    assert (
        rows(default, "TYPE001") == [(5, "review")] * 3 + [(6, "review")] * 2 + [(7, "review")] * 2
    )
    narrowed = make_config(
        "[tool.shockharness.rules.types]\nreport_any = false\nreport_cast = false\n"
    )
    assert rows(run(narrowed, "src/a.py", text), "TYPE001") == [(6, "review")]
    assert any("rules.types.report_any is false" in d for d in narrowed.deviations)


def test_sleep001(strict_config: EffectiveConfig) -> None:
    py = (
        "import time\nimport asyncio\n\n\n"
        "async def f(server):\n"
        "    time.sleep(1)\n"  # 6 fixed wait
        "    while not server.ready():\n        await asyncio.sleep(1)\n"  # 8 polling
        "    server.sleep(1)\n"  # not a sleep API
    )
    result = run(strict_config, "src/a.py", py)
    found = [
        (f.span.line, f.message.split(" instead")[0])
        for f in result.findings
        if f.rule_id == "SLEEP001"
    ]
    assert found == [(6, "waits a fixed time"), (8, "polls with a fixed sleep in a loop")]
    js = (
        'import { setTimeout as delay } from "timers/promises";\n'
        "export async function f() {\n"
        "  await new Promise((resolve) => setTimeout(resolve, PAUSE));\n"  # 3
        "  await delay(PAUSE);\n"
        "  setTimeout(tick, PAUSE);\n"
        "}\n"
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.js", js), "SLEEP001")] == [3]


def test_retry001(strict_config: EffectiveConfig) -> None:
    py = (
        "import backoff\nimport tenacity\nfrom tenacity import retry, stop_after_attempt\n\n\n"
        "@tenacity.retry\ndef a():\n    return fetch()\n\n\n"  # 6
        "@retry(stop=stop_after_attempt(ATTEMPTS))\ndef b():\n    return fetch()\n\n\n"
        "@backoff.on_exception(backoff.expo, OSError)\ndef c():\n    return fetch()\n\n\n"  # 16
        "@backoff.on_exception(backoff.expo, OSError, max_tries=ATTEMPTS)\ndef d():\n"
        "    return fetch()\n\n\n"
        "def e():\n"
        "    while True:\n"  # 27
        "        try:\n            return fetch()\n"
        "        except OSError:\n            pause()\n\n\n"
        "def g():\n"
        "    attempts = 0\n"
        "    while True:\n"
        "        try:\n            return fetch()\n        except OSError:\n"
        "            attempts += 1\n            if attempts > LIMIT:\n                raise\n"
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.py", py), "RETRY001")] == [6, 16, 27]
    js = (
        "export async function f() {\n"
        "  while (true) { try { return await fetchIt(); } catch (e) { await pause(); } }\n"
        "}\n"
        "export async function g() {\n"
        "  for (;;) { try { return await fetchIt(); } catch (e) { throw e; } }\n"
        "}\n"
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.js", js), "RETRY001")] == [2]


def test_batch001(strict_config: EffectiveConfig) -> None:
    py = (
        "import logging\n\nlog = logging.getLogger(__name__)\n\n\n"
        "def f(rows):\n"
        "    for row in rows:\n"  # 7
        "        try:\n            save(row)\n        except ValueError:\n"
        "            log.warning('skip')\n"
        "    failures = []\n"
        "    for row in rows:\n"
        "        try:\n            save(row)\n        except ValueError as error:\n"
        "            failures.append((row, error))\n"
        "    return failures\n"
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.py", py), "BATCH001")] == [7]
    js = (
        "export function f(rows) {\n"
        "  for (const row of rows) {\n"
        "    try { save(row); } catch (e) { console.warn(e); continue; }\n"
        "  }\n"
        "  for (const row of rows) { try { save(row); } catch (e) { report(row, e); } }\n"
        "}\n"
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.js", js), "BATCH001")] == [2]


def test_stub003_and_its_severity(make_config: Callable[[str], EffectiveConfig]) -> None:
    py = (
        "def is_admin(user):\n    '''Docs.'''\n    return True\n\n\n"
        "def can_edit(user, doc):\n    return user.id == doc.owner\n\n\n"
        "def enabled():\n    return True\n"
    )
    assert rows(run(make_config(""), "src/a.py", py), "STUB003") == [(1, "review")]
    error = make_config('[tool.shockharness.rules.stubs]\nstub003_severity = "error"\n')
    assert rows(run(error, "src/a.py", py), "STUB003") == [(1, "error")]
    js = (
        "export const isAdmin = (user) => true;\n"
        "export function canEdit(user) { return true; }\n"
        "export function hasAccess(user) { return user.ok; }\n"
        "class A { validateToken(token) { return true; } }\n"
    )
    assert [r[0] for r in rows(run(make_config(""), "src/a.js", js), "STUB003")] == [1, 2, 4]


def test_roles_scope_the_catalog_rules(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = "import subprocess\n\n\ndef f(name):\n    subprocess.run(['ls'])\n    name.strip()\n"
    default = make_config("")
    test_file = run(default, "tests/test_a.py", text)
    assert [f.rule_id for f in test_file.findings if f.rule_id in H5] == ["RESULT001"]
    assert "PROCESS001" not in test_file.rules_applied
    production = run(default, "src/a.py", text)
    assert [f.rule_id for f in production.findings if f.rule_id in H5] == [
        "PROCESS001",
        "RESULT001",
    ]


def test_process001_hands_a_returned_result_to_the_caller(strict_config: EffectiveConfig) -> None:
    """MetaList feedback (0.7.0): the callers of run_command_allow_failure check returncode."""
    py = (
        "import subprocess\n\n\n"
        "def run_command_allow_failure(cmd):\n"
        "    return subprocess.run(cmd, capture_output=True)\n\n\n"
        "def stored(cmd):\n    result = subprocess.run(cmd)\n    return result\n\n\n"
        "def lost(cmd):\n    result = subprocess.run(cmd)\n    return cmd\n"  # 14
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.py", py), "PROCESS001")] == [14]
    js = (
        'import { spawnSync } from "node:child_process";\n'
        "export function a(c) { return spawnSync(c, []); }\n"
        "export function b(c) { const r = spawnSync(c, []); return r; }\n"
        "export function d(c) { const r = spawnSync(c, []); return c; }\n"  # 4
    )
    assert [r[0] for r in rows(run(strict_config, "src/a.js", js), "PROCESS001")] == [4]


def test_stub003_hook_defaults_and_redundant_overrides(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    # MetaList: BaseModal's documented default, and subclasses that repeat it.
    files = {
        "src/base-modal.js": (
            "export class BaseModal {\n"
            "  // Override in subclasses to disable.\n"
            "  shouldCloseOnClickOutside() { return true; }\n"
            "}\n"
        ),
        "src/help.js": (
            "import { BaseModal } from './base-modal.js';\n"
            "export class HelpModal extends BaseModal {\n"
            "  shouldCloseOnClickOutside() { return true; }\n"  # 3: repeats the default
            "}\n"
            "export class Login extends BaseModal {\n"
            "  isAllowed() { return true; }\n"  # 6: a check of its own that says yes
            "}\n"
        ),
        "src/perms.py": (
            "class Permission:\n    def has_permission(self):\n        return True\n\n\n"
            "class Open(Permission):\n    def has_permission(self):\n        return True\n"
        ),  # 7: repeats the base
    }
    for name, body in files.items():
        (empty_root / name).parent.mkdir(parents=True, exist_ok=True)
        (empty_root / name).write_text(body, encoding="utf-8")
    report = analyze_paths([empty_root], empty_root, strict_config, OPTIONS)
    found = [(f.path, f.span.line, f.message) for f in report.findings if f.rule_id == "STUB003"]
    assert [(path, line) for path, line, _message in found] == [
        ("src/help.js", 3),
        ("src/help.js", 6),
        ("src/perms.py", 7),
    ]
    assert found[0][2] == (
        "HelpModal.shouldCloseOnClickOutside repeats BaseModal.shouldCloseOnClickOutside, "
        "which already answers yes: remove the override"
    )
    assert found[1][2] == "isAllowed is named as a check and always answers yes"
