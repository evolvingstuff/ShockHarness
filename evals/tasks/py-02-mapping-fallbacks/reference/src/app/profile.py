"""User summaries: required data is indexed, optional data is branched on by name."""

from collections.abc import Mapping


def summarize(user: Mapping[str, str]) -> str:
    name = user["name"]
    if "title" in user:
        return f"{name} ({user['title']})"
    return name


def years_active(user: Mapping[str, int], current_year: int) -> int:
    since = user["since"]
    if since > current_year:
        raise ValueError(f"since ({since}) is after the current year ({current_year})")
    return current_year - since
