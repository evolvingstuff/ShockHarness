# Philosophy document: questions for Tom

The rules say *what* ShockHarness forbids. The philosophy document will say *why*,
from experience, so that an agent facing "determine the intended contract" has
something to reason from. Only you can answer these. Short answers are fine. A
story beats a principle, and "I'm not sure" is a useful answer too. I'll turn
the answers into `docs/philosophy.md`, and the skills will point to it.

## Where it started

1. What were you building when you started writing code this way, and what went
   wrong often enough that you changed how you write?
2. Was there one incident that convinced you? What did it cost (hours, data,
   trust)?
3. When you first adopted these habits, what did you expect to lose, and did you?
4. Which habit was the hardest to give up, and why?

## Failures are visible (no catch outside a boundary: EXC001-EXC004, DEF005)

5. Why did you stop writing `try`/`except` around ordinary code? What did the
   code that broke look like?
6. What does an acceptable boundary look like to you, and how do you decide
   that something is "the outside world"?
7. When a catch was the right call, what made it right?
8. What did your code look like a few months after you stopped? What got
   easier? What got harder?

## Absence is a decision, not a default (DEF001-DEF006, INPUT002)

9. Why are parameter defaults and `x or default` worse than a crash, in your
   experience? A specific bug would help.
10. When is a value really optional, and how do you write that so a reader can
    tell?
11. Where should configuration be validated, and what happens downstream of
    that point?
12. MetaList's `_mapping_value_or` reset eleven server-side fields on every
    edit. Is that the canonical example, or do you have an older one?

## Numbers have reasons (MAGIC001-MAGIC003)

13. Why `0` and `1` only, and not "small numbers"? What did a magic number cost
    you?
14. Fable argues that `2` in `x / 2` or `range(2)` is arithmetic, not policy. Do
    you agree? Where is the line between an identity and a decision?
15. What makes a named constant legitimate rather than a renamed literal
    (`TWO = 2`)?
16. Where should constants live, and what should their comments say?

## The verifier is not negotiable (VERIFY001-VERIFY004, ROLE001, SUPP001-SUPP002)

17. Have you seen a test skipped, an assertion weakened or a threshold raised to
    get a change through? What happened afterwards?
18. When is changing a test the right fix? How should an agent tell the
    difference?
19. What should an agent do when it believes a rule is wrong for its case:
    comply, suppress with a reason, or stop and ask? When each?

## Stubs and stand-ins (STUB001-STUB003)

20. What does an honest "not implemented yet" look like to you?
21. Is a hook that returns `True` by design ever fine, and how do you mark it?

## Results are used (RESULT001, PROCESS001, BATCH001, ASYNC001-ASYNC003)

22. What happens when exit codes, rejected promises or per-item failures are
    ignored? Is there a story behind these rules?

## Immutability (no rule yet)

23. What does "immutable by default" mean in your code day to day: frozen
    dataclasses, no mutation of arguments, `readonly` / `as const`, no
    reassignment?
24. Where do you allow mutation, and why there?
25. What would you want a rule to catch first?

## Complexity (CPLX001-CPLX006)

26. Why are the complexity rules advisory rather than gating? What would make
    you gate on them?

## For agents specifically

27. What do agents do that you would never do, and that these rules exist to stop?
28. If an agent could read only one paragraph before writing code in your
    projects, what should it say?
29. Where do you expect this philosophy *not* to generalize, for example code
    you don't control, prototypes, or teams?
