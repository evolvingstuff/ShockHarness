"""The content-hash cache (0.3.0 brief, item 3): codec round trips, keys, invalidation,
corruption, bypass, and the acceptance criteria of docs/shockharness-suggestions-3.md."""

import json
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from shockharness.analysis import (
    CACHE_BYPASSED,
    CACHE_CONFIGURED,
    AnalysisOptions,
    PendingFile,
    pending_from_plain,
    pending_to_plain,
    prepare_text,
)
from shockharness.api import analyze_paths
from shockharness.cache.codec import CacheEntryError, from_plain, to_plain
from shockharness.cache.store import (
    ENTRIES_DIRNAME,
    INDEX_FILENAME,
    TAG_FILENAME,
    FileCache,
    cache_directory,
    open_cache,
)
from shockharness.config import EffectiveConfig, load_config
from shockharness.discovery import discover
from shockharness.ir.javascript import extract_javascript_facts
from shockharness.ir.model import ControlNode
from shockharness.ir.python import extract_python_facts
from shockharness.output import json as json_output
from shockharness.source import SourceText
from tests.conftest import REPO_ROOT, without_cache_block

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
NO_CACHE = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rendered(root: Path, config: EffectiveConfig, options: AnalysisOptions) -> str:
    return json_output.render(analyze_paths([root / "src"], root, config, options))


def cache_block(rendered_json: str) -> dict[str, object]:
    return json.loads(rendered_json)["coverage"]["cache"]


# --- codec -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "src/shockharness/ir/python_catches.py",
        "src/shockharness/complexity/callgraph.py",
        "src/shockharness/cli.py",
        "tests/fixtures/javascript/def_logical_or.js",
    ],
)
def test_prepared_files_round_trip_through_the_codec(
    strict_config: EffectiveConfig, relative: str
) -> None:
    path = REPO_ROOT / relative
    if not path.is_file():
        pytest.skip(f"{relative} is not in this checkout")
    language = "python" if relative.endswith(".py") else "javascript"
    pending = prepare_text(relative, language, path.read_text(encoding="utf-8"), strict_config)
    plain = pending_to_plain(pending)
    text = json.dumps(plain, sort_keys=True)  # must be plain JSON
    rebuilt = pending_from_plain(json.loads(text))
    assert rebuilt == replace(pending, source=None)
    assert isinstance(rebuilt, PendingFile)


def test_codec_handles_every_scalar_shape_and_deep_control_trees() -> None:
    py = SourceText.from_text("x = 1j\ny = -2.5\nz = 3\nw = 1e400\n")
    facts = extract_python_facts(py, "a.py")
    assert from_plain(type(facts), json.loads(json.dumps(to_plain(facts))), "f") == facts
    deep = "function f() {\n" + "if (a) {\n" * 300 + "x();\n" + "}\n" * 300 + "}\n"
    js_facts = extract_javascript_facts(SourceText.from_text(deep), "deep.js")
    plain = json.loads(json.dumps(to_plain(js_facts)))
    rebuilt = from_plain(type(js_facts), plain, "deep")
    # dataclass equality recurses once per nesting level (past 3.11's limit on this
    # tree); the flattened forms, produced iteratively, are compared instead
    assert to_plain(rebuilt) == plain
    tree = rebuilt.functions[1].control
    assert isinstance(tree, ControlNode)
    deepest = 0
    stack: list[tuple[ControlNode, int]] = [(tree, 0)]
    while len(stack) > 0:
        node, depth = stack.pop()
        deepest = max(deepest, depth)
        stack.extend((child, depth + 1) for child in node.children)
    assert deepest >= 300


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"line": 1, "column": 1, "end_line": 1}, "fields of Span do not match"),
        ({"line": "1", "column": 1, "end_line": 1, "end_column": 2}, "expected an integer"),
        ({"line": True, "column": 1, "end_line": 1, "end_column": 2}, "expected an integer"),
        ([1, 1, 1, 2], "expected an object"),
    ],
)
def test_codec_rejects_malformed_entries(data: object, message: str) -> None:
    from shockharness.ir.model import Span

    with pytest.raises(CacheEntryError, match=message):
        from_plain(Span, data, "span")
    with pytest.raises(CacheEntryError, match="inconsistent control tree"):
        from_plain(ControlNode, {"__control__": [["block", 2, 0, 0, "", False]]}, "c")
    with pytest.raises(CacheEntryError, match="no member of the union"):
        from_plain(str | None, 3, "u")


