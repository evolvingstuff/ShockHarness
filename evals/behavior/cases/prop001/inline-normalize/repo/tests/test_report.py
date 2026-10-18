import unittest

from app.report import score


class ScoreTest(unittest.TestCase):
    def test_score_of_a_series(self) -> None:
        self.assertAlmostEqual(score([1.0, 2.0, 3.0]), 2.449489742783178)


if __name__ == "__main__":
    unittest.main()
