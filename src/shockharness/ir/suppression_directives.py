"""Suppression directives in comments (H2, VERIFY002).

A directive is a comment that tells a linter, type checker, coverage tool or ShockHarness
itself to look away. Each is classified as *narrow* (it names the rule codes it
silences, and a ShockHarness suppression also states a reason) or *blanket* (it names
no codes, names ``all``, or covers a whole file). Classification is syntax only: what
the named codes mean is the other tool's business.

Recognised (Python comments): ``# noqa`` and ``# noqa: E501``; ``# ruff: noqa`` and
``# flake8: noqa`` (file); ``# type: ignore`` and ``# type: ignore[code]``;
``# pylint: disable=...``, ``disable-next=...``, ``skip-file``; ``# pragma: no cover``
and ``no branch``; ``# mypy: ignore-errors`` (file).

Recognised (JavaScript comments): ``eslint-disable``, ``eslint-disable-line``,
``eslint-disable-next-line`` with or without rule names; ``@ts-ignore``,
``@ts-expect-error``, ``@ts-nocheck`` (file); ``istanbul ignore next|if|else|file``;
``c8 ignore`` and ``v8 ignore`` ``next|start|file``.

Both languages: ``shockharness: ignore[RULE] reason="..."``.

``@ts-expect-error`` names no codes and is therefore blanket, although it fails when
nothing needs suppressing; the classification is deliberately the strict one.
"""

import re
from collections.abc import Callable, Sequence

from shockharness.ir.model import (
    DIRECTIVE_SCOPE_FILE,
    DIRECTIVE_SCOPE_LINE,
    DIRECTIVE_SCOPE_NEXT_LINE,
    DIRECTIVE_SCOPE_REGION,
    Comment,
    Span,
    SuppressionDirective,
)

TOOL_NOQA = "noqa"
TOOL_FILE_NOQA = "file-noqa"
TOOL_TYPE_IGNORE = "type-ignore"
TOOL_PYLINT = "pylint"
TOOL_PRAGMA = "pragma-no-cover"
TOOL_MYPY = "mypy-ignore-errors"
TOOL_ESLINT = "eslint-disable"
TOOL_TS_IGNORE = "ts-ignore"
TOOL_TS_EXPECT_ERROR = "ts-expect-error"
TOOL_TS_NOCHECK = "ts-nocheck"
TOOL_ISTANBUL = "istanbul-ignore"
TOOL_C8 = "c8-ignore"
TOOL_SHOCKHARNESS = "shockharness"

CODE_SPLIT = re.compile(r"[\s,]+")
BLANKET_CODES = frozenset({"all"})

# Python
CODE_LIST = r"[A-Za-z]+[0-9]+(?:[\s,]+[A-Za-z]+[0-9]+)*"
FILE_NOQA = re.compile(
    r"#\s*(?:ruff|flake8)\s*:\s*noqa\b(?:\s*:\s*(?P<codes>" + CODE_LIST + r"))?", re.I
)
NOQA = re.compile(r"#\s*noqa\b(?:\s*:\s*(?P<codes>" + CODE_LIST + r"))?", re.I)
TYPE_IGNORE = re.compile(r"#\s*type\s*:\s*ignore\b(?:\[(?P<codes>[^\]]*)\])?")
PYLINT = re.compile(
    r"#\s*pylint\s*:\s*(?P<verb>disable-next|disable|skip-file)\b"
    r"(?:\s*=\s*(?P<codes>[\w\-]+(?:\s*,\s*[\w\-]+)*))?"
)
PRAGMA = re.compile(r"#\s*pragma\s*:\s*no\s*(?:cover|branch)\b", re.I)
MYPY = re.compile(r"#\s*mypy\s*:\s*ignore-errors\b")

