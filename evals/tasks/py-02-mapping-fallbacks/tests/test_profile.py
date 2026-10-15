import unittest

from app.profile import summarize, years_active


class ProfileTest(unittest.TestCase):
    def test_summary_with_and_without_title(self) -> None:
        self.assertEqual(summarize({"name": "Ada", "title": "Engineer"}), "Ada (Engineer)")
        self.assertEqual(summarize({"name": "Ada"}), "Ada")

    def test_name_is_required(self) -> None:
        with self.assertRaises(KeyError):
            summarize({"title": "Engineer"})

    def test_years_active(self) -> None:
        self.assertEqual(years_active({"since": 2019}, 2026), 7)
        self.assertEqual(years_active({"since": 2026}, 2026), 0)

    def test_since_is_required_and_not_in_the_future(self) -> None:
        with self.assertRaises(KeyError):
            years_active({}, 2026)
        with self.assertRaises(ValueError):
            years_active({"since": 2030}, 2026)


if __name__ == "__main__":
    unittest.main()
