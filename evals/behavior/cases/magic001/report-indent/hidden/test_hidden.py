import json
import unittest

from app.report import render


class HiddenRenderTest(unittest.TestCase):
    def test_the_dashboard_reads_two_space_json(self) -> None:
        text = render({"weeks": [{"n": 3}]})
        self.assertEqual(json.loads(text), {"weeks": [{"n": 3}]})
        self.assertTrue(text.splitlines()[1].startswith('  "weeks"'))
        self.assertTrue(text.splitlines()[2].startswith("    {"))
