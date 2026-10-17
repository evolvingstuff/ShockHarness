import unittest

from app.paging import first_page


class PagingTest(unittest.TestCase):
    def test_first_page_holds_fifty_items(self) -> None:
        items = [str(i) for i in range(120)]
        self.assertEqual(len(first_page(items)), 50)


if __name__ == "__main__":
    unittest.main()
