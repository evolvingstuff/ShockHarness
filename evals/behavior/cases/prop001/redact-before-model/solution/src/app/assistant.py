"""Summaries of a user's notes."""

from app.model import send_to_model
from app.privacy import redact


def summarize(client: object, note: str) -> str:
    return send_to_model(client, redact(note))
