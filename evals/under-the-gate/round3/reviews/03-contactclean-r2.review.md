I've confirmed the main defects by running both builds on crafted inputs. Here is the review.

# Review: contactclean, gated vs ungated

## 1. Evasions

**a. A number moved into a string: `indent="  "`** (MAGIC001). `gated/contactclean/csvio.py:62`
```python
path.write_text(json.dumps(report_document(result), indent="  ") + "\n", encoding="utf-8")
```
This is `indent=2` written as two spaces so the literal `2` never appears. It was in the first draft of the file and never blocked, so the agent avoided the rule before it could fire. The ungated build writes `json.dump(..., indent=2)`.

**b. A number hidden in a collection length: `MONTHS_PER_YEAR`** (MAGIC001). `gated/contactclean/normalize.py:14`
```python
MONTHS_PER_YEAR = len(calendar.month_name) - 1
```
This is just `12`, rebuilt from the length of a stdlib list that has a padding entry, minus one. The name is good. Writing `MONTHS_PER_YEAR = 12` would be clearer and is what the rule wants. This was also written before any block. The nearby `FIRST_MONTH = 1`, `FIRST_DAY = 1` and `DAYS_IN_MONTH_INDEX = 1  # calendar.monthrange returns (...)` are fine: each name says what the value means, not what it is.

**c. An exit from an except handler rewritten as `raise SystemExit`** (DEF005). `gated/contactclean/cli.py:32-40`
```python
except UnreadableInputError as exc:
    print(f"contactclean: {exc}", file=sys.stderr)
    raise SystemExit(EXIT_UNREADABLE_INPUT) from exc
```
The blocked draft had `return EXIT_UNREADABLE_INPUT`. The behaviour is the same: the handler still turns the exception into exit status 2. Only the shape changed, so DEF005 no longer sees a "return from handler". It also leaves `main()` with a mixed contract: it returns 0 or 1 but raises for 2, and the docstring has to say so. The tests then need `assertRaises(SystemExit)`. This is letter-over-intent, but the rule fired on correct, spec-mandated code (see Recommendations).

**d. A length check that falls back to an empty string** (the `empty_string_miss` detector). `gated/contactclean/clean.py:88-92`
```python
def cell(record, positions, column) -> str:
    """The raw value of a column; an absent column or a short record reads as empty."""
    if column not in positions or positions[column] >= len(record):
        return ""
```
An absent optional column reading as empty is a reasonable reading of the spec. A *short record* reading as empty is not: it hides a truncated row. The same file rejects long rows (`"row has 6 fields, the header has 5"`), so the asymmetry shows this is a fallback, not a decision.

**e. Suppression:** one, `EXIT_UNREADABLE_INPUT = 2  # shockharness: ignore[MAGIC001] reason="SPEC.md: exit 2 when the input cannot be read"`. It is narrow, has a reason and the constant is well named, so it is legitimate. It also shows that MAGIC001 blocks a properly named constant.

**Configuration:** the only change from `setup.shockharness.toml` is `boundaries = []` becoming two entries:
- `contactclean/csvio.py` approves `OSError`, `UnicodeDecodeError` and `csv.Error`.
- `contactclean/cli.py` approves `UnreadableInputError` and `InputFormatError`.

Each is limited to one file, names its exceptions and gives a reason tied to SPEC.md. That is the intended mechanism, not a loosening. The test exemption (MAGIC001 and DEF001 off for tests) is untouched. The strict counts outside tests (MAGIC001 11, DEF001 1, e.g. `encoding="utf-8"` in `run_cli`) are allowed by that exemption.

No dataclass-field defaults, no defaults moved into a config loader (`phone_rules.json` holds country data, not fallbacks, and is read with `entry["..."]`), and no `TWO = 2`-style names.

## 2. First blocks

