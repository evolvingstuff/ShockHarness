"""Built-in profiles: effective values, deviation lines, origins, and precedence."""

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import (
    NO_OVERRIDES,
    ORIGIN_CLI_OVERRIDE,
    CliOverrides,
    EffectiveConfig,
    load_bundled_defaults,
    load_config,
    load_config_with_overrides,
    load_profile_overlay,
    profile_overlay_text,
    render_profile_config_toml,
)
from shockharness.errors import ConfigError
from shockharness.schema import PROFILES

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
PYTHON_SAMPLE = (
    "x = 2\n"
    "def f(a, b=None):\n"
    "    try:\n"
    "        return a[b]\n"
    "    except KeyError:\n"
    "        return None\n"
    "limit = b if b is not None else 30\n"
)


def severities(config: EffectiveConfig) -> dict[str, str]:
    result = analyze_text("src/a.py", "python", PYTHON_SAMPLE, config, OPTIONS)
    return {f.rule_id: f.severity for f in result.findings}


def test_three_profiles_ship_as_package_data() -> None:
    assert PROFILES == ("strict", "recommended", "minimal")
    for name in PROFILES:
        document = tomllib.loads(profile_overlay_text(name))
        assert "tool" in document and "shockharness" in document["tool"], name
        overlay = load_profile_overlay(name)
        assert "profile" not in overlay


def test_unknown_profile_overlay_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="unknown profile"):
        load_profile_overlay("lenient")


def test_strict_is_the_bundled_defaults(empty_root: Path) -> None:
    assert load_profile_overlay("strict") == {}
    config = load_config(empty_root, None)
    assert config.values == load_bundled_defaults()
    assert config.deviations == ()
    assert severities(config) == {
        "MAGIC001": "error",
        "DEF001": "error",
        "DEF005": "error",
        "EXC001": "error",
        "DEF004": "error",
    }
    assert all(origin == "bundled" for origin in config.origins.values())


