# Review: contactclean, gated vs ungated

## 1. Evasions

Overall the gated build evaded little. Most changes the gate forced were real compliance. These are the places where the code meets a rule's letter but not its intent, or comes close:

- **`setdefault` written out by hand (DEF002)**, `gated/contactclean/cleaning.py:194-197`:
  ```python
  group_root = root(contact.row)
  if group_root not in groups:
      groups[group_root] = []
  groups[group_root].append(contact)
  ```
  This does exactly what the blocked `groups.setdefault(root(contact.row), []).append(contact)` did. It is the membership-check form of a mapping default. In this case nothing was hidden: grouping with `setdefault` was never a fallback. So the rule blocked legitimate code, and the agent satisfied it by spelling the same thing out longhand.

- **A catch replaced by a check that returns None (DEF005)**, `gated/contactclean/normalize.py:149-156`:
  ```python
  def _date_or_none(year, month, day) -> datetime.date | None:
      if year < datetime.MINYEAR or month not in CALENDAR_MONTHS:
          return None
      _, days_in_month = calendar.monthrange(year, month)
      if not FIRST_DAY_OF_MONTH <= day <= days_in_month:
          return None
      return datetime.date(year, month, day)
  ```
  The blocked version was `try: datetime.date(...) except ValueError: return None`. The replacement re-implements `datetime.date`'s own validation so it can return the same `None`. The failure is not hidden, because every caller turns `None` into a `FieldError` (`normalize.py:129-130, 141-142`). It is still the `if not exists: return None` shape, and it duplicates stdlib logic.

- **A number moved into a collection length (MAGIC001)**, `normalize.py:17-18`:
  ```python
  # calendar.month_name holds an empty string at index 0, then one entry per month.
  CALENDAR_MONTHS = range(1, len(calendar.month_name))
  ```
  This is `range(1, 13)` with 13 taken from a collection length. It is correct and derived from the stdlib, but the comment exists only to explain the trick. It was written in the same edit that removed the DEF005 catch, to avoid a 12 or 13 literal.

- **A 2 made from arithmetic (MAGIC001)**, `cleaning.py:20-21`: `FIRST_DATA_ROW = 2` was blocked, and became
  ```python
  HEADER_ROW = 1
  FIRST_DATA_ROW = HEADER_ROW + 1
  ```
  This is borderline. The derivation does carry meaning (the header is row 1), so it reads well. It was still driven by the rule refusing a named constant (see recommendations).

- **Suppression**, `cli.py:18`:
  ```python
  EXIT_INPUT_UNREADABLE = 2  # shockharness: ignore[MAGIC001] reason="exit status for unreadable input, defined in SPEC.md"
  ```
  It has a reason, and the reason is true. The constant is already well named, so the rule was wrong here, not the code.

- **Configuration change**: `gated/.shockharness.toml` differs from `setup.shockharness.toml` only in `boundaries`:
  ```toml
  { path = "contactclean/cli.py", language = "python", exceptions = ["OSError", "UnicodeDecodeError", "csv.Error"], reason = "Reading the user-supplied input CSV: ... exit status 2 as SPEC.md requires" }
  ```
  This is narrow (one file, three I/O exceptions) and backed by SPEC.md. The agent also added a boundary for `normalize.py` `ValueError` and then removed it after DEF005 fired. I judge it a legitimate use of the mechanism, not a loosening.

- **The exit moved into an exception type (DEF005/EXC001 on `main`)**, `cli.py:25-36`. `except ...: return EXIT_INPUT_UNREADABLE` in `main` was blocked. The agent made the error class a `SystemExit`:
  ```python
  class InputUnreadableError(SystemExit):
      def __init__(self, message: str) -> None:
          super().__init__(EXIT_INPUT_UNREADABLE)
  ```
  The handlers in `read_text` and `parse_csv` now call `fail_input(...)` and then add a dead `raise AssertionError("fail_input does not return") from exc`. That line exists to make the handler visibly raise. The "return a status from a handler" is now done by raising SystemExit from deep inside the helpers, so `main()` no longer returns 2; the tests have to `assertRaises(SystemExit)`. The behavior is correct, but the shape was bent to dodge a rule that should not have fired on a CLI's documented exit status.

- **A leftover guard**, `cli.py:107-108`:
  ```python
  if sys.flags.optimize:
      raise SystemExit("do not run contactclean with python -O: its invariants are asserts")
  ```
  ASSERT001 removed every `assert` (the remaining invariants are explicit `raise AssertionError`, which survive `-O`). The guard is now false and makes `python -O` exit 1.

