"""Typed errors raised by feedcheck."""


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid."""
