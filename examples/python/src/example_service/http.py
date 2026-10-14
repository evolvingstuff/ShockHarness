"""HTTP status handling with one documented, suppressed literal.

The status code is a protocol constant with an authoritative source, so the
MAGIC001 finding is suppressed inline with the citation as the reason. The
finding stays in every report (with the suppression attached); only the gate
ignores it.
"""

NOT_FOUND = 404  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"


def is_missing(status: int) -> bool:
    return status == NOT_FOUND