# JavaScript
ESLINT = re.compile(r"eslint-disable(?P<variant>-next-line|-line)?\b(?P<rest>[^\n]*)")
TS_DIRECTIVE = re.compile(r"@ts-(?P<kind>ignore|expect-error|nocheck)\b")
ISTANBUL = re.compile(r"istanbul\s+ignore\s+(?P<kind>next|if|else|file)\b")
C8 = re.compile(r"\b(?:c8|v8)\s+ignore\s+(?P<kind>next|start|file)\b")

# Both
SHOCKHARNESS = re.compile(r"shockharness\s*:\s*ignore\[(?P<codes>[^\]]*)\](?P<rest>[^\n]*)")
REASON = re.compile(r"reason\s*=\s*\"(?P<reason>[^\"]*)\"")

ESLINT_DESCRIPTION = "--"
BLOCK_END = "*/"


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _codes(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(code for code in CODE_SPLIT.split(raw.strip()) if code != "")


def _directive(
    tool: str, scope: str, codes: tuple[str, ...], narrow: bool, text: str, span: Span
) -> SuppressionDirective:
    return SuppressionDirective(
        tool=tool, scope=scope, codes=codes, narrow=narrow, text=_collapse(text), span=span
    )


def _narrow(codes: tuple[str, ...]) -> bool:
    """Naming at least one code makes a directive narrow; ``all`` names none."""
    return len(codes) > 0 and not any(code.lower() in BLANKET_CODES for code in codes)


def _shockharness(comment: Comment) -> list[SuppressionDirective]:
    found: list[SuppressionDirective] = []
    for match in SHOCKHARNESS.finditer(comment.text):
        codes = _codes(match.group("codes"))
        reason = REASON.search(match.group("rest"))
        has_reason = reason is not None and reason.group("reason").strip() != ""
        found.append(
            _directive(
                TOOL_SHOCKHARNESS,
                DIRECTIVE_SCOPE_LINE,
                codes,
                _narrow(codes) and has_reason,
                # Identity across revisions: the rules named, never the reason's wording.
                "shockharness: ignore[" + ",".join(codes) + "]",
                comment.span,
            )
        )
    return found


def _pylint(text: str, span: Span) -> list[SuppressionDirective]:
    found: list[SuppressionDirective] = []
    for match in PYLINT.finditer(text):
        verb = match.group("verb")
        if verb == "skip-file":
            found.append(
                _directive(
                    TOOL_PYLINT,
                    DIRECTIVE_SCOPE_FILE,
                    (),
                    narrow=False,
                    text=match.group(0),
                    span=span,
                )
            )
            continue
        codes = _codes(match.group("codes"))
        scope = DIRECTIVE_SCOPE_NEXT_LINE if verb == "disable-next" else DIRECTIVE_SCOPE_LINE
        found.append(_directive(TOOL_PYLINT, scope, codes, _narrow(codes), match.group(0), span))
    return found


def _codeless(
    pattern: re.Pattern[str], tool: str, scope: str, text: str, span: Span
) -> list[SuppressionDirective]:
    """Directives that never name codes (``pragma: no cover``, ``mypy: ignore-errors``)."""
    return [
        _directive(tool, scope, (), narrow=False, text=match.group(0), span=span)
        for match in pattern.finditer(text)
    ]


def _python_comment(comment: Comment) -> list[SuppressionDirective]:
    text = comment.text
    span = comment.span
    found: list[SuppressionDirective] = []
    file_noqa_spans: list[tuple[int, int]] = []
    for match in FILE_NOQA.finditer(text):
        file_noqa_spans.append(match.span())
        codes = _codes(match.group("codes"))
        found.append(
            _directive(
                TOOL_FILE_NOQA, DIRECTIVE_SCOPE_FILE, codes, _narrow(codes), match.group(0), span
            )
        )
    for match in NOQA.finditer(text):
        if any(start <= match.start() < end for start, end in file_noqa_spans):
            continue
        codes = _codes(match.group("codes"))
        found.append(
            _directive(TOOL_NOQA, DIRECTIVE_SCOPE_LINE, codes, _narrow(codes), match.group(0), span)
        )
    for match in TYPE_IGNORE.finditer(text):
        codes = _codes(match.group("codes"))
        found.append(
            _directive(
                TOOL_TYPE_IGNORE, DIRECTIVE_SCOPE_LINE, codes, _narrow(codes), match.group(0), span
            )
        )
    found.extend(_pylint(text, span))
    found.extend(_codeless(PRAGMA, TOOL_PRAGMA, DIRECTIVE_SCOPE_LINE, text, span))
    found.extend(_codeless(MYPY, TOOL_MYPY, DIRECTIVE_SCOPE_FILE, text, span))
    found.extend(_shockharness(comment))
    return found


def _eslint_codes(rest: str) -> tuple[str, ...]:
    """Rule names after an eslint directive, up to a ``--`` description or ``*/``."""
    for marker in (ESLINT_DESCRIPTION, BLOCK_END):
        index = rest.find(marker)
        if index >= 0:
            rest = rest[:index]
    return _codes(rest)


def _javascript_comment(comment: Comment) -> list[SuppressionDirective]:
    text = comment.text
    span = comment.span
    found: list[SuppressionDirective] = []
    for match in ESLINT.finditer(text):
        variant = match.group("variant")
        codes = _eslint_codes(match.group("rest"))
        if variant == "-line":
            scope = DIRECTIVE_SCOPE_LINE
        elif variant == "-next-line":
            scope = DIRECTIVE_SCOPE_NEXT_LINE
        else:
            scope = DIRECTIVE_SCOPE_REGION
        # The text identifies the directive across revisions: tool, variant and codes,
        # never the free-text "-- description", which may be reworded.
        written = "eslint-disable"
        if variant is not None:
            written = written + variant
        if len(codes) > 0:
            written = written + " " + ",".join(codes)
        found.append(_directive(TOOL_ESLINT, scope, codes, _narrow(codes), written, span))
    for match in TS_DIRECTIVE.finditer(text):
        kind = match.group("kind")
        if kind == "nocheck":
            tool, scope = TOOL_TS_NOCHECK, DIRECTIVE_SCOPE_FILE
        elif kind == "expect-error":
            tool, scope = TOOL_TS_EXPECT_ERROR, DIRECTIVE_SCOPE_NEXT_LINE
        else:
            tool, scope = TOOL_TS_IGNORE, DIRECTIVE_SCOPE_NEXT_LINE
        found.append(_directive(tool, scope, (), narrow=False, text=match.group(0), span=span))
    for match in ISTANBUL.finditer(text):
        scope = DIRECTIVE_SCOPE_FILE if match.group("kind") == "file" else DIRECTIVE_SCOPE_REGION
        found.append(
            _directive(TOOL_ISTANBUL, scope, (), narrow=False, text=match.group(0), span=span)
        )
    for match in C8.finditer(text):
        scope = DIRECTIVE_SCOPE_FILE if match.group("kind") == "file" else DIRECTIVE_SCOPE_REGION
        found.append(_directive(TOOL_C8, scope, (), narrow=False, text=match.group(0), span=span))
    found.extend(_shockharness(comment))
    return found


def _collect(
    comments: Sequence[Comment], classify: Callable[[Comment], list[SuppressionDirective]]
) -> tuple[SuppressionDirective, ...]:
    found: list[SuppressionDirective] = []
    for comment in comments:
        found.extend(classify(comment))
    found.sort(key=lambda d: (d.span, d.tool, d.text))
    return tuple(found)


def python_directives(comments: Sequence[Comment]) -> tuple[SuppressionDirective, ...]:
    return _collect(comments, _python_comment)


def javascript_directives(comments: Sequence[Comment]) -> tuple[SuppressionDirective, ...]:
    return _collect(comments, _javascript_comment)
