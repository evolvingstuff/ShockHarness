# contactclean: cleaning a contacts export (Python)

Build `contactclean`, which reads a CSV export of contacts and writes a cleaned
CSV and a report of the rows it could not use.

## Behavior

- Input columns: `name` (required), `email`, `phone`, `birthday`, `country`. All
  but `name` may be empty.
- Normalize: trim whitespace; lowercase emails; phone numbers to E.164 when the
  country is known (`country` is an ISO 3166 alpha-2 code; support at least US,
  GB, DE and FR), otherwise keep the digits as given and mark the phone
  `unverified`; birthdays in `YYYY-MM-DD`, `DD/MM/YYYY` or `MM/DD/YYYY` (only
  when unambiguous) to ISO 8601.
- An empty optional field stays empty in the output. It is not the same as an
  invalid value: an invalid email, phone or birthday goes to the report with the
  row number and the reason, and the row is written without that field.
- Contacts with the same email (case-insensitive), or the same verified phone,
  are merged: keep the most complete record and say in the report which rows
  were merged.
- A row without a name is rejected (in the report).
- `contactclean input.csv --output clean.csv --report report.json`; exit 0 when
  every row was usable, 1 when some were rejected or reported, 2 when the input
  cannot be read.

## Constraints

- Python 3.11+, standard library only. Include `unittest` tests.