# --- acceptance -------------------------------------------------------------------------------


def test_second_run_is_identical_and_every_file_is_a_hit(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/b.js", "const y = 3;\n")
    write(empty_root, "src/c.py", "def f(:\n")  # a parse failure is a per-file result too
    cold = rendered(empty_root, strict_config, OPTIONS)
    warm = rendered(empty_root, strict_config, OPTIONS)
    assert without_cache_block(cold) == without_cache_block(warm)
    assert cache_block(cold) == {
        "status": "enabled",
        "directory": ".shockharness-cache",
        "reason": "per-file results are read from and written to the cache directory",
        "hits": 0,
        "misses": 3,
        "invalidated": 0,
        "errors": 0,
        "problems": [],
    }
    assert cache_block(warm)["hits"] == 3 == json.loads(warm)["execution_summary"]["files"]
    assert cache_block(warm)["misses"] == 0
    directory = empty_root / ".shockharness-cache"
    assert (directory / TAG_FILENAME).is_file() and (directory / INDEX_FILENAME).is_file()
    assert len(list((directory / ENTRIES_DIRNAME).rglob("*.json"))) == 3
    # the cache directory is never analyzed, whatever include says, and is not counted at
    # all (like .git): discovery over the root is identical between a cold and a warm run
    assert (
        discover(empty_root, [empty_root], strict_config).counts_json()
        == (json.loads(cold)["coverage"]["discovery"])
    )


def test_changing_one_file_reanalyzes_only_that_file(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/b.py", "y = 3\n")
    rendered(empty_root, strict_config, OPTIONS)
    write(empty_root, "src/b.py", "y = 4\n")
    changed = rendered(empty_root, strict_config, OPTIONS)
    block = cache_block(changed)
    assert (block["hits"], block["misses"], block["invalidated"]) == (1, 1, 1)
    assert [f["message"] for f in json.loads(changed)["findings"]] == [
        "Numeric literal 2 has no permitted justification in executable code",
        "Numeric literal 4 has no permitted justification in executable code",
    ]
    # the same bytes under a new path are a miss: the key includes the path's entry
    write(empty_root, "src/c.py", "x = 2\n")
    again = cache_block(rendered(empty_root, strict_config, OPTIONS))
    assert (again["hits"], again["misses"]) == (2, 1)


def test_config_tool_version_and_host_changes_invalidate_everything(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/b.py", "y = 3\n")
    strict = load_config(empty_root, None)
    rendered(empty_root, strict, OPTIONS)
    # another effective configuration: a new digest, every entry invalidated
    relaxed = make_config("[tool.shockharness.rules.magic_numbers]\nallowed_values = [0, 1, 2]\n")
    assert relaxed.digest != strict.digest
    block = cache_block(rendered(empty_root, relaxed, OPTIONS))
    assert (block["hits"], block["misses"], block["invalidated"]) == (0, 2, 2)
    assert cache_block(rendered(empty_root, relaxed, OPTIONS))["hits"] == 2
    # another tool version: the index header differs, every entry invalidated
    index = empty_root / ".shockharness-cache" / INDEX_FILENAME
    header = json.loads(index.read_text(encoding="utf-8"))
    index.write_text(json.dumps({**header, "tool_version": "0.0.0"}), encoding="utf-8")
    block = cache_block(rendered(empty_root, relaxed, OPTIONS))
    assert (block["hits"], block["misses"], block["invalidated"]) == (0, 2, 2)
    # another host interpreter or grammar: the same
    index.write_text(json.dumps({**header, "host": "other"}), encoding="utf-8")
    block = cache_block(rendered(empty_root, relaxed, OPTIONS))
    assert (block["hits"], block["misses"], block["invalidated"]) == (0, 2, 2)
    # the cache table itself is not part of the digest, so moving the cache keeps baselines
    moved = make_config(
        "[tool.shockharness.rules.magic_numbers]\nallowed_values = [0, 1, 2]\n"
        '[tool.shockharness.cache]\ndirectory = "elsewhere/cache"\n'
    )
    assert moved.digest == relaxed.digest
    block = cache_block(rendered(empty_root, moved, OPTIONS))
    assert block["directory"] == "elsewhere/cache" and block["misses"] == 2
    assert (empty_root / "elsewhere" / "cache" / INDEX_FILENAME).is_file()


def test_no_cache_bypasses_and_disabled_config_never_touches_the_directory(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    strict = load_config(empty_root, None)
    bypassed = rendered(empty_root, strict, NO_CACHE)
    assert cache_block(bypassed)["status"] == "bypassed"
    assert cache_block(bypassed)["reason"] == "--no-cache"
    assert not (empty_root / ".shockharness-cache").exists()
    disabled_config = make_config("[tool.shockharness.cache]\nenabled = false\n")
    disabled = rendered(empty_root, disabled_config, OPTIONS)
    assert cache_block(disabled)["status"] == "disabled"
    assert cache_block(disabled)["reason"] == "cache.enabled = false"
    assert not (empty_root / ".shockharness-cache").exists()
    assert "cache.enabled" not in " ".join(disabled_config.deviations)  # not a policy change
    rendered(empty_root, strict, OPTIONS)
    warm = rendered(empty_root, strict, OPTIONS)
    assert cache_block(warm)["hits"] == 1
    assert without_cache_block(bypassed) == without_cache_block(warm)
    # the disabled run has another configuration source (a dedicated file), so only the
    # analysis itself is compared
    assert json.loads(disabled)["findings"] == json.loads(bypassed)["findings"]
    assert json.loads(disabled)["files"] == json.loads(bypassed)["files"]


def test_corrupt_index_or_entry_is_reported_once_and_analysis_is_complete(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/b.py", "y = 3\n")
    cold = rendered(empty_root, strict_config, OPTIONS)
    directory = empty_root / ".shockharness-cache"
    (directory / INDEX_FILENAME).write_text("{not json", encoding="utf-8")
    rebuilt = rendered(empty_root, strict_config, OPTIONS)
    block = cache_block(rebuilt)
    assert without_cache_block(rebuilt) == without_cache_block(cold)
    assert block["errors"] == 1 and block["invalidated"] == 2 and block["misses"] == 2
    assert block["problems"] == [
        "index.json is not valid JSON (Expecting property name enclosed in double quotes: "
        "line 1 column 2 (char 1)); it was ignored"
    ]
    assert json.loads(rebuilt)["analysis_status"] == "complete"
    # the cache works again afterwards
    assert cache_block(rendered(empty_root, strict_config, OPTIONS))["hits"] == 2
    # one corrupt entry: counted once, that file analyzed afresh, the other a hit
    entries = sorted((directory / ENTRIES_DIRNAME).rglob("*.json"))
    entries[0].write_bytes(b"\xff\xfe")
    document = json.loads(entries[1].read_text(encoding="utf-8"))
    document["pending"]["line_count"] = "many"
    entries[1].write_text(json.dumps(document), encoding="utf-8")
    broken = rendered(empty_root, strict_config, OPTIONS)
    block = cache_block(broken)
    assert without_cache_block(broken) == without_cache_block(cold)
    assert (block["hits"], block["misses"], block["errors"]) == (0, 2, 2)
    assert any("is not valid UTF-8" in p for p in block["problems"])
    assert any(
        "could not be decoded (pending.line_count: expected an integer)" in p
        for p in block["problems"]
    )
    assert cache_block(rendered(empty_root, strict_config, OPTIONS))["hits"] == 2
    # a wrong shape and an index of the wrong shape
    entries[0].write_text(json.dumps({"unexpected": 1}), encoding="utf-8")
    (directory / INDEX_FILENAME).write_text(json.dumps({"schema_version": "1"}), encoding="utf-8")
    block = cache_block(rendered(empty_root, strict_config, OPTIONS))
    assert block["problems"] == [
        "index.json does not have the expected shape; the cache was rebuilt"
    ]
    assert block["invalidated"] == 2


def test_text_output_reports_the_cache(empty_root: Path, strict_config: EffectiveConfig) -> None:
    from shockharness.output import text as text_output

    write(empty_root, "src/a.py", "x = 2\n")
    analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    out = text_output.render(report)
    assert "  cache: .shockharness-cache: 1 hit(s), 0 miss(es), 0 invalidated, 0 error(s)\n" in out
    bypassed = text_output.render(
        analyze_paths([empty_root / "src"], empty_root, strict_config, NO_CACHE)
    )
    assert "  cache: bypassed (--no-cache)\n" in bypassed


def test_cache_directory_resolves_against_the_root_and_discovery_skips_it(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config('[tool.shockharness.cache]\ndirectory = "build/cache"\n')
    assert cache_directory(empty_root, config) == empty_root / "build" / "cache"
    absolute = make_config(f'[tool.shockharness.cache]\ndirectory = "{empty_root / "abs"}"\n')
    assert cache_directory(empty_root, absolute) == empty_root / "abs"
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "build/cache/entries/ab/x.py", "y = 3\n")  # a .py inside the cache dir
    result = discover(empty_root, [empty_root], config)
    assert [f.relative for f in result.files] == ["src/a.py"]
    assert "cache" not in json.dumps(result.counts_json())


def test_unwritable_cache_directory_is_a_counted_problem_not_a_failure(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, ".shockharness-cache", "a file where the directory should be\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    block = report.coverage["cache"]
    assert block["status"] == "enabled" and block["errors"] >= 1
    assert any("could not be created" in p for p in block["problems"])
    assert report.analysis_status == "complete"
    assert [f.message for f in report.findings] == [
        "Numeric literal 2 has no permitted justification in executable code"
    ]


def test_store_is_inert_before_open_and_open_cache_opens(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    cache = FileCache(empty_root / "c", "c", strict_config.digest)
    cache.store("a.py", "python", b"x = 2\n", {"pending": 1})
    assert not (empty_root / "c").exists()  # nothing is written before open()
    opened = open_cache(empty_root, strict_config)
    assert opened.writable and (empty_root / ".shockharness-cache" / INDEX_FILENAME).is_file()


@pytest.mark.slow
def test_warm_run_over_the_repository_is_at_most_half_the_cold_run(tmp_path: Path) -> None:
    """A sanity bound, not a benchmark: the repository's own src/ and tests/ with a fresh
    cache directory under tmp_path."""
    base = load_config(REPO_ROOT, None)
    config = replace(
        base, values={**base.values, "cache": {"enabled": True, "directory": str(tmp_path / "c")}}
    )
    targets = [REPO_ROOT / "src", REPO_ROOT / "tests"]
    started = time.perf_counter()
    cold = json_output.render(analyze_paths(targets, REPO_ROOT, config, OPTIONS))
    cold_seconds = time.perf_counter() - started
    started = time.perf_counter()
    warm = json_output.render(analyze_paths(targets, REPO_ROOT, config, OPTIONS))
    warm_seconds = time.perf_counter() - started
    assert without_cache_block(cold) == without_cache_block(warm)
    block = cache_block(warm)
    assert block["misses"] == 0 and block["hits"] == json.loads(warm)["execution_summary"]["files"]
    assert warm_seconds <= cold_seconds / 2, (cold_seconds, warm_seconds)
