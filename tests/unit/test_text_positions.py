"""DOM003: a selection saved as text positions and found again through text nodes only."""

from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from shockharness.loosening import loosenings

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CONFIG = '[tool.shockharness]\nprofile = "strict"\ninclude = ["web/**/*.js", "web/**/*.ts"]\n'

POSITIONS = """
export function offsetOf(root, node, offset) {
    const range = document.createRange();
    range.setStart(root, 0);
    range.setEnd(node, offset);
    return range.toString().length;
}

export function pointAt(root, position) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let consumed = 0;
    for (let n = walker.nextNode(); n !== null; n = walker.nextNode()) {
        if (position <= consumed + n.data.length) return { node: n, offset: position - consumed };
        consumed += n.data.length;
    }
    return null;
}

function placeCaret(root, position) {
    const p = pointAt(root, position);
    window.getSelection().collapse(p.node, p.offset);
}

export function redraw(root, render) {
    const sel = window.getSelection();
    const caret = offsetOf(root, sel.focusNode, sel.focusOffset);
    render();
    placeCaret(root, caret);
}

export function countWords(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let words = 0;
    while (walker.nextNode()) words += 1;
    return words;
}
"""

MENU = """
import { offsetOf, pointAt } from './positions.js';

const state = { saved: null };

export function remember(root) {
    const r = window.getSelection().getRangeAt(0);
    state.saved = { from: offsetOf(root, r.startContainer, r.startOffset) };
}

export function restore(root) {
    return pointAt(root, state.saved.from);
}

export function clickedAt(root, point) {
    if (point.node.nodeType === Node.TEXT_NODE) {
        return pointAt(root, offsetOf(root, point.node, point.offset));
    }
    return null;
}
"""


def found(root: Path, files: dict[str, str], config: str = CONFIG) -> list[str]:
    for name, text in {".shockharness.toml": config, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return sorted(
        f"{f.path}:{f.span.line} {f.severity} {f.message.split(':')[0]}"
        for f in report.findings
        if f.rule_id == "DOM003" and f.suppression is None
    )


def test_round_trips_through_a_wrapper_and_through_a_property_across_files(tmp_path: Path) -> None:
    files = {"web/positions.js": POSITIONS, "web/menu.js": MENU}
    assert found(tmp_path, files) == [
        "web/menu.js:12 review pointAt finds a point again by walking text nodes only, from "
        "the property from, which this file sets to a text position",
        "web/positions.js:28 review placeCaret finds a point again by walking text nodes "
        "only, from offsetOf(...)",
    ]


def test_typescript_parameters_and_imports_without_an_extension(tmp_path: Path) -> None:
    typed = POSITIONS.replace("(root, node, offset)", "(root: Node, node: Node, offset: number)")
    typed = typed.replace(
        "function pointAt(root, position)", "function pointAt(root: Node, position: number)"
    )
    menu = MENU.replace("'./positions.js'", "'./positions'")
    lines = [
        line.split(" ")[0]
        for line in found(tmp_path, {"web/positions.ts": typed, "web/menu.ts": menu})
    ]
    assert lines == ["web/menu.ts:12", "web/positions.ts:28"]


def test_a_point_tested_as_a_text_node_is_exact(tmp_path: Path) -> None:
    files = {"web/positions.js": POSITIONS, "web/menu.js": MENU}
    assert not any(line.startswith("web/menu.js:17") for line in found(tmp_path, files))


def test_object_methods_a_hand_written_walk_and_a_method_call(tmp_path: Path) -> None:
    # medium-editor's shape: object-literal methods, the position kept by assignment, and
    # a walk that tests nodeType instead of a SHOW_TEXT walker.
    selection = """
var Selection = {
    exportSelection: function (root, doc) {
        var range = doc.getSelection().getRangeAt(0), before = range.cloneRange(), start;
        before.selectNodeContents(root);
        before.setEnd(range.startContainer, range.startOffset);
        start = before.toString().length;
        return { start: start, end: start + range.toString().length };
    },
    importSelection: function (state, root, doc) {
        var index = 0, stack = [root], node;
        while ((node = stack.pop())) {
            if (node.nodeType === 3 && state.start >= index) {
                index += node.length;
            }
        }
        return index;
    },
    restore: function (root, doc) {
        this.importSelection(this.exportSelection(root, doc), root, doc);
    },
};
"""
    lines = [line.split(" ")[0] for line in found(tmp_path, {"web/selection.js": selection})]
    assert lines == ["web/selection.js:20"]


def test_a_decoder_given_other_numbers_is_fine(tmp_path: Path) -> None:
    other = """
import { pointAt } from './positions.js';

export function atStart(root) {
    return pointAt(root, 0);
}

export function atSearchHit(root, text, word) {
    return pointAt(root, text.indexOf(word));
}
"""
    assert found(tmp_path, {"web/positions.js": POSITIONS, "web/other.js": other}) == [
        "web/positions.js:28 review placeCaret finds a point again by walking text nodes "
        "only, from offsetOf(...)"
    ]


def test_a_text_only_place_takes_a_reasoned_suppression(tmp_path: Path) -> None:
    menu = MENU.replace(
        "    return pointAt(root, state.saved.from);",
        "    return pointAt(root, state.saved.from);"
        '  // shockharness: ignore[DOM003] reason="the title field holds text only"',
    )
    lines = found(tmp_path, {"web/positions.js": POSITIONS, "web/menu.js": menu})
    assert [line.split(" ")[0] for line in lines] == ["web/positions.js:28"]


def test_the_severity_setting_and_its_loosening(tmp_path: Path) -> None:
    files = {"web/positions.js": POSITIONS}
    warning = CONFIG + '\n[tool.shockharness.rules.dom]\ndom003_severity = "warning"\n'
    assert [line.split(" ")[1] for line in found(tmp_path, files, warning)] == ["warning"]
    before = load_config(tmp_path, None)
    (tmp_path / ".shockharness.toml").write_text(CONFIG, encoding="utf-8")
    after = load_config(tmp_path, None)
    found_keys = [
        item.key
        for item in loosenings(before.values, before.deviations, after.values, after.deviations)
    ]
    assert found_keys == ["rules.dom.dom003_severity"]
