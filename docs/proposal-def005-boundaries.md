# Proposal: DEF005 inside a declared boundary (decision 37, draft)

Status: **draft, waiting on Tom.** From the under-the-gate experiment, round 3
(`evals/under-the-gate/RESULTS-round3.md`, finding 5). Nothing here is built.

## What happened

DEF005 reports a handler that returns a value (a literal, a constant, an empty
container) instead of raising: the classic silent default. It reports it even when the
catch sits in a boundary the project declared on purpose. Round 3 had two such cases;
in both, the agent kept the behavior and made the code worse to get past the rule.

1. **The process edge.** contactclean r3, in `main()`:

   ```python
   except InputError as exc:
       print(f"contactclean: {exc}", file=sys.stderr)
       return EXIT_UNREADABLE_INPUT          # SPEC.md: exit 2
   ```

   DEF005 reported `return EXIT_UNREADABLE_INPUT`. The agent changed it to
   `raise SystemExit(EXIT_UNREADABLE_INPUT) from exc`. The behavior is the same, but
   `main() -> int` now raises on one path, its docstring had to say so, and its tests had to
   catch `SystemExit`. contactclean r1 went further: its error class became a `SystemExit`
   subclass. An exit status of 2 is not success-shaped. It is how a command line reports
   failure, and SPEC.md asked for exactly that.

2. **An optional value.** contactclean r1, parsing a date:

   ```python
   try:
       return datetime.date(year, month, day)
   except ValueError:
       return None
   ```

   Every caller turned `None` into a reported field error, so nothing was hidden. The agent
   replaced it with a function that re-implements `datetime.date`'s own validation
   (`MINYEAR`, the month range, `calendar.monthrange`) so it could return the same `None`
   without a catch.

## Options

* **(a) Leave DEF005 as it is.** A boundary approves *catching*, not *returning a
  default*. The rule stays simple. Agents keep producing the round-3 workarounds.
* **(b) Exempt the process edge only.** Inside a declared boundary, a handler in the
  program's entry point is not a DEF005 finding when it returns a named non-zero exit
  status (`return EXIT_USAGE`, not `return 0` and not a bare literal). The entry point is:
  * a function named `main`; or
  * a function called from `if __name__ == "__main__":`; or
  * a function named in `[project.scripts]` of the project's `pyproject.toml`.

  JavaScript's equivalent would be `process.exitCode = EXIT_X` in a handler, which DEF005
  does not report today. Case 1 becomes the honest form; case 2 stays a finding.
* **(c) Also exempt a `None` returned to callers that all check for it.** That needs a
  cross-function trace: every caller of the function tests `is None` and raises or
  reports. It would cover case 2, but it is a much bigger change, and a `None` that every
  caller must remember to check is exactly what DEF005 exists to discourage.

**Recommendation: (b), plus remediation wording for case 2.** Case 1 is a false positive,
because an exit status is the edge's failure report. Case 2 is DEF005 working as
designed. The workaround is the problem, and better wording addresses it: DEF005's
remediation and the skills would say not to re-implement a library's validation to
avoid its exception. Raise a typed error from the handler (`raise InvalidDate(...) from
exc`), or return a result type that callers must handle.

## Questions for Tom

1. (b), (a), or (c)?
2. If (b): is `main` / `__main__` / `[project.scripts]` the right definition of the entry
   point, and must the exit status be a named constant (not a bare `2`)?

## Work, if (b)

* Python: an entry-point check on the handler's enclosing function. The return value must
  be a name bound at module level to a non-zero integer, which DEF005's one-step trace
  already resolves. The handler must also sit inside a boundary that approves the caught
  type.
* Tests for each entry-point form, a zero or bare-literal return (still reported), and a
  non-entry function (still reported).
* The remediation wording, one line in `fix-violations`, and `docs/rules.md`.

About half a session.