def test_recommended_profile_values_and_deviations(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config('profile = "recommended"\n')
    strict = load_bundled_defaults()
    assert config.values["profile"] == "recommended"
    assert config.values["rules"]["defaults"]["nullish_fallbacks"] == "review"
    assert config.values["rules"]["defaults"]["truthiness_fallbacks"] == "review"  # as strict
    assert config.values["rules"]["magic_numbers"]["allow_unary_negative_one"] is True
    assert config.values["rules"]["magic_numbers"]["named_constant_definitions"] == "allow"
    assert config.values["complexity"]["fan_out_warn"] == 30
    assert config.values["complexity"]["fan_out_severity"] == "review"
    assert config.values["parse_errors"] == "fail"
    assert config.values["complexity"]["enabled"] is True
    for section in ("magic_numbers", "exceptions", "defaults"):
        assert config.values["rules"][section]["severity"] == "error"
    changed = {key for key, origin in config.origins.items() if origin != "bundled"}
    assert changed == {
        "profile",
        "rules.defaults.nullish_fallbacks",
        "rules.defaults.fail_on_unknown",
        "rules.magic_numbers.allow_unary_negative_one",
        "rules.magic_numbers.named_constant_definitions",
        "complexity.fan_out_warn",
        "complexity.fan_out_severity",
    }
    assert config.origins["rules.defaults.nullish_fallbacks"] == "profile:recommended"
    assert config.origins["profile"] == "dedicated"
    assert strict["rules"]["defaults"]["nullish_fallbacks"] == "forbid"
    assert strict["rules"]["magic_numbers"]["allow_unary_negative_one"] is False
    assert strict["rules"]["magic_numbers"]["named_constant_definitions"] == "report"
    assert strict["complexity"]["fan_out_warn"] == 20
    assert strict["complexity"]["fan_out_severity"] == "warning"
    assert severities(config) == {
        "MAGIC001": "error",
        "DEF001": "error",
        "DEF005": "error",
        "EXC001": "error",
        "DEF004": "review",
    }


def test_recommended_profile_deviations(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config('profile = "recommended"\n')
    strict = load_bundled_defaults()
    # the threshold and the advisory severity of fan-out are not loosenings; the rest are
    assert config.deviations == (
        "profile is 'recommended', below 'strict'; the lines that follow are what it changes "
        "(see docs/configuration.md, Profiles)",
        "rules.magic_numbers.allow_unary_negative_one is enabled",
        "rules.magic_numbers.named_constant_definitions is 'allow'; a numeric literal that is "
        "the whole value of a module-level named constant definition is not reported",
        "rules.defaults.nullish_fallbacks is 'review' (strict profile: 'forbid'); DEF004 "
        "findings of that kind are reported as review",
        "rules.defaults.fail_on_unknown is false (profile 'strict': true); DEF001-DEF006 "
        "findings whose status is unknown are reported and never fail the gate",
    )
    assert config.values["rules"]["defaults"]["fail_on_unknown"] is False
    assert strict["rules"]["defaults"]["fail_on_unknown"] is True


def test_recommended_fan_out_is_review_above_thirty(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    helpers = "".join(f"def h{i}():\n    return 1\n\n\n" for i in range(31))
    calls_31 = " + ".join(f"h{i}()" for i in range(31))
    calls_25 = " + ".join(f"h{i}()" for i in range(25))
    text = helpers + f"def wide():\n    return {calls_31}\n\n\ndef mid():\n    return {calls_25}\n"
    (empty_root / "src").mkdir()
    (empty_root / "src" / "a.py").write_text(text, encoding="utf-8")
    recommended = make_config('profile = "recommended"\n')
    report = analyze_paths([empty_root / "src"], empty_root, recommended, OPTIONS)
    fan_out = [(f.scope, f.severity) for f in report.findings if f.rule_id == "CPLX005"]
    assert fan_out == [("wide", "review")]  # mid (25) is under fan_out_warn = 30
    assert "above fan_out_warn = 30" in report.findings[0].message
    assert report.gate.review == 1 and report.gate.warnings == 0
    (empty_root / ".shockharness.toml").unlink()
    strict = load_config(empty_root, None)
    report = analyze_paths([empty_root / "src"], empty_root, strict, OPTIONS)
    fan_out = [(f.scope, f.severity) for f in report.findings if f.rule_id == "CPLX005"]
    assert fan_out == [("wide", "warning"), ("mid", "warning")]  # source order


def test_minimal_reports_everything_at_review_and_never_fails(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config('profile = "minimal"\n')
    assert config.values["parse_errors"] == "warn"
    assert config.values["complexity"]["enabled"] is False
    for section in ("magic_numbers", "exceptions", "defaults"):
        assert config.values["rules"][section]["severity"] == "review"
        assert config.values["rules"][section]["enabled"] is True
    assert config.values["unsupported_sources"] == "ignore"
    changed = {key for key, origin in config.origins.items() if origin != "bundled"}
    assert changed == {
        "profile",
        "parse_errors",
        "unsupported_sources",
        "complexity.enabled",
        "rules.magic_numbers.severity",
        "rules.magic_numbers.named_constant_definitions",
        "rules.exceptions.severity",
        "rules.defaults.severity",
    }
    assert config.values["rules"]["magic_numbers"]["named_constant_definitions"] == "allow"
    assert severities(config) == {
        "MAGIC001": "review",
        "DEF001": "review",
        "DEF005": "review",
        "EXC001": "review",
        "DEF004": "review",
    }
    joined = "\n".join(config.deviations)
    assert config.deviations[0].startswith("profile is 'minimal', below 'strict'")
    assert "rules.magic_numbers.severity is 'review'; MAGIC001 findings" in joined
    assert "rules.exceptions.severity is 'review'; EXC001-EXC003 findings" in joined
    assert "rules.defaults.severity is 'review'; DEF001-DEF006 findings" in joined
    assert "complexity is disabled" in joined
    assert "parse_errors is 'warn'" in joined
    assert "rules.magic_numbers.named_constant_definitions is 'allow'" in joined
    assert "unsupported_sources is 'ignore'" in joined

    (empty_root / "src").mkdir()
    (empty_root / "src" / "a.py").write_text(PYTHON_SAMPLE, encoding="utf-8")
    (empty_root / "src" / "bad.js").write_text("function (\n", encoding="utf-8")
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.hard_violations == 0
    assert report.gate.review == len(report.findings) > 0
    assert report.analysis_status == "incomplete"  # the parse failure is still visible
    assert report.to_json_dict()["effective_profile"] == "minimal"


def test_malformed_suppressions_still_fail_under_minimal(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config('profile = "minimal"\n')
    result = analyze_text(
        "src/a.py", "python", "x = 2  # shockharness: ignore[MAGIC001]\n", config, OPTIONS
    )
    assert [(f.rule_id, f.severity) for f in result.findings] == [
        ("MAGIC001", "review"),
        ("SUPP001", "error"),
    ]


def test_repository_config_overrides_the_profile(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        'profile = "minimal"\nparse_errors = "fail"\n'
        '[tool.shockharness.rules.magic_numbers]\nseverity = "error"\n'
    )
    assert config.values["parse_errors"] == "fail"
    assert config.origins["parse_errors"] == "dedicated"
    assert config.values["rules"]["magic_numbers"]["severity"] == "error"
    assert config.values["rules"]["exceptions"]["severity"] == "review"  # still the profile's
    assert severities(config)["MAGIC001"] == "error"
    assert severities(config)["EXC001"] == "review"
    assert "parse_errors is 'warn'" not in "\n".join(config.deviations)


def test_cli_overrides_sit_above_the_repository_config(empty_root: Path) -> None:
    (empty_root / "shockharness.toml").write_text(
        '[tool.shockharness]\nprofile = "minimal"\nparse_errors = "warn"\n'
        '[tool.shockharness.rules.exceptions]\nseverity = "error"\n',
        encoding="utf-8",
    )
    config = load_config_with_overrides(
        empty_root, None, CliOverrides(profile="strict", parse_errors="fail", policy=None)
    )
    assert config.values["profile"] == "strict"
    assert config.values["parse_errors"] == "fail"
    assert config.origins["profile"] == ORIGIN_CLI_OVERRIDE
    assert config.origins["parse_errors"] == ORIGIN_CLI_OVERRIDE
    # the repository's own keys still apply on top of the CLI-selected profile layer
    assert config.values["rules"]["exceptions"]["severity"] == "error"
    assert config.origins["rules.exceptions.severity"] == "dedicated"
    assert config.values["rules"]["magic_numbers"]["severity"] == "error"  # strict overlay
    assert config.deviations == ()
    notes = "\n".join(config.notes)
    assert "profile 'strict' selected by --profile" in notes
    assert "parse_errors = 'fail' set by --parse-errors" in notes
    assert "configured value: 'warn'" in notes
    # the digest follows the effective values, so an override is never invisible
    assert config.digest != load_config(empty_root, None).digest
    assert load_config_with_overrides(empty_root, None, NO_OVERRIDES).values == (
        load_config(empty_root, None).values
    )


def test_invalid_cli_overrides_are_config_errors(empty_root: Path) -> None:
    with pytest.raises(ConfigError, match="--profile must be one of"):
        load_config_with_overrides(empty_root, None, CliOverrides("lenient", None, None))
    with pytest.raises(ConfigError, match="--parse-errors must be one of"):
        load_config_with_overrides(empty_root, None, CliOverrides(None, "ignore", None))


def test_section_severity_without_a_profile_is_a_deviation(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config('[tool.shockharness.rules.defaults]\nseverity = "review"\n')
    assert config.values["profile"] == "strict"
    assert config.deviations == (
        "rules.defaults.severity is 'review'; DEF001-DEF006 findings are reported as review "
        "and never fail the gate",
    )
    assert severities(config) == {
        "MAGIC001": "error",
        "DEF001": "review",
        "DEF005": "review",
        "EXC001": "error",
        "DEF004": "review",
    }


def test_section_severity_is_validated(make_config: Callable[[str], EffectiveConfig]) -> None:
    with pytest.raises(ConfigError, match=r"rules\.exceptions\.severity: must be one of"):
        make_config('[tool.shockharness.rules.exceptions]\nseverity = "warning"\n')


def test_init_text_per_profile() -> None:
    assert render_profile_config_toml("strict") == profile_defaults_text()
    short = render_profile_config_toml("minimal")
    assert 'profile = "minimal"' in short
    assert "parse_errors" not in short  # spelling out values would override the profile
    with pytest.raises(ConfigError, match="unknown profile"):
        render_profile_config_toml("lenient")


def profile_defaults_text() -> str:
    from shockharness.config import render_default_config_toml

    return render_default_config_toml()
