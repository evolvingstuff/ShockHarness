"""Typed errors raised by ShockHarness.

Every error carries a human-readable message and, where known, the origin
(a file path, config key, or CLI argument) that caused it. None of these are
ever swallowed inside the tool; the CLI maps them to exit codes.
"""


class ShockHarnessError(Exception):
    """Base class for all errors raised by ShockHarness."""

    def __init__(self, message: str, origin: str | None) -> None:
        super().__init__(message)
        self.message = message
        self.origin = origin

    def __str__(self) -> str:
        if self.origin is None:
            return self.message
        return f"{self.origin}: {self.message}"


class ConfigError(ShockHarnessError):
    """The configuration is missing, ambiguous, malformed, or semantically invalid.

    Maps to exit code ``EXIT_INVALID_CONFIG``.
    """


class UsageError(ShockHarnessError):
    """The invocation itself is unsupported (bad paths, unsupported file type, ...).

    Maps to exit code ``EXIT_INVALID_CONFIG``.
    """


class UnsupportedFeatureError(UsageError):
    """A documented command or option exists in the spec but is not built yet.

    Raised instead of silently doing nothing, so callers never mistake a no-op
    for a result.
    """
