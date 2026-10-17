import unittest

from app.service import audit_database, main_database


class DsnTest(unittest.TestCase):
    def test_both_databases(self) -> None:
        self.assertEqual(main_database("db", "postgresql"), "postgresql://db/orders")
        self.assertEqual(audit_database("db", "mysql"), "mysql://db/audit")


if __name__ == "__main__":
    unittest.main()
