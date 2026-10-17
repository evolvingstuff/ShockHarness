# contactclean

    contactclean input.csv --output clean.csv --report report.json
    # or, without installing: python3 -m contactclean ...

Tests: `python3 -m unittest`

Output columns: `name,email,phone,phone_status,birthday,country`. `phone_status`
is `verified` (E.164), `unverified` (digits kept as given) or empty.

Report (`report.json`): `summary`, `rejected` (`row`, `reason`),
`invalid_fields` (`row`, `field`, `value`, `reason`) and `merged` (`kept_row`,
`merged_rows`, `rows`, `matched_on`). Row numbers count the header as row 1,
so they match a spreadsheet view of the file.

Exit codes: 0 all rows usable (merges and unverified phones don't count as
problems), 1 some row rejected or a field invalid, 2 input unreadable (missing,
empty, not UTF-8, no `name` column) or output not writable.
