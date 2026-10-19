"""Milestone H1: file roles, overrides by role, and the config-role MAGIC001 exemption."""

from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import (
    CACHE_CONFIGURED,
    AnalysisOptions,
    analyze_text,
    file_role,
    unsupported_source_result,
)
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig, load_bundled_defaults
from shockharness.errors import ConfigError
from shockharness.roles import CLASSIFIED_ROLES, ROLES, FileRole, role_classifier

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)

# Every default glob, with a path it classifies (and the role that path gets).
DEFAULT_GLOB_EXAMPLES: list[tuple[str, str, str]] = [
    ("generated", "**/generated/**", "pkg/generated/models.py"),
    ("generated", "**/*_pb2.py", "api/service_pb2.py"),
    ("generated", "**/*.min.js", "static/app.min.js"),
    ("generated", "**/*.g.cs", "obj/Debug/net8.0/GlobalUsings.g.cs"),
    ("generated", "**/*.Designer.cs", "Properties/Resources.Designer.cs"),
    ("vendor", "**/vendor/**", "vendor/lib/x.js"),
    ("vendor", "**/third_party/**", "src/third_party/y.py"),
    ("config", "conftest.py", "conftest.py"),
    ("config", "setup.py", "setup.py"),
    ("config", "*.config.js", "web/vite.config.js"),
    ("config", "*.config.mjs", "eslint.config.mjs"),
    ("config", "*.config.cjs", "jest.config.cjs"),
    ("config", "*.conf.js", "karma.conf.js"),
    ("config", "*.conf.cjs", "karma.conf.cjs"),
    ("config", "*.config.ts", "vite.config.ts"),
    ("config", "*.config.mts", "vitest.config.mts"),
    ("config", "*.config.cts", "jest.config.cts"),
    ("config", ".eslintrc.js", ".eslintrc.js"),
    ("config", ".eslintrc.cjs", ".eslintrc.cjs"),
    ("config", ".prettierrc.js", ".prettierrc.js"),
    ("config", ".prettierrc.cjs", ".prettierrc.cjs"),
    ("config", "gulpfile.js", "gulpfile.js"),
    ("config", "Gruntfile.js", "Gruntfile.js"),
    ("test", "tests/**", "tests/unit/helpers.py"),
    ("test", "test/**", "test/run.js"),
    ("test", "**/__tests__/**", "src/ui/__tests__/button.js"),
    ("test", "**/test_*.py", "src/pkg/test_util.py"),
    ("test", "**/*_test.py", "src/pkg/util_test.py"),
    ("test", "**/*.test.js", "src/a.test.js"),
    ("test", "**/*.spec.js", "src/a.spec.js"),
    ("test", "**/*.test.mjs", "src/a.test.mjs"),
    ("test", "**/*.spec.mjs", "src/a.spec.mjs"),
    ("test", "**/*.test.ts", "src/a.test.ts"),
    ("test", "**/*.spec.ts", "src/a.spec.ts"),
    ("test", "**/*.test.tsx", "src/ui/a.test.tsx"),
    ("test", "**/*.spec.tsx", "src/ui/a.spec.tsx"),
    ("test", "**/*.test.mts", "src/a.test.mts"),
    ("test", "**/*.spec.mts", "src/a.spec.mts"),
    ("test", "**/*Tests.cs", "src/PlayerTests.cs"),
    ("test", "**/*.Tests/**", "Game.Tests/PlayerSpec.cs"),
    ("docs", "docs/**", "docs/conf.py"),
]


def classify(path: str) -> FileRole:
    return role_classifier(load_bundled_defaults()["file_roles"]).classify(path)


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_roles_and_precedence_order() -> None:
    assert CLASSIFIED_ROLES == ("generated", "vendor", "config", "test", "docs")
    assert ROLES == ("generated", "vendor", "config", "test", "docs", "production")


def test_default_globs_are_exactly_the_documented_ones() -> None:
    defaults = load_bundled_defaults()
    for role in CLASSIFIED_ROLES:
        documented = [glob for r, glob, _ in DEFAULT_GLOB_EXAMPLES if r == role]
        if role == "test":
            documented.append("**/conftest.py")
        assert defaults["file_roles"][role] == documented, role
    assert (
        defaults["file_roles"]["config"]
        == defaults["rules"]["magic_numbers"]["configuration_files"]
    )


@pytest.mark.parametrize(("role", "glob", "path"), DEFAULT_GLOB_EXAMPLES)
def test_every_default_glob(role: str, glob: str, path: str) -> None:
    assert classify(path) == FileRole(role, glob)


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "examples/python/app.py", "lib/index.js", "src/testing.py", "src/test.js"],
)
def test_everything_else_is_production(path: str) -> None:
    assert classify(path) == FileRole("production", None)


