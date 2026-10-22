"""Agent skills shipped as package data (specification section 12).

One directory per skill under this package, each holding a ``SKILL.md`` in the open
Agent Skills format: YAML frontmatter with ``name`` and ``description`` followed by a
Markdown body. The files are vendor-neutral; the adapters in :mod:`.adapters` decide
where each agent expects them.
"""

import re
from dataclasses import dataclass
from importlib import resources

SKILL_FILENAME = "SKILL.md"
SKILL_NAMES: tuple[str, ...] = (
    "write-compliant-code",
    "fix-violations",
    "refactor-complexity",
    "pre-commit-review",
    "verification-integrity",
    "async-lifecycle",
    "property-contracts",
    "adopt-shockharness",
)
FRONTMATTER_DELIMITER = "---"
# Agent Skills specification: lowercase letters, digits and single hyphens, no leading,
# trailing or consecutive hyphen.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED_FIELDS = ("name", "description")


@dataclass(frozen=True)
class Frontmatter:
    name: str
    description: str


def skill_relative_path(name: str) -> str:
    """Where a skill lives below any destination directory (forward slashes)."""
    return f"{name}/{SKILL_FILENAME}"


def skill_bytes(name: str) -> bytes:
    """The exact bytes of a shipped ``SKILL.md`` (what ``skills install`` writes)."""
    if name not in SKILL_NAMES:
        raise KeyError(f"unknown skill {name!r}")
    raw = resources.files(__name__).joinpath(name).joinpath(SKILL_FILENAME).read_bytes()
    # Checkouts with core.autocrlf (Windows runners, some editors) turn LF into CRLF.
    # Skills are compared, hashed and installed byte-for-byte, so normalize once here
    # and the manifest hashes are identical on every platform.
    return raw.replace(b"\r\n", b"\n")


def skill_text(name: str) -> str:
    return skill_bytes(name).decode("utf-8")


def parse_frontmatter(text: str) -> Frontmatter:
    """Read the ``name`` and ``description`` of a SKILL.md.

    Supports the subset of YAML the shipped skills use: the document starts with a
    ``---`` line, every field is a single ``key: value`` line, and a second ``---``
    line closes the block. Anything else raises ``ValueError``: the shipped files are
    validated by the test suite, so a failure here is a packaging bug, not user input.
    """
    lines = text.split("\n")
    if len(lines) == 0 or lines[0].rstrip("\r") != FRONTMATTER_DELIMITER:
        raise ValueError("SKILL.md must start with a '---' frontmatter line")
    fields: dict[str, str] = {}
    closed = False
    for line in lines[1:]:
        stripped = line.rstrip("\r")
        if stripped == FRONTMATTER_DELIMITER:
            closed = True
            break
        key, separator, value = stripped.partition(":")
        if separator == "" or key.strip() == "" or key != key.strip():
            raise ValueError(f"frontmatter line is not 'key: value': {stripped!r}")
        if key in fields:
            raise ValueError(f"duplicate frontmatter field {key!r}")
        fields[key] = value.strip()
    if not closed:
        raise ValueError("frontmatter is not closed by a second '---' line")
    for field in REQUIRED_FIELDS:
        if field not in fields or fields[field] == "":
            raise ValueError(f"frontmatter is missing the required field {field!r}")
    return Frontmatter(name=fields["name"], description=fields["description"])


def shipped_frontmatter(name: str) -> Frontmatter:
    return parse_frontmatter(skill_text(name))
