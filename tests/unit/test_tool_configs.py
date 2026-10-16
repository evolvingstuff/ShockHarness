"""Loosened settings of other tools (VERIFY003): ruff, flake8, pytest, coverage, ESLint."""

from shockharness.rules.tool_configs import ToolSettings, read_tool_settings, tool_loosenings


def settings(name: str, text: str) -> ToolSettings:
    parsed, error = read_tool_settings(name, text)
    assert error is None
    assert parsed is not None
    return parsed


def changes(name: str, before: str, after: str) -> list[tuple[str, str]]:
    found = tool_loosenings(settings(name, before), settings(name, after))
    return [(item.category, item.item) for item in found]


def test_ruff_ignore_select_and_per_file_ignores() -> None:
    before = '[tool.ruff.lint]\nselect = ["E", "F", "B"]\nignore = ["E501"]\n'
    after = (
        '[tool.ruff.lint]\nselect = ["E", "F"]\nignore = ["E501", "F401"]\n'
        '[tool.ruff.lint.per-file-ignores]\n"src/app.py" = ["F841"]\n'
    )
    assert changes("pyproject.toml", before, after) == [
        ("ruff.ignore", "F401"),
        ("ruff.per-file-ignores", "src/app.py: F841"),
        ("ruff.select", "B"),
    ]
    assert changes("pyproject.toml", after, before) == []


def test_top_level_ruff_toml() -> None:
    assert changes("ruff.toml", "exclude = []\n", 'exclude = ["src"]\n') == [
        ("ruff.exclude", "src")
    ]


def test_flake8_in_setup_cfg_and_dot_flake8() -> None:
    before = "[flake8]\nextend-ignore = E203\n"
    after = "[flake8]\nextend-ignore = E203, W503\nexclude = build\n"
    assert changes("setup.cfg", before, after) == [
        ("flake8.extend-ignore", "W503"),
        ("flake8.exclude", "build"),
    ]
    assert changes(".flake8", before, after) == changes("setup.cfg", before, after)


def test_pytest_addopts_deselection_and_testpaths() -> None:
    before = '[tool.pytest.ini_options]\ntestpaths = ["tests", "integration"]\naddopts = "-ra"\n'
    after = (
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
        "addopts = \"-ra -k 'not slow' -p no:randomly --deselect tests/test_a.py::test_b\"\n"
    )
    assert changes("pyproject.toml", before, after) == [
        ("pytest.addopts", "--deselect tests/test_a.py::test_b"),
        ("pytest.addopts", "-k not slow"),
        ("pytest.addopts", "-p no:randomly"),
        ("pytest.testpaths", "integration"),
    ]


def test_pytest_ini_with_unbalanced_quotes_is_still_read() -> None:
    parsed = settings("pytest.ini", "[pytest]\naddopts = -k 'not slow\n")
    assert "pytest.addopts" in parsed.sets


def test_coverage_fail_under_and_omit() -> None:
    before = "[report]\nfail_under = 90\n"
    assert changes(".coveragerc", before, "[report]\nfail_under = 80\n") == [
        ("coverage.fail_under", "80")
    ]
    assert changes(".coveragerc", before, "[report]\n") == [("coverage.fail_under", "removed")]
    assert changes(".coveragerc", before, "[report]\nfail_under = 95\n") == []
    assert changes(
        "pyproject.toml",
        "[tool.coverage.run]\nomit = []\n",
        '[tool.coverage.run]\nomit = ["src/legacy/*"]\n',
    ) == [("coverage.omit", "src/legacy/*")]
    assert changes(
        "setup.cfg", "[coverage:report]\nfail_under = 90\n", "[coverage:report]\nfail_under = 50\n"
    ) == [("coverage.fail_under", "50")]


def test_eslint_rules_turned_down_or_removed() -> None:
    before = '{"rules": {"no-unused-vars": "error", "eqeqeq": 2, "no-console": "off"}}'
    after = '{"rules": {"no-unused-vars": ["warn", {"args": "none"}]}, "ignorePatterns": ["src/"]}'
    assert changes(".eslintrc.json", before, after) == [
        ("eslint.ignorePatterns", "src/"),
        ("eslint.rules", "eqeqeq"),
        ("eslint.rules", "no-unused-vars"),
    ]
    assert changes(".eslintrc.json", after, before) == []


def test_unparseable_files_report_an_error_not_a_pass() -> None:
    for name, text in (
        ("pyproject.toml", "[tool.ruff\n"),
        ("setup.cfg", "no section header\n"),
        (".eslintrc", "rules:\n  eqeqeq: error\n"),
    ):
        parsed, error = read_tool_settings(name, text)
        assert parsed is None, name
        assert error is not None, name
