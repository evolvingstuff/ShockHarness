"""The ``--policy`` tier: bundled < profile < policy < repository < CLI, except that a
repository key may not loosen a key the policy sets (spec 21, H2 part 2)."""

from pathlib import Path

import pytest

from shockharness.config import CliOverrides, EffectiveConfig, load_config_with_overrides
from shockharness.errors import ConfigError
from shockharness.rules.policy_integrity import (
    _baseline_fingerprints,
    strictest_verification,
    toml_key_line,
)

POLICY = (
    '[tool.shockharness]\nprofile = "strict"\n'
    "[tool.shockharness.complexity]\ncognitive_warn = 15\n"
    "[tool.shockharness.rules.magic_numbers]\nenabled = true\n"
    '[tool.shockharness.rules.verification]\nseverity = "error"\n'
)


def write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    return write(tmp_path / "org" / "shockharness-policy.toml", POLICY)


def load(root: Path, policy: Path | None, profile: str | None) -> EffectiveConfig:
    return load_config_with_overrides(
        root, None, CliOverrides(profile=profile, parse_errors=None, policy=policy)
    )


def test_policy_values_apply_over_the_profile(empty_root: Path, policy: Path) -> None:
    config = load(empty_root, policy, None)
    assert config.values["complexity"]["cognitive_warn"] == 15
    assert config.values["rules"]["verification"]["severity"] == "error"
    assert config.policy is not None
    assert config.policy.keys == (
        "complexity.cognitive_warn",
        "profile",
        "rules.magic_numbers.enabled",
        "rules.verification.severity",
    )
    assert config.policy_attempts == ()
    assert config.to_json_dict()["policy"]["digest"] == config.policy.digest


def test_policy_digest_ignores_formatting(tmp_path: Path, empty_root: Path, policy: Path) -> None:
    reformatted = write(
        tmp_path / "other" / "p.toml",
        "# comment\n" + POLICY.replace("cognitive_warn = 15", "cognitive_warn   =   15"),
    )
    first = load(empty_root, policy, None).policy
    second = load(empty_root, reformatted, None).policy
    assert first is not None and second is not None
    assert first.digest == second.digest


def test_repository_loosening_is_reverted_and_recorded(empty_root: Path, policy: Path) -> None:
    write(
        empty_root / ".shockharness.toml",
        '[tool.shockharness]\nprofile = "minimal"\n'
        "[tool.shockharness.complexity]\ncognitive_warn = 40\nnpath_warn = 50\n"
        "[tool.shockharness.rules.magic_numbers]\nenabled = false\n"
        '[tool.shockharness.rules.verification]\nseverity = "review"\n',
    )
    config = load(empty_root, policy, None)
    assert config.values["profile"] == "strict"
    assert config.values["complexity"]["cognitive_warn"] == 15
    assert config.values["complexity"]["npath_warn"] == 50  # not a policy key
    assert config.values["rules"]["magic_numbers"]["enabled"] is True
    assert config.values["rules"]["verification"]["severity"] == "error"
    attempts = {a.key: a for a in config.policy_attempts}
    assert sorted(attempts) == [
        "complexity.cognitive_warn",
        "profile",
        "rules.magic_numbers.enabled",
        "rules.verification.severity",
    ]
    assert attempts["complexity.cognitive_warn"].policy_value == 15
    assert attempts["complexity.cognitive_warn"].attempted_value == 40
    assert attempts["complexity.cognitive_warn"].reasons != ()


def test_repository_tightening_of_a_policy_key_is_allowed(empty_root: Path, policy: Path) -> None:
    write(
        empty_root / ".shockharness.toml",
        "[tool.shockharness.complexity]\ncognitive_warn = 10\n",
    )
    config = load(empty_root, policy, None)
    assert config.values["complexity"]["cognitive_warn"] == 10
    assert config.policy_attempts == ()


def test_cli_profile_is_the_operators_and_is_noted(empty_root: Path, policy: Path) -> None:
    config = load(empty_root, policy, "minimal")
    assert config.values["profile"] == "minimal"
    assert config.policy_attempts == ()
    assert any("is looser than the policy file's profile 'strict'" in n for n in config.notes)
    assert not any("looser than the policy" in n for n in load(empty_root, policy, None).notes)


def test_policy_inside_the_root_is_refused(empty_root: Path) -> None:
    inside = write(empty_root / "policy" / "p.toml", POLICY)
    with pytest.raises(ConfigError) as info:
        load(empty_root, inside, None)
    assert "outside the analyzed root" in str(info.value)


def test_policy_must_exist_and_be_valid(tmp_path: Path, empty_root: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load(empty_root, tmp_path / "missing.toml", None)
    assert "does not exist" in str(info.value)
    bare = write(tmp_path / "bare.toml", "[other]\nx = true\n")
    with pytest.raises(ConfigError) as info:
        load(empty_root, bare, None)
    assert "no [tool.shockharness] table" in str(info.value)
    invalid = write(tmp_path / "bad.toml", '[tool.shockharness.complexity]\ncognitive_warn = "x"\n')
    with pytest.raises(ConfigError) as info:
        load(empty_root, invalid, None)
    assert "policy file is invalid" in str(info.value)


def test_strictest_verification_takes_the_stricter_side() -> None:
    base = {
        "enabled": True,
        "severity": "error",
        "fail_on_unknown": False,
        "allowed_skip_reasons": ["flaky"],
        "report_narrow_suppressions": False,
    }
    head = {
        "enabled": False,
        "severity": "review",
        "fail_on_unknown": True,
        "allowed_skip_reasons": ["flaky", "slow"],
        "report_narrow_suppressions": False,
    }
    assert strictest_verification(head, base) == {
        "enabled": True,
        "severity": "error",
        "fail_on_unknown": True,
        "allowed_skip_reasons": ["flaky"],
        "report_narrow_suppressions": False,
    }
    assert strictest_verification(head, None) == head


def test_toml_key_line_finds_assignments_and_tables() -> None:
    text = (
        '[tool.shockharness]\nprofile = "strict"\n\n'
        "[tool.shockharness.complexity]\ncognitive_warn = 40\n"
        "[tool.shockharness.rules.magic_numbers]\nenabled = false\n"
    )
    assert toml_key_line(text, "profile") == 2
    assert toml_key_line(text, "complexity.cognitive_warn") == 5
    assert toml_key_line(text, "rules.magic_numbers.enabled") == 7
    assert toml_key_line(text, "rules.magic_numbers") == 6
    assert toml_key_line(text, "nowhere.at_all") == 1


def test_only_shockharness_baselines_are_read() -> None:
    document = (
        '{"fingerprint_version": "1", "fingerprints": [{"fingerprint": "f", "rule_id": "R"}]}'
    )
    assert _baseline_fingerprints(document) == {"f": "R"}
    assert _baseline_fingerprints('{"fingerprints": []}') is None
    assert _baseline_fingerprints("not json") is None
    assert _baseline_fingerprints("[]") is None
