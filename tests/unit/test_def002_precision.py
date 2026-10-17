"""0.5.0 DEF002 precision (docs/shockharness-suggestions-4.md items 1-6): decorators,
checked-then-raised lookups, discarded removals, the grouping idiom, remediation, and
unknown findings under the recommended profile."""

from collections.abc import Callable
from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.findings import STATUS_UNKNOWN
from shockharness.ir.model import KIND_DISCARDED_REMOVAL
from shockharness.ir.python import extract_python_facts
from shockharness.rules import registry
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def run(config: EffectiveConfig, text: str) -> FileResult:
    return analyze_text("t.py", "python", text, config, OPTIONS)


def def002(result: FileResult) -> list[tuple[int, str]]:
    return [(f.span.line, f.severity) for f in result.findings if f.rule_id == "DEF002"]


def test_get_used_as_a_decorator_is_not_a_lookup(strict_config: EffectiveConfig) -> None:
    text = (
        "@router.get('/notes/x')\ndef a():\n    return OK\n\n\n"
        "@app.get('/x', status_code=OK)\ndef b():\n    return OK\n\n\n"
        "class Api:\n    @client.get('/x')\n    def c(self):\n        return OK\n\n\n"
        "@retry(times=config.get('retries', DEFAULT))\ndef d():\n    return OK\n\n\n"
        "value = router.get('/x')\n"
    )
    assert def002(run(strict_config, text)) == [(17, "error"), (22, "review")]


def test_a_lookup_checked_and_raised_on_the_next_statement_is_not_reported(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "table: dict = {}\n\n\n"
        "def a(key):\n"
        "    record = table.get(key)\n"
        "    if record is None:\n"
        "        raise KeyError(key)\n"
        "    return record\n\n\n"
        "def b(obj):\n"
        "    handler = getattr(obj, 'handle', None)\n"
        "    if not callable(handler):\n"
        "        raise TypeError('no handler')\n"
        "    return handler\n\n\n"
        "def c(key):\n"
        "    found = table.get(key, None)\n"
        "    if found is None or found.closed:\n"
        "        raise LookupError(key)\n"
        "    return found\n\n\n"
        "def d(obj):\n"
        "    item = getattr(obj, 'item', None)\n"
        "    if not isinstance(item, Item):\n"
        "        raise TypeError('item')\n"
        "    return item\n"
    )
    assert def002(run(strict_config, text)) == []


def test_a_lookup_not_strictly_checked_and_raised_is_still_reported(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "table: dict = {}\n\n\n"
        "def between(key):\n"
        "    record = table.get(key)\n"
        "    log(key)\n"
        "    if record is None:\n"
        "        raise KeyError(key)\n"
        "    return record\n\n\n"
        "def with_else(obj):\n"
        "    handler = getattr(obj, 'handle', None)\n"
        "    if not callable(handler):\n"
        "        raise TypeError('no handler')\n"
        "    else:\n"
        "        log(obj)\n"
        "    return handler\n\n\n"
        "def returns(key):\n"
        "    record = table.get(key)\n"
        "    if record is None:\n"
        "        return EMPTY\n"
        "    return record\n\n\n"
        "def fallback(key):\n"
        "    record = table.get(key, {})\n"
        "    if record is None:\n"
        "        raise KeyError(key)\n"
        "    return record\n"
    )
    assert def002(run(strict_config, text)) == [
        (5, "review"),
        (13, "error"),
        (22, "review"),
        (29, "error"),
    ]


def test_a_discarded_pop_with_none_is_a_review_finding_of_its_own_kind(
    strict_config: EffectiveConfig,
) -> None:
    text = (
        "cache: dict = {}\n"
        "cache.pop(KEY, None)\n"
        "other.pop(KEY, None)\n"
        "value = cache.pop(KEY, None)\n"
        "cache.pop(KEY, 0)\n"
    )
    result = run(strict_config, text)
    assert def002(result) == [(2, "review"), (3, "review"), (4, "error"), (5, "error")]
    first, second = (f for f in result.findings if f.span.line in (2, 3))
    assert "use del cache[KEY]" in first.message
    assert second.status == STATUS_UNKNOWN  # the receiver is not proven a mapping
    facts = extract_python_facts(SourceText.from_text(text), "t.py")
    kinds = {fact.span.line: fact.kind for fact in facts.defaults}
    assert kinds[2] == KIND_DISCARDED_REMOVAL and kinds[4] != KIND_DISCARDED_REMOVAL


def test_the_grouping_idiom_is_not_a_fallback(strict_config: EffectiveConfig) -> None:
    text = (
        "groups: dict = {}\n"
        "groups.setdefault(KEY, set()).add(VALUE)\n"
        "groups.setdefault(KEY, []).append(VALUE)\n"
        "groups.setdefault(KEY, {})[CHILD] = VALUE\n"
        "n = groups.setdefault(KEY, 0)\n"
        "groups.setdefault(KEY, {'a'}).add(VALUE)\n"
        "x = groups.setdefault(KEY, []).copy()\n"
    )
    assert def002(run(strict_config, text)) == [(5, "error"), (6, "error"), (7, "error")]


def test_the_grouping_idiom_with_the_container_named_first(
    strict_config: EffectiveConfig,
) -> None:
    # Under-the-gate round 3: `reasons = shared.setdefault(k, set())` then
    # `reasons.add(key)` is the same idiom; it was flagged and rewritten as a
    # membership check.
    text = (
        "def merge(shared: dict, keys: list, kept: int) -> None:\n"
        "    for key in keys:\n"
        "        reasons = shared.setdefault(kept, set())\n"  # 3: mutated next: exempt
        "        reasons.add(key)\n"
        "        rows = shared.setdefault(key, [])\n"  # 5: mutated next by subscript
        "        rows[0] = key\n"
        "        seen = shared.setdefault(key, set())\n"  # 7: not mutated next: reported
        "        print(seen)\n"
        "        other = shared.setdefault(key, set())\n"  # 9: another name mutated
        "        reasons.add(other)\n"
        "        size = shared.setdefault(key, 0)\n"  # 11: not an empty container
        "        size.bit_length()\n"
    )
    assert def002(run(strict_config, text)) == [(7, "error"), (9, "error"), (11, "error")]


def test_remediation_names_the_three_cases() -> None:
    remediation = registry.DEF002.remediation
    assert "(1) The key must exist" in remediation
    assert "(2) Absence is a normal state" in remediation
    assert "'if tag not in index: continue'" in remediation  # branch where it matters
    assert ".get under another name" in remediation  # decision 34: fallback helpers
    assert "(3) The value comes from outside" in remediation


def test_recommended_reports_unknown_def_findings_without_gating(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    (empty_root / "src").mkdir()
    (empty_root / "src" / "a.py").write_text(
        "def f(payload):\n    return payload.get('items', [])\n", encoding="utf-8"
    )
    for profile, gate in (("strict", "fail"), ("recommended", "pass")):
        config = make_config(f'profile = "{profile}"\n')
        report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
        (finding,) = [f for f in report.findings if f.rule_id == "DEF002"]
        assert finding.status == STATUS_UNKNOWN and finding.severity == "error"
        assert report.gate.status == gate, profile
        assert report.gate.unknown == 1