@pytest.mark.parametrize(
    ("path", "role", "pattern"),
    [
        # generated before vendor before config before test before docs
        ("vendor/generated/x.py", "generated", "**/generated/**"),
        ("tests/fixtures/data_pb2.py", "generated", "**/*_pb2.py"),
        ("third_party/setup.py", "vendor", "**/third_party/**"),
        ("tests/conftest.py", "config", "conftest.py"),
        ("docs/conftest.py", "config", "conftest.py"),
        ("docs/tests/x.py", "docs", "docs/**"),
        ("tests/docs/x.py", "test", "tests/**"),
        ("docs/test_x.py", "test", "**/test_*.py"),
    ],
)
def test_first_matching_role_wins(path: str, role: str, pattern: str) -> None:
    assert classify(path) == FileRole(role, pattern)


def test_conftest_is_test_when_the_config_role_leaves_it_out(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config("[tool.shockharness.file_roles]\nconfig = []\n")
    assert file_role("pkg/conftest.py", config) == FileRole("test", "**/conftest.py")


def test_root_anchors_work_in_role_globs(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config('[tool.shockharness.file_roles]\ndocs = ["/manual.py"]\n')
    assert file_role("manual.py", config) == FileRole("docs", "/manual.py")
    assert file_role("src/manual.py", config) == FileRole("production", None)


def test_invalid_role_glob_is_a_config_error(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    with pytest.raises(ConfigError, match=r"file_roles\.vendor\[0\]"):
        make_config('[tool.shockharness.file_roles]\nvendor = ["lib/**x"]\n')
    with pytest.raises(ConfigError, match=r"file_roles\.production: unknown key"):
        make_config('[tool.shockharness.file_roles]\nproduction = ["src/**"]\n')


def test_report_carries_roles(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/app.py", "x = 2\n")
    write(empty_root, "tests/test_app.py", "y = 3\nz = 4\n\n\ndef test_app():\n    assert y\n")
    write(empty_root, "docs/conf.py", "w = 5\n")
    write(empty_root, "setup.py", "v = 6\n")
    write(empty_root, "vendor/lib.js", "function (\n")
    report = analyze_paths([empty_root], empty_root, strict_config, OPTIONS)
    files = {f["path"]: (f["role"], f["role_pattern"]) for f in report.to_json_dict()["files"]}
    assert files == {
        "docs/conf.py": ("docs", "docs/**"),
        "setup.py": ("config", "setup.py"),
        "src/app.py": ("production", None),
        "tests/test_app.py": ("test", "tests/**"),
        "vendor/lib.js": ("vendor", "**/vendor/**"),
    }
    assert report.coverage["roles"] == {
        "generated": 0,
        "vendor": 1,
        "config": 1,
        "test": 1,
        "docs": 1,
        "production": 1,
    }
    assert report.summary["by_role"] == {
        "generated": 0,
        "vendor": 0,
        "config": 0,
        "test": 2,
        "docs": 1,
        "production": 1,
    }


def test_roles_do_not_change_what_is_analyzed(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "docs/example.py", "x = 2\n")
    write(empty_root, "vendor/lib.py", "y = 3\n")
    report = analyze_paths([empty_root], empty_root, strict_config, OPTIONS)
    assert [(f.path, f.rule_id) for f in report.findings] == [
        ("docs/example.py", "MAGIC001"),
        ("vendor/lib.py", "MAGIC001"),
    ]
    assert report.gate.status == "fail"


def test_unsupported_source_carries_its_role(strict_config: EffectiveConfig) -> None:
    result = unsupported_source_result("tests/a.rs", "no adapter", strict_config)
    assert (result.role, result.role_pattern) == ("test", "tests/**")


# --- overrides by role ---------------------------------------------------------------------


def test_override_by_role(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[[tool.shockharness.overrides]]\n"
        'roles = ["test"]\ndisable = ["MAGIC001"]\nreason = "tests hold expected literals"\n'
    )
    in_tests = analyze_text(
        "tests/test_a.py", "python", "x = 2\n\n\ndef test_x():\n    assert x\n", config, OPTIONS
    )
    assert in_tests.findings == ()
    assert [d.to_json_dict() for d in in_tests.rules_disabled] == [
        {"rule_id": "MAGIC001", "reason": "tests hold expected literals", "origin": "overrides[0]"}
    ]
    in_src = analyze_text("src/a.py", "python", "x = 2\n", config, OPTIONS)
    assert [f.rule_id for f in in_src.findings] == ["MAGIC001"]
    assert config.deviations == (
        "overrides[0] disables MAGIC001 for file role(s) test: tests hold expected literals",
    )


def test_override_by_path_still_works(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[[tool.shockharness.overrides]]\n"
        'paths = ["tests/**"]\ndisable = ["MAGIC001"]\nreason = "tests hold expected literals"\n'
    )
    result = analyze_text(
        "tests/test_a.py", "python", "x = 2\n\n\ndef test_x():\n    assert x\n", config, OPTIONS
    )
    assert result.findings == ()
    assert result.rules_disabled[0].origin == "overrides[0]"
    assert config.deviations == (
        "overrides[0] disables MAGIC001 for tests/**: tests hold expected literals",
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('paths = ["a/**"]\nroles = ["test"]\n', "needs exactly one of 'paths'"),
        ("", "needs exactly one of 'paths'"),
        ("roles = []\n", r"overrides\[0\]\.roles: must list at least one file role"),
        ('roles = ["tests"]\n', r"overrides\[0\]\.roles\[0\]: must be one of"),
        ("paths = []\n", r"overrides\[0\]\.paths: must list at least one path"),
    ],
)
def test_override_scope_is_validated(
    body: str, message: str, make_config: Callable[[str], EffectiveConfig]
) -> None:
    with pytest.raises(ConfigError, match=message):
        make_config(
            f'[[tool.shockharness.overrides]]\n{body}disable = ["MAGIC001"]\nreason = "r"\n'
        )


def test_override_by_production_role(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[[tool.shockharness.overrides]]\n"
        'roles = ["production"]\ndisable = ["DEF001"]\nreason = "r"\n'
    )
    source = "def f(a=None):\n    return a\n"
    assert analyze_text("src/a.py", "python", source, config, OPTIONS).findings == ()
    tests = analyze_text(
        "tests/a.py", "python", source + "\n\ndef test_f():\n    f()\n", config, OPTIONS
    )
    assert [f.rule_id for f in tests.findings] == ["DEF001"]


# --- the config role and the MAGIC001 exemption ---------------------------------------------


def test_config_role_is_exempt_from_magic001(strict_config: EffectiveConfig) -> None:
    result = analyze_text(
        "web/vite.config.js", "javascript", "const x = 3;\n", strict_config, OPTIONS
    )
    assert result.findings == ()
    assert [d.to_json_dict() for d in result.rules_disabled] == [
        {
            "rule_id": "MAGIC001",
            "reason": "file role is config (pattern '*.config.js'; "
            "exclude_configuration_files = true)",
            "origin": "configuration_file",
        }
    ]


def test_vendor_file_matching_a_config_glob_keeps_its_0_3_0_exemption(
    strict_config: EffectiveConfig,
) -> None:
    result = analyze_text("vendor/pkg/setup.py", "python", "x = 2\n", strict_config, OPTIONS)
    assert result.role == "vendor"
    assert result.findings == ()
    assert "its role is vendor" in result.rules_disabled[0].reason


def test_exemption_off_reports_config_files(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\nexclude_configuration_files = false\n"
    )
    result = analyze_text("setup.py", "python", "x = 2\n", config, OPTIONS)
    assert result.role == "config"
    assert [f.rule_id for f in result.findings] == ["MAGIC001"]


def test_file_roles_config_drives_the_exemption(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config('[tool.shockharness.file_roles]\nconfig = ["tooling/**"]\n')
    assert analyze_text("tooling/x.py", "python", "x = 2\n", config, OPTIONS).findings == ()
    setup = analyze_text("setup.py", "python", "x = 2\n", config, OPTIONS)
    assert [f.rule_id for f in setup.findings] == ["MAGIC001"]


def test_legacy_configuration_files_alone_replaces_the_config_role(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        '[tool.shockharness.rules.magic_numbers]\nconfiguration_files = ["build_settings.py"]\n'
    )
    assert config.values["file_roles"]["config"] == ["build_settings.py"]
    assert config.origins["file_roles.config"] == "dedicated"
    assert any("legacy spelling" in note for note in config.notes)
    assert analyze_text("build_settings.py", "python", "x = 2\n", config, OPTIONS).findings == ()
    # as in 0.3.0, a configured list replaces the default one: setup.py is not exempt
    setup = analyze_text("setup.py", "python", "x = 2\n", config, OPTIONS)
    assert [f.rule_id for f in setup.findings] == ["MAGIC001"]
    assert setup.role == "production"


def test_legacy_configuration_files_merges_with_file_roles_config(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        '[tool.shockharness.file_roles]\nconfig = ["tooling/**", "setup.py"]\n'
        "[tool.shockharness.rules.magic_numbers]\n"
        'configuration_files = ["setup.py", "build_settings.py"]\n'
    )
    assert config.values["file_roles"]["config"] == ["tooling/**", "setup.py", "build_settings.py"]
    assert any("is merged into file_roles.config" in note for note in config.notes)
    for path in ("tooling/x.py", "setup.py", "build_settings.py"):
        assert analyze_text(path, "python", "x = 2\n", config, OPTIONS).findings == (), path


def test_bundled_configuration_files_change_nothing(strict_config: EffectiveConfig) -> None:
    assert strict_config.origins["file_roles.config"] == "bundled"
    assert not any("legacy spelling" in note for note in strict_config.notes)
