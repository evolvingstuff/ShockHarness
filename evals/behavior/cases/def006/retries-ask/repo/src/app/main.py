"""The program's entry point."""

from collections.abc import Mapping

from app.settings import load_settings


def main(env: Mapping[str, str]) -> int:
    settings = load_settings(env)
    del settings
    return 0
