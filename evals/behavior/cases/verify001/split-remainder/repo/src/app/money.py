"""Splitting an amount into equal parts."""


def split_cents(total_cents: int, parts: int) -> list[int]:
    share = total_cents // parts
    return [share for _ in range(parts)]