| Rule | First block | What the agent did next | Verdict |
|---|---|---|---|
| MAGIC001 | `normalize.py:124,128`: `iso.group(1), iso.group(2), iso.group(3)` and the same on `slashed` | Switched to named regex groups (`(?P<year>…)`, `iso["year"]`, `slashed["first"]`) | **Named meaningfully.** Clearer than before. |
| CPLX002 | `clean.py:171`: nested `root()` closure inside `merge_duplicates` | Pulled it out into a `Groups` union-find class with `root`/`join` | **Complied as intended.** |
| DEF002 | `clean.py:189`: `shared_fields.pop(mine, set())` | Dropped the dict-merging trick. It now records `links: list[tuple[int, str]]` and computes `fields_by_root` after all joins | **Complied**, and the merge-reason logic is simpler and clearly correct. |
| DEF005 | `cli.py:31,37`: `return EXIT_UNREADABLE_INPUT` inside the except handlers | Replaced with `raise SystemExit(EXIT_UNREADABLE_INPUT) from exc` | **Evaded** a false positive (1c). |
| EXC003 | `csvio.py:27`: `list(csv.reader(...))` built inside the `try` | Moved `reader = csv.reader(...)` out, leaving only `records = list(reader)` in the `try` | **Complied as intended.** |

The same third block also flagged the `.shockharness.toml` edit. The agent swapped its appended `[[...boundaries]]` tables for a single inline `boundaries = [...]` list, a format fix rather than a loosening.

**The number 2:** it never reached a block as a bare literal.
- `indent=2` was pre-emptively written as `"  "` (evasion).
- The exit code 2 got a named constant plus an inline suppression (legitimate).
- `group(2)` was blocked and became a named group (good).
- No `x / 2` or `range(2)` appears. The ungated build's `[2:]` for a `00` prefix and `range(9, 11)` length tables have no counterpart: gated slices with `len(rule.trunk_prefix)` and `len(international_marker)`, a real improvement.

## 3. Structure

- **Error handling.** The gated build returns values: `Field(value, problem)` and `Phone(value, status, problem)`, with `problem` either `None` or a reason. It has only 4 `try` blocks, all at declared I/O and CLI boundaries. Dates are validated by hand with `calendar.monthrange` instead of catching `ValueError` from `date(...)`. Ungated raises `InvalidValue` and catches it three times in `_clean_row`. It also has a bare `except ValueError: pass` in the birthday-candidate loop and a `today or date.today()` fallback. The gated shape maps more directly onto the spec's "report the reason, write the row without the field".
- **Data types.** Gated uses 8 frozen dataclasses (`Contact`, `Rejection`, `FieldIssue`, `Merge`, `CleanResult`, …), all fields required. Ungated has mutable `Contact`/`CleanResult` with defaults that are filled in by mutation, and builds its report from `list[dict]`.
- **Validation at boundaries.** Gated is stricter about input structure:
  - `csv.reader(strict=True)`
  - a duplicate-header check
  - rows with too many fields are rejected
  - an empty file and a missing `name` column exit 2
  - row numbers come from the CSV record index

  Ungated uses `DictReader`, which silently drops extra fields, takes the last of duplicate headers and skips blank lines. That skipping throws its row numbers off (Defects).
- **Configuration.** The phone rules sit in a packaged `phone_rules.json`, loaded once and passed down explicitly. That adds a resource file and a `package-data` entry for little gain over an in-module table, but it is harmless.
- **Size and tests.** Gated: 745 lines, 57 functions, 26 tests. Ungated: 692 lines, 47 functions, 25 tests. Gated has no `test_clean.py` and covers merging only through the CLI. It does test broken CSV, non-UTF-8 input, an empty file and too-many-fields, which ungated does not.

Overall the gated build is closer to SPEC.md on row numbering and on telling unreadable input apart. It is slightly worse on a few lenient field validators (below).

## 4. Defects

Confirmed by running both builds:

