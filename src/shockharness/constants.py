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
# H6 dataflow: statements and expressions nested deeper than this are not followed (the
# unit is marked truncated); left-deep operator chains are flattened and never count.
DATAFLOW_MAX_DEPTH: Final[int] = 100
# GUARD001's rules.consistency.guard_min_percent is a percentage of call sites.
PERCENT: Final[int] = 100
# Claude Code's hook protocol: exit 2 shows the hook's stderr to the agent (an edit hook
# feeds findings back while the edit is still in the agent's context).
HOOK_FEEDBACK: Final[int] = 2
# Seconds Claude Code waits for the edit hook (a run analyzes one file, with the cache;
# measured at about half a second on this repository).
HOOK_TIMEOUT_SECONDS: Final[int] = 60
# A listener registration's arguments before its options: the event name and the handler
# (addEventListener("unhandledrejection", h), process.on("unhandledRejection", h)).
LISTENER_ARGUMENTS: Final[int] = 2
# MAGIC002 messages: the other places named, and the characters of a value shown.
STRING_PLACES_SHOWN: Final[int] = 3
STRING_VALUE_SHOWN: Final[int] = 60

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
MEMBERSHIP_RETURN_STATEMENTS: Final[int] = 2  # if k in m: return m[k] / return v

# Baseline files and finding fingerprints (Milestone F). Bumped on an incompatible change.
BASELINE_SCHEMA_VERSION: Final[str] = "1"
FINGERPRINT_VERSION: Final[str] = "1"

# SARIF output (Milestone F).
SARIF_VERSION: Final[str] = "2.1.0"
SARIF_SCHEMA_URI: Final[str] = "https://json.schemastore.org/sarif-2.1.0.json"

# Git history (Milestone F). A commit touching more analyzed files than this is excluded
# from co-change pairing: a repository-wide sweep says nothing about which files belong
# together, and pairing it would cost O(n^2) rows of noise.
COCHANGE_MAX_FILES_PER_COMMIT: Final[int] = 50

# Length of the abbreviated commit hash in human-readable output.
COMMIT_SHORT_HEX: Final[int] = 12
# skills install --lock: hex digits of the project-path digest in the lock file name.
LOCK_DIGEST_HEX: Final[int] = 12

# Skills manifest (Milestone G): `.shockharness-skills.json` written by `skills install`.
# Bumped on an incompatible change to its shape.
SKILLS_MANIFEST_SCHEMA_VERSION: Final[str] = "1"

# Human-readable output of hotspots (Milestone E): how many to list, and the score precision.
HOTSPOTS_SHOWN: Final[int] = 5
SCORE_DECIMALS: Final[int] = 3

# CPLX005 (0.2.0): a module import cycle is one finding; its message lists at most this
# many member modules, then "and N more". The full membership is in metrics.graph.cycles.
CYCLE_MEMBERS_LISTED: Final[int] = 8

# `check --summary` / report `summary` (0.2.0): how many files with the most policy
# findings to list, and the precision of the elapsed time in seconds.
SUMMARY_TOP_FILES: Final[int] = 10
ELAPSED_DECIMALS: Final[int] = 3

# The content-hash cache (0.3.0): the shape version of index.json and of each entry.
# Bumped on an incompatible change; a cache written by another version is invalidated.
# "2": finding status and file role (H1); "3": verification facts (H2); "7": TypeScript
# facts, and JavaScript parameters counted as a unit's locals (H-TS); "8": dataflow facts
# (H6); "9": call guards (H6 part two); "10": sentinel facts (MAGIC003); "11": element
# guards (DOM001); "12": cleanup and returned flags, computed-receiver callees; "18":
# constant definitions (MAGIC004); "19": a top-level allSettled checked after it; "20":
# early publications (STATE002); "21": receiver facts (docs/proposal-receivers.md, R1);
# "22": JavaScript receiver facts (R2); "23": disguised numbers (MAGIC005); "24":
# annotation coverage (TYPE002); "25": uses of functions (DEAD001, DEAD002);
# "26": methods named on call results, classes handed to a library (DEAD001, DEAD002);
# "27": function shapes (DUP001, DUP002); "28": C# exceptions and defaults (decision 41);
# "29": the annotated signature of a function shape (DUP002); "30": test stubs (VERIFY005);
# "31": text positions (DOM003).
CACHE_SCHEMA_VERSION: Final[str] = "31"
# Entry files are sharded by the first characters of the path hash (entries/ab/<hash>.json).
CACHE_SHARD_CHARS: Final[int] = 2
# A flattened control-tree entry: kind, child count, operators, sequences, label, labeled.
CACHE_CONTROL_FIELDS: Final[int] = 6

# Verification (H2): an equality assertion compares exactly two operands
# (assertEqual(a, b), expect(a).toBe(b) has one each side, assert.equal(a, b)).
EQUALITY_OPERANDS: Final[int] = 2
# isinstance(value, types): the value and the types (H4, ASYNC003).
ISINSTANCE_ARGUMENTS: Final[int] = 2

# `git diff --name-status -z` records (H2 rename detection): a rename or copy is
# "status, old path, new path"; every other change is "status, path".
GIT_RENAME_RECORD_TOKENS: Final[int] = 3
GIT_CHANGE_RECORD_TOKENS: Final[int] = 2

# VERIFY003 (H2 part 2): how many dropped file paths a scope finding lists before
# saying "and N more".
VERIFY003_LISTED_FILES: Final[int] = 5
