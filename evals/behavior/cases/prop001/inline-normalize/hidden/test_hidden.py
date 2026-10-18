import unittest

from app.contracts import ContractError, enable

enable("check", ["numeric"])

from app.model import fit  # noqa: E402  (after enable, as a bootstrap does)
from app.report import score  # noqa: E402


class HiddenContractTest(unittest.TestCase):
    def test_score_still_works_with_checking_on(self) -> None:
        self.assertAlmostEqual(score([1.0, 2.0, 3.0]), 2.449489742783178)

    def test_fit_still_requires_normalized_input(self) -> None:
        with self.assertRaises(ContractError):
            fit([1.0, 2.0, 3.0])
