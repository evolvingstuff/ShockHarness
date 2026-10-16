"""What makes one configuration looser than another (shared by --policy and VERIFY003)."""

from pathlib import Path

from shockharness.config import load_config
from shockharness.loosening import deviation_key, has_key, loosenings, new_deviations, value_at


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def compare(root: Path, before: str, after: str) -> list[tuple[str, str]]:
    write(root, ".shockharness.toml", before)
    old = load_config(root, None)
    write(root, ".shockharness.toml", after)
    new = load_config(root, None)
    found = loosenings(old.values, old.deviations, new.values, new.deviations)
    return [(item.key, item.message) for item in found]


def test_deviation_key_strips_indices_and_trailing_text() -> None:
    assert deviation_key("overrides[2] disables rules.magic_numbers for 'x'") == "overrides"
    assert deviation_key("rules.magic_numbers is disabled") == "rules.magic_numbers"
    assert deviation_key("  ") == ""


def test_new_deviations_is_a_multiset_difference_ignoring_indices() -> None:
    before = ["a[0] x", "a[1] y", "b"]
    assert new_deviations(before, ["a[0] y", "a[1] x", "b"]) == []
    assert new_deviations(before, ["a[0] x", "a[1] y", "a[2] y", "b"]) == ["a[2] y"]
    assert new_deviations(["b"], []) == []


def test_value_lookup_by_dotted_key() -> None:
    values = {"complexity": {"cognitive_warn": 15}}
    assert has_key(values, "complexity.cognitive_warn")
    assert not has_key(values, "complexity.npath_warn")
    assert not has_key(values, "complexity.cognitive_warn.deeper")
    assert value_at(values, "complexity.cognitive_warn") == 15


def test_identical_configurations_are_not_looser(empty_root: Path) -> None:
    config = "[tool.shockharness.complexity]\ncognitive_warn = 20\n"
    assert compare(empty_root, config, config) == []


def test_disabling_a_family_is_a_new_deviation(empty_root: Path) -> None:
    found = compare(
        empty_root,
        "[tool.shockharness]\n",
        "[tool.shockharness.rules.magic_numbers]\nenabled = false\n",
    )
    assert [key for key, _ in found] == ["rules.magic_numbers"]


def test_ordered_settings_only_count_towards_the_looser_end(empty_root: Path) -> None:
    error = '[tool.shockharness.rules.verification]\nseverity = "error"\n'
    review = '[tool.shockharness.rules.verification]\nseverity = "review"\n'
    keys = [key for key, _ in compare(empty_root, error, review)]
    assert "rules.verification.severity" in keys
    assert compare(empty_root, review, error) == []
    warn = '[tool.shockharness.gates]\nnew_hard_violations = "warn"\n'
    found = compare(empty_root, "[tool.shockharness]\n", warn)
    assert [key for key, _ in found] == ["gates.new_hard_violations"]


def test_raised_threshold_is_looser_and_lowered_is_not(empty_root: Path) -> None:
    low = "[tool.shockharness.complexity]\ncognitive_warn = 10\n"
    high = "[tool.shockharness.complexity]\ncognitive_warn = 40\n"
    found = compare(empty_root, low, high)
    assert found == [
        (
            "complexity.cognitive_warn",
            "complexity.cognitive_warn raised from 10 to 40: fewer units are reported",
        )
    ]
    assert compare(empty_root, high, low) == []


def test_scope_changes(empty_root: Path) -> None:
    narrowed = compare(
        empty_root,
        '[tool.shockharness]\ninclude = ["src/**", "lib/**"]\n',
        '[tool.shockharness]\ninclude = ["src/**"]\n',
    )
    assert narrowed == [("include", "include no longer lists 'lib/**'")]
    excluded = compare(
        empty_root,
        "[tool.shockharness]\nexclude = []\n",
        '[tool.shockharness]\nexclude = ["src/**"]\n',
    )
    assert excluded == [("exclude", "exclude now also lists 'src/**'")]
    widened = compare(
        empty_root,
        '[tool.shockharness]\nexclude = ["src/**"]\n',
        "[tool.shockharness]\nexclude = []\n",
    )
    assert widened == []


def test_each_key_is_reported_once(empty_root: Path) -> None:
    found = compare(
        empty_root,
        "[tool.shockharness]\n",
        '[tool.shockharness]\nparse_errors = "warn"\n',
    )
    assert [key for key, _ in found] == ["parse_errors"]


def test_h3_guardrail_settings_loosen_like_the_others(empty_root: Path) -> None:
    keys = [
        key
        for key, _ in compare(
            empty_root,
            "[tool.shockharness]\n",
            '[tool.shockharness.rules.stubs]\nseverity = "review"\nroles = []\n'
            "[tool.shockharness.rules.import_effects]\npython_operations = []\n"
            "[tool.shockharness.rules.assertions]\nenabled = false\n",
        )
    ]
    assert "rules.stubs.severity" in keys
    assert "rules.stubs.roles" in keys
    assert "rules.import_effects.python_operations" in keys
    assert "rules.assertions" in keys
    tightened = compare(
        empty_root,
        "[tool.shockharness]\n",
        '[tool.shockharness.rules.stubs]\nseverity = "error"\nmarkers = ["TODO"]\n',
    )
    assert tightened == []
