"""Typed errors raised by contactclean."""


class InputError(Exception):
    """The input file cannot be read or does not have the expected columns."""


class OutputError(Exception):
    """An output file cannot be written."""
