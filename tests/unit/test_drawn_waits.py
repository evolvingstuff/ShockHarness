"""ASYNC004: a gated command waits on the page being drawn."""

from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import ConfigError, load_config

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
HEADER = '[tool.shockharness]\nprofile = "strict"\ninclude = ["web/**"]\n'
GATES = (
    "[tool.shockharness.rules.async_lifecycle]\n"
    'gates = ["navigator.locks.request:last", "CommandGate.run:1"]\n'
)
GATE = "export const CommandGate = { run(name, fn) { return fn(); } };\n"
# MetaList's shape before its fix: a service awaits the slide, the command awaits the service.
SLIDE = """export async function slide(el) {
  const animations = el.getAnimations();
  await Promise.all(animations.map((a) => a.finished));
}
"""
KEYS = """import { slide } from './slide.js';
import { CommandGate } from './gate.js';
async function navigate(el) {
  await slide(el);
}
export function onKey(el) {
  CommandGate.run('keyboard.nav', () => navigate(el));
  CommandGate.run('keyboard.back', async () => {
    await navigate(el);
  });
  CommandGate.run('keyboard.other', async () => {
    await other();
  });
}
async function other() {
  return 0;
}
"""


def found(root: Path, files: dict[str, str], config: str = HEADER + GATES) -> list[str]:
    for name, text in {".shockharness.toml": config, "web/gate.js": GATE, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [
        f"{f.path}:{f.span.line} {f.confidence} {f.message}"
        for f in report.findings
        if f.rule_id == "ASYNC004"
    ]


def test_one_finding_at_the_await_names_every_command_that_reaches_it(tmp_path: Path) -> None:
    assert found(tmp_path, {"web/slide.js": SLIDE, "web/keys.js": KEYS}) == [
        "web/slide.js:3 exact awaits Promise.all(animations.map((a) => a.finished)), which a "
        "page that is not drawn does not settle, while a gated command runs: 2 command(s) "
        "wait on it and hold the gate meanwhile: 'keyboard.nav' (web/keys.js:7), "
        "'keyboard.back' (web/keys.js:8)"
    ]


def test_a_wait_nothing_holds_the_gate_for_is_not_reported(tmp_path: Path) -> None:
    # The fix: the slide is not awaited, so the command returns at once.
    fixed = """export function slide(el) {
  const animations = el.getAnimations();
  void Promise.all(animations.map((a) => a.finished)).then(() => el.remove());
}
"""
    keys = KEYS.replace("await slide(el);", "slide(el);")
    assert found(tmp_path, {"web/slide.js": fixed, "web/keys.js": keys}) == []


def test_without_a_configured_gate_nothing_is_reported(tmp_path: Path) -> None:
    files = {"web/slide.js": SLIDE, "web/keys.js": KEYS}
    assert found(tmp_path, files, HEADER) == []


def test_web_locks_need_no_configuration_and_their_callback_is_the_last_argument(
    tmp_path: Path,
) -> None:
    locks = """export function save(el) {
  navigator.locks.request('save', async () => {
    await el.animate([], 100).finished;
  });
  navigator.locks.request('save', { mode: 'shared' }, async () => {
    const done = el.animate([], 100).finished;
    await done;
  });
}
"""
    lines = [line.split(" ")[0] for line in found(tmp_path, {"web/locks.js": locks}, HEADER)]
    assert lines == ["web/locks.js:3", "web/locks.js:7"]


def test_returned_and_chained_waits_and_typescript(tmp_path: Path) -> None:
    fade = """export function fade(el: HTMLElement): Promise<void> {
  return el.animate([], 100).finished.then(() => undefined);
}
"""
    keys = """import { fade } from './fade';
import { CommandGate } from './gate.js';
export function onKey(el: HTMLElement): void {
  CommandGate.run('keyboard.fade', () => fade(el));
}
"""
    lines = [
        line.split(" ")[0] for line in found(tmp_path, {"web/fade.ts": fade, "web/keys.ts": keys})
    ]
    assert lines == ["web/fade.ts:2"]


def test_a_value_named_finished_is_not_a_drawn_wait(tmp_path: Path) -> None:
    keys = """import { CommandGate } from './gate.js';
export function onKey(job) {
  CommandGate.run('keyboard.save', async () => {
    await save(job.finished);
    return job.finished ? 1 : 0;
  });
}
async function save(done) {
  return done;
}
"""
    assert found(tmp_path, {"web/keys.js": keys}) == []


@pytest.mark.parametrize("entry", ["CommandGate.run", "CommandGate.run:first", "run(1)"])
def test_a_gate_is_callee_and_index(tmp_path: Path, entry: str) -> None:
    config = HEADER + f'[tool.shockharness.rules.async_lifecycle]\ngates = ["{entry}"]\n'
    (tmp_path / ".shockharness.toml").write_text(config, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_config(tmp_path, None)
    assert "rules.async_lifecycle.gates[0]" in str(raised.value)


def test_removing_the_built_in_gate_is_a_deviation(tmp_path: Path) -> None:
    config = HEADER + "[tool.shockharness.rules.async_lifecycle]\ngates = []\n"
    (tmp_path / ".shockharness.toml").write_text(config, encoding="utf-8")
    deviations = load_config(tmp_path, None).deviations
    assert any("async_lifecycle.gates" in line for line in deviations)
