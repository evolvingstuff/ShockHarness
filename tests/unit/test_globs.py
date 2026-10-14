import pytest

from shockharness.globs import compile_glob, compile_globset, validate_glob


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("*.py", "a.py", True),
        ("*.py", "deep/nested/a.py", True),
        ("*.py", "a.pyc", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("src/**/*.py", "src/a.py", True),
        ("src/**/*.py", "src/sub/deep/a.py", True),
        ("src/**/*.py", "other/a.py", False),
        ("**/node_modules/**", "node_modules/x.js", True),
        ("**/node_modules/**", "a/b/node_modules/c/x.js", True),
        ("**/node_modules/**", "a/node_modulesx/x.js", False),
        ("**/*.test.js", "pkg/a.test.js", True),
        ("tests/**", "tests/unit/t.py", True),
        ("tests/**", "src/tests_helper.py", False),
        ("a?c.py", "abc.py", True),
        ("a?c.py", "ac.py", False),
        ("[ab].py", "a.py", True),
        ("[!ab].py", "a.py", False),
        ("[!ab].py", "c.py", True),
        ("./src/*.py", "src/a.py", True),
        ("file.with.dots.py", "x/file.with.dots.py", True),
        ("a*b", "x/ab", True),
        ("a*b", "x/a/b", False),
    ],
)
def test_glob_matching(pattern: str, path: str, expected: bool) -> None:
    assert compile_glob(pattern).matches(path) is expected


@pytest.mark.parametrize(
    ("pattern", "problem"),
    [
        ("", "empty"),
        ("src\\a.py", "forward slashes"),
        ("/abs/path.py", "relative"),
        ("a[bc.py", "unmatched '['"),
        ("abc].py", "unmatched ']'"),
        ("src**/a.py", "whole path segment"),
        ("a\0b", "NUL"),
    ],
)
def test_glob_validation_errors(pattern: str, problem: str) -> None:
    message = validate_glob(pattern)
    assert message is not None
    assert problem in message


@pytest.mark.parametrize(
    "pattern", ["*.py", "src/**/*.js", "**/node_modules/**", "[ab]c.py", "tests/**"]
)
def test_valid_globs(pattern: str) -> None:
    assert validate_glob(pattern) is None


def test_directory_pruning_only_for_double_star_suffix() -> None:
    globs = compile_globset(["**/node_modules/**", "**/dist/**", "*.min.js", "build/**"])
    assert globs.prunes_directory("node_modules")
    assert globs.prunes_directory("a/b/node_modules")
    assert globs.prunes_directory("build")
    assert not globs.prunes_directory("src")
    assert not globs.prunes_directory("x.min.js")


def test_first_match_reports_the_pattern() -> None:
    globs = compile_globset(["*.js", "**/vendor/**"])
    assert globs.first_match("vendor/a.py") == "**/vendor/**"
    assert globs.first_match("a.js") == "*.js"
    assert globs.first_match("a.py") is None
