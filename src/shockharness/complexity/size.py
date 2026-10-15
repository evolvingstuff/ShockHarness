"""Size measures, convention ``size/1``. Auxiliary numbers, never a quality verdict.

* ``logical_lines``: lines of the unit's span that carry code once comments are
  blanked out, minus the lines of nested units (a nested ``def``/``class``
  gives up its whole span; a nested lambda/arrow only its interior lines, so
  a one-line lambda is counted in both the lambda and its parent).
* ``parameters``: the unit's own parameters, receivers (``self``, ``cls``)
  included, ``*args``/``**kwargs``/rest parameters counted once each; 0 for
  modules and class bodies.
* ``statements``: statements of the unit's own body; a nested function or
  class definition counts as one statement of the unit that contains it and
  its body is not counted. Python: every ``ast.stmt``; JavaScript: every
  statement and declaration node (blocks and labels are transparent).
"""

from typing import Any

from shockharness.ir.model import FunctionFact

CONVENTION = "size/1"


def size(fact: FunctionFact) -> dict[str, Any]:
    return {
        "logical_lines": fact.logical_lines,
        "parameters": fact.parameters,
        "statements": fact.statements,
    }
