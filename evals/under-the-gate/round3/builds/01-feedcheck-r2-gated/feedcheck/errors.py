"""Typed errors raised by feedcheck."""


class FeedcheckError(Exception):
    """Base class for every error feedcheck reports to its user."""


class ConfigError(FeedcheckError):
    """The config file is missing, unreadable or invalid."""


class ReportWriteError(FeedcheckError):
    """The report could not be written."""
