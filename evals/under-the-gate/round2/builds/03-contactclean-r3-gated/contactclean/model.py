"""Records passed between the stages of contactclean."""

from dataclasses import dataclass

COLUMNS = ("name", "email", "phone", "birthday", "country")
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")

PHONE_VERIFIED = "verified"
PHONE_UNVERIFIED = "unverified"
NO_PHONE_STATUS = ""
EMPTY = ""


@dataclass(frozen=True)
class RawRow:
    """One data row of the input; row_number counts the header as row 1."""

    row_number: int
    values: tuple[tuple[str, str], ...]

    def field(self, column: str) -> str:
        for name, value in self.values:
            if name == column:
                return value
        raise KeyError(column)


@dataclass(frozen=True)
class Contact:
    row_number: int
    name: str
    email: str
    phone: str
    phone_status: str
    birthday: str
    country: str

    def filled_fields(self) -> int:
        """How many optional fields carry a value; used to pick the most complete record."""
        optional = (self.email, self.phone, self.birthday, self.country)
        return sum(1 for value in optional if value != EMPTY)

    def as_output_row(self) -> dict[str, str]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "phone_status": self.phone_status,
            "birthday": self.birthday,
            "country": self.country,
        }


@dataclass(frozen=True)
class FieldIssue:
    row_number: int
    field: str
    value: str
    reason: str


@dataclass(frozen=True)
class Rejection:
    row_number: int
    reason: str


@dataclass(frozen=True)
class Merge:
    kept_row: int
    merged_rows: tuple[int, ...]
    reasons: tuple[str, ...]
