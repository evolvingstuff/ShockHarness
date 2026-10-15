import unittest

from app.pages import PageSettings, last_item, load_page_settings, paginate


class PagesTest(unittest.TestCase):
    def test_settings_are_required_and_validated(self) -> None:
        settings = load_page_settings({"PAGE_SIZE": "2", "MAX_PAGES": "3"})
        self.assertEqual(settings, PageSettings(page_size=2, max_pages=3))
        with self.assertRaises(KeyError):
            load_page_settings({"PAGE_SIZE": "2"})
        with self.assertRaisesRegex(ValueError, "PAGE_SIZE"):
            load_page_settings({"PAGE_SIZE": "0", "MAX_PAGES": "3"})
        with self.assertRaisesRegex(ValueError, "MAX_PAGES"):
            load_page_settings({"PAGE_SIZE": "2", "MAX_PAGES": "0"})

    def test_paginate_splits_and_caps(self) -> None:
        settings = PageSettings(page_size=2, max_pages=2)
        self.assertEqual(paginate(["a", "b", "c"], settings), [["a", "b"], ["c"]])
        with self.assertRaises(ValueError):
            paginate(["a", "b", "c", "d", "e"], settings)

    def test_last_item(self) -> None:
        self.assertEqual(last_item(["a", "b"]), "b")
        with self.assertRaises(IndexError):
            last_item([])


if __name__ == "__main__":
    unittest.main()
