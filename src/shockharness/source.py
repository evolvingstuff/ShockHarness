"""Source text with line/column mapping.

Both parsers report columns as UTF-8 *byte* offsets within a line (Python's
``ast`` and tree-sitter alike). Reports use 1-based *character* columns, so every
span goes through :meth:`SourceText.column_from_byte_offset`. Line breaks are
``\\r\\n``, ``\\r`` or ``\\n``; a trailing line break does not count as an extra line.
"""

import re
from dataclasses import dataclass

from shockharness.constants import EVIDENCE_MAX_CHARS, FIRST_COLUMN, FIRST_LINE

LINE_BREAK = re.compile(r"\r\n|\r|\n")
ELLIPSIS = "..."


@dataclass(frozen=True)
class SourceText:
    text: str
    lines: tuple[str, ...]

    @staticmethod
    def from_text(text: str) -> "SourceText":
        return SourceText(text=text, lines=tuple(LINE_BREAK.split(text)))

    @property
    def line_count(self) -> int:
        if self.text == "":
            return 0
        if self.text.endswith(("\n", "\r")):
            return len(self.lines) - 1
        return len(self.lines)

    def line_text(self, line_number: int) -> str:
        index = line_number - FIRST_LINE
        if index < 0 or index >= len(self.lines):
            return ""
        return self.lines[index]

    def column_from_byte_offset(self, line_number: int, byte_offset: int) -> int:
        """Convert a UTF-8 byte offset within ``line_number`` to a 1-based character column."""
        encoded = self.line_text(line_number).encode("utf-8")
        prefix = encoded[:byte_offset]
        return len(prefix.decode("utf-8", errors="replace")) + FIRST_COLUMN

    def excerpt(self, line_number: int) -> str:
        """The stripped source line, truncated for use as finding evidence."""
        stripped = self.line_text(line_number).strip()
        if len(stripped) <= EVIDENCE_MAX_CHARS:
            return stripped
        return stripped[: EVIDENCE_MAX_CHARS - len(ELLIPSIS)] + ELLIPSIS
