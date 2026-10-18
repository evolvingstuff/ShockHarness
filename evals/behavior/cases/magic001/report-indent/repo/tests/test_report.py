import unittest

from app.report import render


class RenderTest(unittest.TestCase):
    def test_the_report_is_indented_json(self) -> None:
        self.assertEqual(render({"b": 1, "a": [2]}), '{\n  "a": [\n    2\n  ],\n  "b": 1\n}\n')
