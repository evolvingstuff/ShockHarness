import tempfile
import unittest
from pathlib import Path

from app.cache import page


class CacheTest(unittest.TestCase):
    def test_a_cached_page_is_served(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            path.write_text("<p>cached</p>", encoding="utf-8")
            self.assertEqual(page(path, lambda: "<p>fresh</p>"), "<p>cached</p>")

    def test_a_missing_cache_renders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            self.assertEqual(page(path, lambda: "<p>fresh</p>"), "<p>fresh</p>")


if __name__ == "__main__":
    unittest.main()
