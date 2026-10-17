# contactclean

Cleans a CSV export of contacts (see `SPEC.md`). Python 3.11+, standard library only.

    python -m contactclean input.csv --output clean.csv --report report.json
    # or, after `pip install .`:
    contactclean input.csv --output clean.csv --report report.json

Run the tests with `python -m unittest`.

## Decisions not fixed by the spec

- **Row numbers** are CSV line numbers: the header is row 1, so the first contact is row 2.
- **Output columns**: `name,email,phone,phone_status,birthday,country`. `phone_status` is
  `verified` (E.164 for a supported country: US, GB, DE, FR), `unverified` (kept as
  given), or empty when there is no phone.
- **Phones**: a number with a supported country that does not fit that country's plan is
  invalid (it goes in the report). If it has an explicit `+`/`00` prefix with a different
  calling code, it is kept as given and marked unverified. Without a supported country, a
  value still needs 4–15 digits to be kept.
- **Birthdays**: a `DD/MM/YYYY` vs `MM/DD/YYYY` value that is ambiguous (e.g. `03/04/1990`)
  is reported as invalid. Dates in the future are invalid.
- **Merging** is transitive (A shares an email with B, B shares a verified phone with C,
  so all three are merged). The record with the most non-empty fields is kept, and a tie
  goes to the earlier row. Merges are listed in the report but do not on their own cause
  exit code 1.
- **Exit 2** covers: a missing or unreadable file, a file that is not UTF-8, an empty
  file, malformed CSV, and a header with no `name` column. In those cases no output is
  written.
- Header names are matched without regard to case or surrounding spaces. Unknown columns
  are dropped.

## Report format

```json
{
  "summary": {"rows_read": 3, "contacts_written": 1, "rows_rejected": 1,
              "invalid_fields": 1, "merge_groups": 1},
  "rejected": [{"row": 4, "reason": "missing name"}],
  "invalid_fields": [{"row": 2, "field": "email", "value": "bad", "reason": "not a valid email address"}],
  "merged": [{"kept_row": 3, "merged_rows": [2], "rows": [2, 3]}]
}
```
