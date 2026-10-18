"""The language-model client wrapper."""

from app.contracts import requires


def send_to_model(client: object, note: str) -> str:
    requires(note, "redacted")
    return client.complete(note)
