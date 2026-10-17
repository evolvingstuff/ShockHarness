from pathlib import Path

import pytest

from shockharness.config import (
    TIER_BUNDLED,
    TIER_CLI,
    TIER_DEDICATED,
    TIER_PYPROJECT,
    config_digest,
    load_bundled_defaults,
    load_config,
)
from shockharness.errors import ConfigError
from shockharness.rules import registry


def write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def test_bundled_defaults_apply_when_nothing_is_configured(empty_root: Path) -> None:
    config = load_config(empty_root, None)
    assert config.source.tier == TIER_BUNDLED
    assert config.values["profile"] == "strict"
    assert config.values["rules"]["magic_numbers"]["allowed_values"] == [0, 1]
    assert config.values["parse_errors"] == "fail"
    assert config.deviations == ()
    assert any("bundled strict defaults apply" in note for note in config.notes)
    assert config.origins["parse_errors"] == TIER_BUNDLED


def test_bundled_defaults_validate_against_their_own_schema() -> None:
    defaults = load_bundled_defaults()
    assert "overrides" in defaults
    assert defaults["overrides"] == []
    assert "overrides" not in defaults["gates"]


def test_dedicated_file_wins_over_pyproject_and_is_reported(empty_root: Path) -> None:
    write(empty_root, "pyproject.toml", '[tool.shockharness]\nparse_errors = "warn"\n')
    write(empty_root, ".shockharness.toml", '[tool.shockharness]\ninclude = ["src/**/*.py"]\n')
    config = load_config(empty_root, None)
    assert config.source.tier == TIER_DEDICATED
    assert config.values["include"] == ["src/**/*.py"]
    assert config.values["parse_errors"] == "fail"
    assert config.origins["include"] == TIER_DEDICATED
    assert config.origins["parse_errors"] == TIER_BUNDLED
    assert any("shadowed" in note for note in config.notes)


def test_pyproject_table_is_used_when_no_dedicated_file(empty_root: Path) -> None:
    write(
        empty_root,
        "pyproject.toml",
        '[project]\nname = "x"\n[tool.shockharness]\nparse_errors = "warn"\n',
    )
    config = load_config(empty_root, None)
    assert config.source.tier == TIER_PYPROJECT
    assert config.values["parse_errors"] == "warn"
    assert any("parse_errors is 'warn'" in d for d in config.deviations)


def test_pyproject_without_table_is_not_a_source(empty_root: Path) -> None:
    write(empty_root, "pyproject.toml", '[project]\nname = "x"\n')
    assert load_config(empty_root, None).source.tier == TIER_BUNDLED


def test_explicit_config_wins_over_everything(empty_root: Path) -> None:
    write(empty_root, ".shockharness.toml", '[tool.shockharness]\nparse_errors = "warn"\n')
    explicit = write(empty_root, "ci.toml", "[tool.shockharness]\nfollow_symlinks = true\n")
    config = load_config(empty_root, explicit)
    assert config.source.tier == TIER_CLI
    assert config.values["follow_symlinks"] is True
    assert config.values["parse_errors"] == "fail"