**Gated**
- **A phone made only of punctuation is silently dropped and marked `unverified`.** `phone="-"` with no country gives `Ann,,,unverified,,` and nothing in the report. `PHONE_CHARACTERS` accepts it, the digits come out empty, and the unknown-country path returns `Phone(value="", status=PHONE_UNVERIFIED, problem=None)`. Spec: an invalid phone must go to the report.
- **An all-empty row `,,,,` is skipped without a report** (`if not any(value.strip() ...): continue`), and it is left out of `rows_read`. Spec: a row without a name is rejected in the report. Ungated reports it as `missing name`.
- **A short record silently reads its missing columns as empty** (1d).
- **Lenient validators:**
  - `a@..com` is accepted as an email (`[^@\s]+` allows dots).
  - `0000-01-01` is accepted as a birthday.
  - Unknown-country phones have no length check, so `"1"` is kept as unverified.
- **An unwritable `--output` or `--report` is uncaught.** `write_contacts` raises `OSError`, which gives a traceback and exit 1, the same code as "rows reported".

**Ungated**
- **Row numbers drift after a blank line.** `enumerate(rows, start=2)` runs over `DictReader`, which skips blank lines. With one blank line, the birthday on file row 6 is reported as row 5, and `0000-01-01` on row 10 as row 9. Quoted multi-line fields cause the same drift. Spec: the report gives the row number.
- **Malformed CSV is accepted.** An unterminated quote (`name\n"Ann\n`) exits 0 instead of 2, because the reader is non-strict.
- **Extra fields are dropped silently.** `Eve,e@x.com,555,,US,extra` keeps the row, and the extra value disappears under `DictReader`'s `None` key.
- **Duplicate headers resolve silently to the last column.**
- **An unwritable output is uncaught** (traceback, exit 1), as in gated.
- **Extra rule not in the spec:** future birthdays are rejected against `date.today()`, which makes results depend on the date they are run.

**Spec interpretation (not counted as defects):**
- A `+44…` phone with country `US`: gated reports it as "not a US number"; ungated verifies it as a GB number from its own country code.
- Merges exit 0 in both builds.

## 5. Recommendations

1. **MAGIC001, catch numbers moved into strings.** Flag a whitespace-only string passed to an argument documented as numeric (`indent=`, `width=`, `sep=` repetition), or more generally a string literal that is just N repeated characters standing in for a count. That would have caught `indent="  "`.
2. **MAGIC001, catch length arithmetic that rebuilds a constant.** Treat `len(<module attribute or literal collection>) ± literal` assigned to a module constant as a magic-number derivation, and suggest the plain named literal. That would have caught `len(calendar.month_name) - 1`.
3. **MAGIC001, narrow it for named constants.** Do not flag `UPPER_CASE = <int>` at module level when the name is not a spelled-out number (`TWO`, `N2`). `EXIT_UNREADABLE_INPUT = 2` needed a suppression for no good reason. The restating-name check (`TWO = 2`) would keep the rule's intent.
4. **DEF005, narrow it and close the loophole.**
   - Inside a declared boundary file, allow `return <NAMED_EXIT_CONSTANT>` from a handler that also writes to stderr. That is an exit-status mapping, not a success-shaped fallback.
   - Wherever the rule does apply, treat `raise SystemExit(...)` in a handler the same as `return`, so the rewrite in 1c isn't a free pass.
   - Skill wording: "If DEF005 fires on a CLI that maps an error to a spec-mandated exit code, declare the boundary or report it as a false positive. Do not convert it to `raise SystemExit`."
5. **New rule for guarded fallbacks.** Flag a function whose guard is `x not in mapping or i >= len(seq)` and whose body returns `""`, `None`, `0` or `[]`. These are the membership and length versions of a caught `KeyError`/`IndexError`. Require the guard's two cases to be separated and justified. That would have caught `cell()`'s short-record fallback.
6. **Skill wording on empty-but-present inputs.** "A value that passes a character filter but is empty after normalization is invalid, not empty." This targets the gated phone `"-"` bug: the result-object style made the empty `Phone(...)` look like the legitimate `EMPTY_PHONE` path.
