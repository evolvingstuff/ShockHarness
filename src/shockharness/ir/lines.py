"""Logical line counting shared by both adapters (size convention ``size/1``).

A line is *logical* when, after the comment text on it is blanked out, something
other than whitespace remains. The count for a unit covers the lines of its own
span minus the lines of every unit nested inside it, so each line of a file is
attributed to exactly one unit.
"""

from collections.abc import Sequence

from shockharness.ir.model import Comment, Span
from shockharness.source import SourceText


def _blank_comment(line: str, comment: Comment, line_number: int) -> str:
    """``line`` with the part covered by ``comment`` replaced by spaces."""
    start = 0
    if comment.span.line == line_number:
        start = comment.span.column - 1
    end = len(line)
    if comment.span.end_line == line_number:
        end = comment.span.end_column - 1
    if start >= end:
        return line
    return line[:start] + " " * (end - start) + line[end:]


def logical_line_count(
    source: SourceText,
    comments: Sequence[Comment],
    span: Span,
    excluded: Sequence[Span],
) -> int:
    """Lines in ``span`` that carry code, excluding lines inside any ``excluded`` span."""
    covered: set[int] = set()
    for other in excluded:
        covered.update(range(other.line, other.end_line + 1))
    by_line: dict[int, list[Comment]] = {}
    for comment in comments:
        for line_number in range(comment.span.line, comment.span.end_line + 1):
            if line_number not in by_line:
                by_line[line_number] = []
            by_line[line_number].append(comment)
    count = 0
    for line_number in range(span.line, span.end_line + 1):
        if line_number in covered:
            continue
        text = source.line_text(line_number)
        if line_number in by_line:
            for comment in by_line[line_number]:
                text = _blank_comment(text, comment, line_number)
        if text.strip() != "":
            count += 1
    return count
