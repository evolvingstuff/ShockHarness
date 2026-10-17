"""Outcome of normalizing one optional field."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Valid:
    """A normalized value; the empty string means the field was empty."""

    value: str


@dataclass(frozen=True)
class Invalid:
    """A value that cannot be used, and why."""

    reason: str


@dataclass(frozen=True)
class Phone:
    """A normalized phone number; verified numbers are in E.164."""

    value: str
    verified: bool


FieldResult = Valid | Invalid
PhoneResult = Phone | Invalid
