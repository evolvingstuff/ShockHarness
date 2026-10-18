"""Summaries of a user's notes."""

from app.model import send_to_model


def summarize(client: object, note: str) -> str:
    return send_to_model(client, note)
