"""The value of a C# numeric literal: ``0x1F``, ``0b1010``, ``1_000UL``, ``1.5e3m``, ``.5f``."""

import re

DIGIT_SEPARATOR = "_"
HEX_PREFIX = "0x"
BINARY_PREFIX = "0b"
HEX_BASE = 16
BINARY_BASE = 2
INTEGER_SUFFIX = re.compile(r"(?i)(ul|lu|u|l)$")
REAL_SUFFIX = re.compile(r"(?i)[fdm]$")


def parse_csharp_number(raw: str) -> int | float:
    """The value of an ``integer_literal`` or ``real_literal`` token. A real literal with
    a suffix but no point or exponent (``300f``) is a real number."""
    text = raw.replace(DIGIT_SEPARATOR, "").lower()
    if text.startswith(HEX_PREFIX):
        return int(INTEGER_SUFFIX.sub("", text[len(HEX_PREFIX) :]), HEX_BASE)
    if text.startswith(BINARY_PREFIX):
        return int(INTEGER_SUFFIX.sub("", text[len(BINARY_PREFIX) :]), BINARY_BASE)
    if REAL_SUFFIX.search(text) is not None:
        return float(REAL_SUFFIX.sub("", text))
    stripped = INTEGER_SUFFIX.sub("", text)
    if "." in stripped or "e" in stripped:
        return float(stripped)
    return int(stripped)
