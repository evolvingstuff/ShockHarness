"""Every numeric constant ShockHarness needs, in one place.

This module is the single MAGIC001 exemption in the tool's own configuration
(``.shockharness.toml``). Nothing else under ``src/`` may carry a numeric literal
other than ``0`` or ``1``. Each constant says what the number means so that the
number itself never has to appear anywhere else.

Values that are ``0`` or ``1`` but carry meaning (exit codes, first line) are
also named here, per the skills convention: the rule permits them, the project
still names them.
"""

from typing import Final

# Process exit codes (CLI contract, spec section 10).
EXIT_OK: Final[int] = 0
EXIT_VIOLATIONS: Final[int] = 1
EXIT_INVALID_CONFIG: Final[int] = 2
EXIT_INTERNAL_ERROR: Final[int] = 3

# Report schema. Bumped only on a breaking change to the JSON shape.
REPORT_SCHEMA_VERSION: Final[str] = "1"

# Source positions are reported 1-based for both lines and columns.
FIRST_LINE: Final[int] = 1
FIRST_COLUMN: Final[int] = 1

# How much of the config digest (hex SHA-256) to print in human output.
CONFIG_DIGEST_SHORT_HEX: Final[int] = 16

# Evidence excerpts are the stripped source line, truncated to this many characters.
EVIDENCE_MAX_CHARS: Final[int] = 120

# Text output wrapping width for rule explanations.
TEXT_WRAP_WIDTH: Final[int] = 88

# JSON indentation for human-readable report files.
JSON_INDENT: Final[int] = 2

# The one negative value MAGIC001 can be configured to permit.
NEGATIVE_ONE: Final[int] = -1

# Radix bases for decoding JavaScript numeric literals.
RADIX_BINARY: Final[int] = 2
RADIX_OCTAL: Final[int] = 8
RADIX_DECIMAL: Final[int] = 10
RADIX_HEX: Final[int] = 16

# Call arities that distinguish a fallback form from a plain lookup (DEF002, DEF006).
LOOKUP_WITH_FALLBACK_ARITY: Final[int] = (
    2  # m.get(k, v), m.pop(k, v), os.getenv("X", v), Object.hasOwn(o, k)
)
GETATTR_WITH_FALLBACK_ARITY: Final[int] = 3  # getattr(o, name, v)
