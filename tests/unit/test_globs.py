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
        ("./src/*.py", "src/sub/a.py", False),
        ("./src/*.py", "other/src/a.py", False),
        ("/src/*.py", "src/a.py", True),
        ("/src/*.py", "other/src/a.py", False),
        ("/main.py", "main.py", True),
        ("/main.py", "build/main.py", False),
        ("./main.py", "main.py", True),
        ("./main.py", "build/main.py", False),
        ("main.py", "main.py", True),
        ("main.py", "build/main.py", True),
        ("/**/*.py", "a/b/c.py", True),
        ("/build/**", "build/x.py", True),
        ("/build/**", "a/build/x.py", False),
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
        ("/", "name something after the anchor"),
        ("./", "name something after the anchor"),
        ("//a.py", "'//'"),
        (".//a.py", "'//'"),
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
    "pattern",
    ["*.py", "src/**/*.js", "**/node_modules/**", "[ab]c.py", "tests/**", "/main.py", "./a.py"],
)
def test_valid_globs(pattern: str) -> None:
    assert validate_glob(pattern) is None


def test_root_anchored_patterns_are_reported_as_written_and_prune_at_the_root() -> None:
    """0.3.0, item 4: a leading ``/`` or ``./`` anchors the pattern to the analysis root."""
    globs = compile_globset(["/build/**", "./dist/**", "main.py"])
    assert globs.first_match("build/a.py") == "/build/**"
    assert globs.first_match("dist/a.py") == "./dist/**"
    assert globs.first_match("x/main.py") == "main.py"
    assert globs.prunes_directory("build")
    assert globs.prunes_directory("dist")
    assert not globs.prunes_directory("pkg/build")
    assert not globs.prunes_directory("pkg/dist")
    anchored = compile_glob("/main.py")
    assert anchored.anchored and not anchored.basename_only and anchored.body == "main.py"


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
