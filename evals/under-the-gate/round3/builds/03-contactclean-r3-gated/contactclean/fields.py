"""Column names of the contacts CSV."""

NAME = "name"
EMAIL = "email"
PHONE = "phone"
BIRTHDAY = "birthday"
COUNTRY = "country"

INPUT_COLUMNS = (NAME, EMAIL, PHONE, BIRTHDAY, COUNTRY)
REQUIRED_COLUMNS = frozenset({NAME})

PHONE_STATUS = "phone_status"
VERIFIED = "verified"
UNVERIFIED = "unverified"

OUTPUT_COLUMNS = (NAME, EMAIL, PHONE, PHONE_STATUS, BIRTHDAY, COUNTRY)