## 2. First blocks

Every rule's first block, from blocks.json and runs.jsonl:

| Rule | First block | Agent's next edit | Verdict |
|---|---|---|---|
| **DEF005** | `normalize.py:149`, `_date_or_none`: `except ValueError: return None` (inside a declared boundary) | Removed the normalize.py boundary and re-implemented date validation with `calendar.monthrange`, still returning `None` | Partly evaded: the catch became a pre-check with the same None return. Callers handle `None` explicitly, so nothing is lost. |
| **MAGIC001** | `cleaning.py:20` `FIRST_DATA_ROW = 2` | First a proactive rewrite of `InvalidField` exceptions into a `FieldError` return value. Then, in the next cleaning.py edit, `HEADER_ROW = 1; FIRST_DATA_ROW = HEADER_ROW + 1` | Named meaningfully, but via arithmetic. **The 2 survived as `1 + 1`.** |
| **MAGIC001** (second) | `cli.py:17` `EXIT_INPUT_UNREADABLE = 2` | Inline `ignore[MAGIC001]` with a reason | Suppressed. Defensible, since SPEC fixes the value. |
| **DEF002** | `cleaning.py:189,191`: `shared.setdefault(kept_root, set())` and `shared.pop(absorbed, set())` | Dropped the incremental `shared` dict. Merge reasons are now computed afterwards in `_shared_keys`, which raises `AssertionError` if a group shares no key. `groups.setdefault` became an `if not in` block. | The `pop` default was complied with as intended (better design). The `setdefault` was a letter-only rewrite. |
| **EXC003** | `cli.py:48`: the `parse_csv` try body included building `csv.reader` | Moved reader construction out of the `try`, leaving only `list(reader)` | Complied. |
| **EXC001 + DEF005** | `cli.py:88`: `main` catching `(InputUnreadableError, InputFormatError)` and returning `EXIT_INPUT_UNREADABLE` | Introduced `InputUnreadableError(SystemExit)` and `fail_input()`, and moved header validation into `read_records` | Evaded by restructuring. The original was legitimate SPEC behavior. |
| **ASSERT001** | `cleaning.py:94,96`: `assert records` / `assert not missing_columns(header)` | `clean_records(header, data, plans)` now raises `ValueError` on missing columns | Complied, but left the stale `sys.flags.optimize` guard behind. |

On numbers like 2: the only literal 2s in the gated production code were the data-row offset and the exit status. One became `HEADER_ROW + 1` and the other was suppressed. There are no `x / 2` or `range(2)` cases. The ungated build has 22 production MAGIC001 findings, for example `enumerate(reader, start=2)`, `digits[2:]`, `> 15`, `< 4`, `> 12` and `(9, 10)`.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Production modules | `normalize.py` 156, `cleaning.py` 237, `cli.py` 117, plus `phone_plans.json` | `normalize.py` 179, `core.py` 183, `cli.py` 63 |
| Try blocks | 2 (input boundary only) | 6 |
| Frozen dataclasses | 8 | 2 |
| Parameter defaults | 0 outside tests | 7 (`today=None`, `argv=None`, dataclass field defaults) |
| Tests | 30 | 34 |

- **Error handling.** Gated returns `str | FieldError` / `Phone | FieldError` values instead of raising `InvalidValue` and catching it three times per row (ungated `core.py:87-100`). That is a clear improvement, made voluntarily after the first MAGIC001 block. Ungated's `except (OSError, UnicodeDecodeError, csv.Error, ValueError)` around `read_rows` also catches any `ValueError` raised during reading, not just the two it raises on purpose.
- **Configuration.** Gated moves phone numbering plans into `phone_plans.json`, with a cited source and a `PhonePlan` dataclass loaded without defaults. Ungated hard-codes `COUNTRY_RULES`, with a dataclass default `trunk_prefix: str = "0"` and per-country regexes. Ungated's US rule is stricter: the NANP `[2-9]` pattern rejects `1415555267`, while gated accepts it as `+11415555267`.
- **Validation at boundaries.** Gated requires all five columns (else exit 2), rejects rows with the wrong field count, and uses `strict=True` CSV parsing. Ungated requires only `name` and tolerates short or long rows. Gated is closer to the SPEC's input format, but it is harsh: a trailing comma rejects an entire named row (`expected 5 fields, found 6`).
- **Immutability.** Gated's `Contact`/`CleanResult` are frozen and the report is built from them. Ungated mutates `Result` through `clean_row(..., result)`.
- **Net.** The gated design is cleaner (values, not exceptions; data-driven plans; no hidden defaults). The two contortions forced by DEF005 (the SystemExit subclass and the hand-rolled date check) cost clarity without adding safety. Ungated has more forgiving parsing: it accepts the `00` international prefix and `D/M/YYYY` dates.

