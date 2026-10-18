"""The JavaScript property-contracts runtime (spec §6.2, §6.2a, §6.3, P1b), run in Node.

Each case copies the runtime into a fresh directory as an ES module and runs a script
there, so module state never leaks between cases. The browser pre-load object is set
the way an init script sets it: on globalThis before the module is imported."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig
from tests.conftest import REPO_ROOT

RUNTIME = REPO_ROOT / "src" / "shockharness" / "contracts" / "runtime"
NODE_TIMEOUT_SECONDS = 60


def node(tmp_path: Path, script: str, files: dict[str, str]) -> dict[str, object]:
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("node is required for the JavaScript runtime tests")
    shutil.copy(RUNTIME / "contracts.js", tmp_path / "contracts.mjs")
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    (tmp_path / "main.mjs").write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [executable, "main.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


THROWS = """
function throws(action) {
  try {
    action();
    return null;
  } catch (error) {
    return `${error.name}: ${error.message}`;
  }
}
"""


def test_identity_before_enable(tmp_path: Path) -> None:
    out = node(
        tmp_path,
        'import * as c from "./contracts.mjs";\n'
        "const value = {};\n"
        "const same = [c.requires(value, 'p'), c.produces(value, 'p'), c.preserves(value, {}),"
        " c.preserves_except(value, {}, 'p')].every((v) => v === value);\n"
        "console.log(JSON.stringify({ same, report: c.report() }));\n",
        {},
    )
    assert out == {"same": True, "report": {"mode": "off", "declarations": 4, "static_skips": {}}}


def test_enable_validation(tmp_path: Path) -> None:
    out = node(
        tmp_path,
        'import * as c from "./contracts.mjs";\n' + THROWS + "const results = {\n"
        "  notList: throws(() => c.enable('check', 'p')),\n"
        "  notStrings: throws(() => c.enable('check', [1])),\n"
        "  verify: throws(() => c.enable('verify', [])),\n"
        "  off: throws(() => c.enable('off', [])),\n"
        "  first: throws(() => c.enable('check', [])),\n"
        "  second: throws(() => c.enable('check', [])),\n"
        "};\nconsole.log(JSON.stringify(results));\n",
        {},
    )
    assert "array of strings" in str(out["notList"])
    assert "array of strings" in str(out["notStrings"])
    assert "verify mode" in str(out["verify"])
    assert "takes 'check'" in str(out["off"])
    assert out["first"] is None
    assert "already called" in str(out["second"])


def test_enable_after_a_declaration_throws(tmp_path: Path) -> None:
    out = node(
        tmp_path,
        'import * as c from "./contracts.mjs";\n' + THROWS + "c.produces({}, 'p');\n"
        "console.log(JSON.stringify({ late: throws(() => c.enable('check', [])) }));\n",
        {},
    )
    assert "after 1 declaration" in str(out["late"])


def test_check_mode(tmp_path: Path) -> None:
    out = node(
        tmp_path,
        'import * as c from "./contracts.mjs";\n' + THROWS + "c.enable('check', ['escaped']);\n"
        "const series = c.produces([1, 2], 'normalized');\n"
        "const kept = c.preserves({}, series);\n"
        "const narrowed = c.preserves_except({}, c.produces({}, 'a', 'b'), 'b');\n"
        "const text = c.produces('x', 'escaped');\n"
        "const results = {\n"
        "  satisfied: throws(() => c.requires(series, 'normalized')),\n"
        "  missing: throws(() => c.requires([1, 2], 'normalized')),\n"
        "  kept: throws(() => c.requires(kept, 'normalized')),\n"
        "  narrowedA: throws(() => c.requires(narrowed, 'a')),\n"
        "  narrowedB: throws(() => c.requires(narrowed, 'b')),\n"
        "  staticString: throws(() => c.requires(text, 'escaped')),\n"
        "  checkOnString: throws(() => c.produces('x', 'normalized')),\n"
        "  isError: (() => { try { c.requires({}, 'normalized'); } catch (e) {"
        " return e instanceof Error && e.property === 'normalized'"
        " && e.function === null; } })(),\n"
        "  report: c.report(),\n"
        "};\nconsole.log(JSON.stringify(results));\n",
        {},
    )
    assert out["satisfied"] is None and out["kept"] is None and out["narrowedA"] is None
    assert "does not carry 'normalized'" in str(out["missing"])
    assert "does not carry 'b'" in str(out["narrowedB"])
    assert out["staticString"] is None
    assert "cannot carry runtime properties" in str(out["checkOnString"])
    assert out["isError"] is True
    assert out["report"] == {
        "mode": "check",
        "declarations": 13,
        "static_skips": {"escaped": 2},
    }


def test_the_preload_object_enables_once_and_is_deleted(tmp_path: Path) -> None:
    out = node(
        tmp_path,
        THROWS + "globalThis.__shockharnessContracts = { mode: 'check', static: ['s'] };\n"
        'const c = await import("./contracts.mjs");\n'
        "console.log(JSON.stringify({\n"
        "  mode: c.report().mode,\n"
        "  deleted: !('__shockharnessContracts' in globalThis),\n"
        "  again: throws(() => c.enable('check', [])),\n"
        "  skipped: (c.produces('x', 's'), c.report().static_skips),\n"
        "}));\n",
        {},
    )
    assert out["mode"] == "check"
    assert out["deleted"] is True
    assert "already called" in str(out["again"])
    assert out["skipped"] == {"s": 1}


def test_a_bad_preload_object_throws_at_load_and_none_is_identity(tmp_path: Path) -> None:
    out = node(
        tmp_path,
        "globalThis.__shockharnessContracts = { mode: 'verbose', static: [] };\n"
        "let failure = null;\n"
        'try { await import("./contracts.mjs"); } catch (error) { failure = error.message; }\n'
        'const fresh = await import("./fresh.mjs");\n'
        "console.log(JSON.stringify({ failure, mode: fresh.mode }));\n",
        {
            # A second copy: Node caches the failed evaluation of the first. The object
            # was deleted by then, so this copy loads with nothing pending.
            "plain.mjs": (RUNTIME / "contracts.js").read_text(encoding="utf-8"),
            "fresh.mjs": (
                'import { report } from "./plain.mjs";\nexport const mode = report().mode;\n'
            ),
        },
    )
    assert "takes 'check', not 'verbose'" in str(out["failure"])
    assert out["mode"] == "off"


def test_enable_then_a_dynamic_import_works_and_a_static_import_first_does_not(
    tmp_path: Path,
) -> None:
    app = (
        'import { produces } from "./contracts.mjs";\n'
        "export const series = produces([1, 2], 'normalized');\n"
    )
    dynamic = node(
        tmp_path,
        'import { enable, requires } from "./contracts.mjs";\n'
        "enable('check', []);\n"
        'const { series } = await import("./app.mjs");\n'
        "requires(series, 'normalized');\n"
        "console.log(JSON.stringify({ ok: true }));\n",
        {"app.mjs": app},
    )
    assert dynamic == {"ok": True}
    separate = tmp_path / "hoisted"
    separate.mkdir()
    hoisted = node(
        separate,
        'import "./app.mjs";\nimport { enable } from "./contracts.mjs";\n'
        + THROWS
        + "console.log(JSON.stringify({ late: throws(() => enable('check', [])) }));\n",
        {"app.mjs": app},
    )
    assert "after 1 declaration" in str(hoisted["late"])  # the static import ran first


def test_both_runtime_files_pass_strict_as_production_code(
    strict_config: EffectiveConfig,
) -> None:
    options = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
    for name, language in (("contracts.js", "javascript"), ("contracts.d.ts", "typescript")):
        text = (RUNTIME / name).read_text(encoding="utf-8")
        result = analyze_text(f"static/js/{name}", language, text, strict_config, options)
        assert result.status == "analyzed"
        assert [(f.rule_id, f.span.line, f.message) for f in result.findings] == []
        assert "shockharness: ignore" not in text
