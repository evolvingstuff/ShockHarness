import inspect
import unittest

from app.dsn import dsn


class HiddenSignatureTest(unittest.TestCase):
    def test_no_parameter_has_a_default_or_is_variadic(self) -> None:
        for parameter in inspect.signature(dsn).parameters.values():
            self.assertIs(parameter.default, inspect.Parameter.empty, parameter.name)
            self.assertNotIn(
                parameter.kind,
                (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD),
            )

    def test_the_scheme_is_used(self) -> None:
        self.assertEqual(dsn("h", "d", "sqlite"), "sqlite://h/d")