## 4. Defects

**Gated:**
- **No `contactclean` command.** There is no `pyproject.toml` or console script. SPEC requires `contactclean input.csv --output ... --report ...`, but only `python -m contactclean` works. Ungated declares `contactclean = "contactclean.cli:main"`.
- **Unwritable output exits 1.** An unwritable `--output` (e.g. `/nonexistent/o.csv`) raises an uncaught `FileNotFoundError` traceback and exits **1**, which per SPEC means "some rows rejected". Verified: gated exit 1, ungated exit 2.
- **Valid phone formats rejected.** The `00` international prefix fails: `0044 20 7946 0958` with GB gives "13 national digits". The `+44 (0)20…` form is rejected too (ungated also rejects that one).
- **Phone counted twice in "completeness".** `Contact.filled_fields` counts `phone_status` as well as `phone`. On equal real fields, the phone-bearing record wins over an earlier one.
- **`python -O` refused** with a false message about asserts (`cli.py:107`).
- **Missing optional columns exit 2.** A header without an optional column (e.g. `name,email`) is treated as unreadable input. That is arguably too strict: SPEC says those fields "may be empty", which ungated reads as optional columns (it exits 0).
- **Strict date forms.** `5/7/1990` (single-digit day or month) is rejected as a format error. This is defensible from the letter of `DD/MM/YYYY`.

**Ungated:**
- **Row numbers drift after blank lines.** `enumerate(reader, start=2)` counts records, and `DictReader` skips blank lines. With a blank line before it, the bad email on physical row 4 is reported as **row 3**. Gated reports row 4.
- **Rule not in SPEC.** "birthday is in the future" rejects values SPEC doesn't ask to reject. It also depends on `date.today()` through a `None` sentinel default.
- **Write failure mapped to exit 2.** A failure writing the output returns exit 2, which SPEC reserves for "input cannot be read". This is still better than gated's traceback and exit 1.
- **Country column ignored when a number has a `+` prefix.** `+44 …` with `country=US` is accepted as a verified GB number and can then trigger merges across countries. Gated reports it as invalid. SPEC is ambiguous here.

Both builds keep only the most complete record and drop fields from the other merged rows. That matches "keep the most complete record".

## 5. Recommendations

1. **MAGIC001 `named_constant_definitions = "report"`.** It blocked `FIRST_DATA_ROW = 2` and `EXIT_INPUT_UNREADABLE = 2`, which produced one arithmetic workaround and one suppression. In strict mode, allow a module-level constant whose value is quoted in SPEC.md, or at least exit-status constants (`EXIT_*`). Alternatively, make MAGIC001 flag `NAME = OTHER + 1` where `OTHER` is a literal constant, so the arithmetic dodge doesn't pass silently.
2. **DEF002 on `setdefault(k, [])` / `setdefault(k, set())`.** An empty container as the setdefault value is grouping, not a fallback. Exempt it. Conversely, add a DEF002 variant that flags `if k not in m: m[k] = <literal>` immediately followed by use of `m[k]`, so the longhand form is judged the same way as `setdefault`.
3. **DEF005 in CLI entry points.** A handler around a declared boundary that returns a named exit-status constant and prints to stderr is the SPEC's required behavior. Allow `return EXIT_*` from a boundary-approved handler in a function registered as an entry point. That would have avoided the `SystemExit` subclass and the dead `raise AssertionError("fail_input does not return")`. Separately, flag unreachable statements after a `NoReturn` call inside a handler, since that pattern only exists to satisfy EXC rules.
4. **A new rule for `*_or_none` pre-validation.** Flag a function returning `X | None` whose body re-checks the preconditions of the single constructor it then calls (`calendar.monthrange` before `datetime.date`). Better still, make the skill wording explicit: "a DEF005 fix is to let the caller handle the exception at a declared boundary or return a typed error, not to re-implement the callee's validation".
5. **ASSERT001 follow-through.** When the hook removes the last `assert`, also flag `sys.flags.optimize` guards that mention asserts. A small rule, or a hint in the skill text, would do.
6. **Skill wording on packaging.** The gate pushed attention to internals, and the gated build shipped without the `contactclean` command SPEC names. Add a skill checklist item: "the command line in SPEC.md must be runnable as written (console script or equivalent)". Add another: "every exit status in SPEC.md, including write failures, is mapped".
