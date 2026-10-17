"""The log level the program runs with."""

import os

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def log_level() -> str:
    level = os.getenv("LOG_LEVEL", "INFO")
    if level not in LEVELS:
        raise ValueError(f"LOG_LEVEL must be one of {', '.join(LEVELS)}, got {level!r}")
    return level
