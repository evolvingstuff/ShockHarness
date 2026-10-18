import re

from app.contracts import produces


def redact(text):
    return produces(re.sub("@", "[at]", text), "redacted")
