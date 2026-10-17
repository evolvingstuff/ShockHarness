"""H6 part two: PROV001 and GUARD001 compare the call sites of one function (spec 21.1
decisions 20, 21 and 29)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.rules import registry

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def project(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return analyze_paths([root], root, config, OPTIONS)


def rows(report: Any, rule: str) -> list[tuple[str, int]]:
    return [(f.path, f.span.line) for f in report.findings if f.rule_id == rule]


AGENT = {
    "app/__init__.py": "",
    "app/trace.py": (
        "import uuid\n\n\ndef record(run_id, step):\n    return (run_id, step)\n\n\n"
        "def new_trace_id():\n    return str(uuid.uuid4())\n"
    ),
    "app/store.py": (
        "class Store:\n    def start_run(self):\n        return 1\n\n"
        "    def create_run(self):\n        return 1\n\n\nstore = Store()\n"
    ),
    "app/agent.py": (
        "from uuid import uuid4\n\nfrom app.store import store\n"
        "from app.trace import new_trace_id, record\n\n\n"
        "def run_agent(step):\n    run = store.start_run()\n    record(run.id, step)\n\n\n"  # 9
        "def resume(step):\n    run_id = store.create_run().id\n    record(run_id, step)\n\n\n"
        "def quick(step):\n    record(str(uuid4()), step)\n\n\n"  # 18
        "def via_helper(step):\n    record(new_trace_id(), step)\n"  # 22
    ),
    "tests/test_agent.py": (
        "from uuid import uuid4\n\nfrom app.trace import record\n\n\n"
        "def test_record():\n    assert record(str(uuid4()), 1)\n"
    ),
}


def test_prov001_reports_made_up_identifiers(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = project(empty_root, strict_config, AGENT)
    assert rows(report, "PROV001") == [("app/agent.py", 18), ("app/agent.py", 22)]
    message = next(f.message for f in report.findings if f.rule_id == "PROV001")
    assert message.startswith(
        "argument 'run_id' of record(...) is a freshly made uuid.uuid4() here, while 2 other "
        "call site(s) pass an identifier the program issued"
    )
    finding = next(f for f in report.findings if f.rule_id == "PROV001")
    assert (finding.severity, finding.confidence) == ("review", "approximate")
    assert registry.category_of("PROV001") == "contract_integrity"


def test_prov001_needs_an_issued_site(empty_root: Path, strict_config: EffectiveConfig) -> None:
    files = {
        "a.js": (
            'import { v4 as uuidv4 } from "uuid";\n'
            "export function record(runId) { return runId; }\n"
            "export function a() { return record(uuidv4()); }\n"
            "export function b() { return record(crypto.randomUUID()); }\n"
        ),
    }
    assert rows(project(empty_root, strict_config, files), "PROV001") == []
    files["a.js"] += "export function c(store) { return record(store.createRun().id); }\n"
    assert rows(project(empty_root, strict_config, files), "PROV001") == [("a.js", 3), ("a.js", 4)]


NOTES = (
    "export function hasNoteHash(id) { return id.length > 0; }\n"
    "export function removeNoteHash(id) { hashes.delete(id); }\n"  # no check of its own
    "export function a(id) { if (hasNoteHash(id)) { removeNoteHash(id); } }\n"
    "export function b(id) { if (!hasNoteHash(id)) return; removeNoteHash(id); }\n"
    "export function c(note) {\n"
    '  if (!hasNoteHash(note.id)) { throw new Error("missing"); }\n'
    "  removeNoteHash(note.id);\n"
    "}\n"
    "export function d(id) { removeNoteHash(id); }\n"  # 9
    "export function e(id, other) { if (hasNoteHash(other)) { removeNoteHash(id); } }\n"  # 10
)


def test_guard001_reports_the_unguarded_minority(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    report = project(empty_root, make_config(""), {"notes.js": NOTES})
    # a, b, c are guarded on the same argument; d is not, and e checks another value
    assert rows(report, "GUARD001") == []  # 3 of 5 sites guarded: below 75 percent
    relaxed = make_config("[tool.shockharness.rules.consistency]\nguard_min_percent = 60\n")
    report = project(empty_root, relaxed, {})
    assert rows(report, "GUARD001") == [("notes.js", 9), ("notes.js", 10)]
    message = next(f.message for f in report.findings if f.rule_id == "GUARD001")
    assert message.startswith(
        "removeNoteHash(id) runs without a check of its argument, while 3 of 5 call sites of "
        "removeNoteHash(...) check it first (most often hasNoteHash(id))"
    )


def test_guard001_python_and_thresholds(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = (
        "def has(key):\n    return bool(key)\n\n\ndef drop(key):\n    return key\n\n\n"
        "def a(k):\n    if has(k):\n        drop(k)\n\n\n"
        "def b(k):\n    if not has(k):\n        raise KeyError(k)\n    drop(k)\n\n\n"
        "def c(k):\n    assert has(k)\n    drop(k)\n\n\n"
        "def d(k):\n    if has(k) and k:\n        drop(k)\n\n\n"
        "def e(k):\n    drop(k)\n\n\n"  # 31
        "def f(k):\n    if valid(k):\n        drop(k)\n"  # another check: guarded
    )
    report = project(empty_root, make_config(""), {"src/keys.py": text})
    assert rows(report, "GUARD001") == [("src/keys.py", 31)]  # 5 of 6 sites check k
    strict = make_config("[tool.shockharness.rules.consistency]\nguard_min_sites = 7\n")
    assert rows(project(empty_root, strict, {}), "GUARD001") == []
    assert any("guard_min_sites is 7 (strict: 3)" in d for d in strict.deviations)


def test_guard001_skips_a_callee_that_checks_its_argument(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    # MetaList: note_tags_include raises on the check its callers make first.
    checked = (
        "def note_tags_include(tags, tag):\n"
        '    """Whether tags lists tag."""\n'
        "    if not isinstance(tags, str):\n"
        "        raise TypeError(tags)\n"
        "    return tag in tags.split()\n\n\n"
    )
    unchecked = "def includes(tags, tag):\n    return tag in tags.split()\n\n\n"
    sites = (
        "".join(
            f"def site{i}(tags):\n    if isinstance(tags, str):\n"
            "        {callee}(tags, 'a')\n\n\n"
            for i in range(4)
        )
        + "def bare(tags):\n    {callee}(tags, 'a')\n"
    )
    files = {"src/tags.py": checked + sites.format(callee="note_tags_include")}
    assert rows(project(empty_root, strict_config, files), "GUARD001") == []
    other = empty_root / "other"
    other.mkdir()
    files = {"src/tags.py": unchecked + sites.format(callee="includes")}
    assert rows(project(other, strict_config, files), "GUARD001") == [("src/tags.py", 26)]
    js = (
        "function show(note) {\n  if (!isNote(note)) {\n    throw new TypeError('note');\n  }\n"
        "  return note;\n}\n"
        + "".join(f"export function s{i}(n) {{\n  if (isNote(n)) show(n);\n}}\n" for i in range(4))
        + "export function bare(n) {\n  show(n);\n}\n"
    )
    third = empty_root / "third"
    third.mkdir()
    assert rows(project(third, strict_config, {"src/notes.js": js}), "GUARD001") == []
