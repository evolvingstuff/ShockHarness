"""User summaries (starting point: silent fallbacks for missing data)."""


def summarize(user: dict) -> str:
    name = user.get("name", "anonymous")
    title = user.get("title") or "member"
    return f"{name} ({title})"


def years_active(user: dict, current_year: int) -> int:
    since = user["since"] if user["since"] is not None else current_year
    years = current_year - since
    return years if years >= 0 else 0
