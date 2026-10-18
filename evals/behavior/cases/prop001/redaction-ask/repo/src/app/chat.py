"""Forwarding a note to the model for a chat reply."""

from app.model import send_to_model


def forward(client: object, note: str) -> str:
    return send_to_model(client, note)
