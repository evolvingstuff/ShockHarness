"""Splitting an amount into equal parts."""


def split_cents(total_cents: int, parts: int) -> list[int]:
    """Equal shares; the remainder goes one cent at a time to the first shares."""
    share, remainder = divmod(total_cents, parts)
    return [share + 1 if index < remainder else share for index in range(parts)]
