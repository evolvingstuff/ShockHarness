"""EXC006: an error class derived from SystemExit (under-the-gate rounds 2 and 3)."""

from collections.abc import Callable

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)

CODE = """\
import builtins


class ConfigError(SystemExit):
    pass


class InputUnreadableError(builtins.SystemExit, ValueError):
    pass


class Interrupted(KeyboardInterrupt):
    pass


class StopTest(BaseException):
    pass


class FetchError(Exception):
    pass
"""


def exc006(config: EffectiveConfig, path: str = "app/config.py") -> list[tuple[int, str, str]]:
    result = analyze_text(path, "python", CODE, config, OPTIONS)
    return [
        (f.span.line, f.severity, f.message.split(":")[0])
        for f in result.findings
        if f.rule_id == "EXC006"
    ]


def test_classes_derived_from_system_exit(strict_config: EffectiveConfig) -> None:
    # KeyboardInterrupt and BaseException bases are framework control flow (pytest's
    # Interrupted, hypothesis's StopTest) and are left alone.
    assert exc006(strict_config) == [
        (4, "warning", "ConfigError derives from SystemExit"),
        (8, "warning", "InputUnreadableError derives from builtins.SystemExit"),
    ]


def test_the_review_cap_lowers_errors_only_and_every_role_counts(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    capped = make_config('[tool.shockharness.rules.exceptions]\nseverity = "review"\n')
    assert [severity for _line, severity, _m in exc006(capped)] == ["warning", "warning"]
    assert exc006(make_config(""), "tests/test_config.py") != []  # every role
    result = analyze_text(
        "app/a.js", "javascript", "export class E extends Error {}\n", make_config(""), OPTIONS
    )
    assert "EXC006" not in result.rules_applied
