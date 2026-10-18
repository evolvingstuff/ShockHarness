"""What may leave the machine."""

import re

from app.contracts import produces

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def redact(note: str) -> str:
    return produces(EMAIL.sub("[email]", note), "redacted")