def test_missing_explicit_config_is_an_error(empty_root: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(empty_root, empty_root / "nope.toml")


def test_explicit_config_without_table_is_an_error(empty_root: Path) -> None:
    explicit = write(empty_root, "ci.toml", "[other]\nx = 1\n")
    with pytest.raises(ConfigError, match=r"no \[tool.shockharness\] table"):
        load_config(empty_root, explicit)


def test_invalid_toml_is_an_error(empty_root: Path) -> None:
    write(empty_root, ".shockharness.toml", "[tool.shockharness\n")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(empty_root, None)


def test_unknown_key_is_an_error_not_a_warning(empty_root: Path) -> None:
    write(empty_root, ".shockharness.toml", "[tool.shockharness]\nstrictness = 11\n")
    with pytest.raises(ConfigError, match="strictness: unknown key"):
        load_config(empty_root, None)


def test_unknown_rule_in_override_is_rejected(empty_root: Path) -> None:
    write(
        empty_root,
        ".shockharness.toml",
        "[tool.shockharness]\n[[tool.shockharness.overrides]]\n"
        'paths = ["tests/**"]\ndisable = ["MAGIC999"]\nreason = "x"\n',
    )
    with pytest.raises(ConfigError, match="unknown rule ID 'MAGIC999'"):
        load_config(empty_root, None)


def test_invalid_glob_is_rejected_with_key_path(empty_root: Path) -> None:
    write(empty_root, ".shockharness.toml", '[tool.shockharness]\nexclude = ["ok/**", "bad[x"]\n')
    with pytest.raises(ConfigError, match=r"exclude\[1\]: unmatched"):
        load_config(empty_root, None)


def test_unsupported_language_in_include_is_rejected(empty_root: Path) -> None:
    write(empty_root, ".shockharness.toml", '[tool.shockharness]\ninclude = ["src/**/*.rs"]\n')
    with pytest.raises(ConfigError, match=r"'\.rs' is not a supported language"):
        load_config(empty_root, None)


def test_wildcard_extension_in_include_is_allowed(empty_root: Path) -> None:
    write(
        empty_root, ".shockharness.toml", '[tool.shockharness]\ninclude = ["src/**/*", "src/*.*"]\n'
    )
    assert load_config(empty_root, None).values["include"] == ["src/**/*", "src/*.*"]


def test_empty_override_lists_are_rejected(empty_root: Path) -> None:
    write(
        empty_root,
        ".shockharness.toml",
        "[tool.shockharness]\n[[tool.shockharness.overrides]]\n"
        'paths = []\ndisable = []\nreason = "x"\n',
    )
    with pytest.raises(ConfigError) as info:
        load_config(empty_root, None)
    assert "overrides[0].paths: must list at least one path" in str(info.value)
    assert "overrides[0].disable: must list at least one rule ID" in str(info.value)


def test_all_issues_are_reported_together(empty_root: Path) -> None:
    write(
        empty_root, ".shockharness.toml", '[tool.shockharness]\nbogus = 1\nparse_errors = "maybe"\n'
    )
    with pytest.raises(ConfigError) as info:
        load_config(empty_root, None)
    assert "bogus: unknown key" in str(info.value)
    assert "parse_errors: must be one of" in str(info.value)


def test_deviations_are_explicit(empty_root: Path) -> None:
    write(
        empty_root,
        ".shockharness.toml",
        "[tool.shockharness]\n"
        "[tool.shockharness.rules.magic_numbers]\n"
        "allowed_values = [0, 1, 2, 10]\n"
        "allow_unary_negative_one = true\n"
        "[tool.shockharness.rules.magic_strings]\n"
        "enabled = false\n"
        "[[tool.shockharness.overrides]]\n"
        'paths = ["tests/**"]\n'
        'disable = ["MAGIC001"]\n'
        'reason = "fixtures"\n',
    )
    config = load_config(empty_root, None)
    joined = "\n".join(config.deviations)
    assert "allowed_values permits 10, 2" in joined
    assert "allow_unary_negative_one" not in joined  # the default since the H6 feedback
    assert "rules.magic_strings is disabled" in joined
    assert "overrides[0] disables MAGIC001 for tests/**: fixtures" in joined


def test_digest_is_deterministic_and_sensitive() -> None:
    base = load_bundled_defaults()
    assert config_digest(base) == config_digest(load_bundled_defaults())
    changed = load_bundled_defaults()
    changed["parse_errors"] = "warn"
    assert config_digest(base) != config_digest(changed)


def test_section_lookup(empty_root: Path) -> None:
    config = load_config(empty_root, None)
    assert config.section("rules.magic_numbers")["enabled"] is True
    assert config.section(str(registry.MAGIC001.config_section))["allowed_values"] == [0, 1]


def test_effective_config_json_shape(empty_root: Path) -> None:
    data = load_config(empty_root, None).to_json_dict()
    assert set(data) == {
        "source",
        "digest",
        "notes",
        "deviations",
        "origins",
        "values",
        "policy",
        "policy_attempts",
    }
    assert data["policy"] is None
    assert data["policy_attempts"] == []
    assert data["values"]["profile"] == "strict"


def test_boundary_exception_must_be_a_class_name(empty_root: Path) -> None:
    for bad in ("*", "Timeout | Abort", "errors.*", "", "3rd.Error"):
        write(
            empty_root,
            ".shockharness.toml",
            "[tool.shockharness]\n[[tool.shockharness.rules.exceptions.boundaries]]\n"
            f'path = "src/**"\nlanguage = "python"\nexception = "{bad}"\nreason = "r"\n',
        )
        with pytest.raises(ConfigError) as info:
            load_config(empty_root, None)
        assert "boundaries[0].exception" in str(info.value), bad


def test_transparent_rethrow_is_validated_and_defaults_off(empty_root: Path) -> None:
    assert load_config(empty_root, None).section("rules.exceptions")["transparent_rethrow"] is False
    write(
        empty_root,
        ".shockharness.toml",
        '[tool.shockharness.rules.exceptions]\ntransparent_rethrow = "yes"\n',
    )
    with pytest.raises(ConfigError) as info:
        load_config(empty_root, None)
    assert "rules.exceptions.transparent_rethrow: expected true or false" in str(info.value)


def test_shockharness_toml_without_the_dot_is_accepted(empty_root: Path) -> None:
    write(empty_root, "shockharness.toml", '[tool.shockharness]\nparse_errors = "warn"\n')
    config = load_config(empty_root, None)
    assert config.source.tier == TIER_DEDICATED
    assert config.source.path == str(empty_root / "shockharness.toml")
    assert config.values["parse_errors"] == "warn"
    assert config.origins["parse_errors"] == TIER_DEDICATED


def test_both_dedicated_filenames_present_is_an_error_naming_both(empty_root: Path) -> None:
    write(empty_root, ".shockharness.toml", "[tool.shockharness]\n")
    write(empty_root, "shockharness.toml", "[tool.shockharness]\n")
    with pytest.raises(ConfigError) as info:
        load_config(empty_root, None)
    message = str(info.value)
    assert "two dedicated configuration files exist" in message
    assert str(empty_root / ".shockharness.toml") in message
    assert str(empty_root / "shockharness.toml") in message


def test_undotted_dedicated_file_also_shadows_pyproject(empty_root: Path) -> None:
    write(empty_root, "pyproject.toml", '[tool.shockharness]\nparse_errors = "warn"\n')
    write(empty_root, "shockharness.toml", "[tool.shockharness]\nfollow_symlinks = true\n")
    config = load_config(empty_root, None)
    assert config.source.tier == TIER_DEDICATED
    assert config.values["parse_errors"] == "fail"
    assert any("shadowed" in note for note in config.notes)


def test_root_anchored_globs_are_accepted_everywhere(empty_root: Path) -> None:
    """0.3.0, item 4: a leading ``/`` is no longer a configuration error."""
    write(
        empty_root,
        ".shockharness.toml",
        "[tool.shockharness]\n"
        'include = ["/main.py", "./src/**/*.py"]\nexclude = ["/build/**"]\n'
        "[tool.shockharness.rules.magic_numbers]\n"
        'configuration_files = ["/conftest.py"]\n'
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "/main.py"\nlanguage = "python"\nexception = "OSError"\nreason = "r"\n'
        "[[tool.shockharness.overrides]]\n"
        'paths = ["./tests/**"]\ndisable = ["MAGIC001"]\nreason = "r"\n',
    )
    config = load_config(empty_root, None)
    assert config.values["include"] == ["/main.py", "./src/**/*.py"]
    write(empty_root, ".shockharness.toml", '[tool.shockharness]\ninclude = ["/"]\n')
    with pytest.raises(ConfigError, match=r"include\[0\]: a root-anchored glob pattern"):
        load_config(empty_root, None)
