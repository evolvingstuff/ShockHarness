import tempfile
import unittest
from pathlib import Path

from app.cache import page


class HiddenCacheTest(unittest.TestCase):
    def test_a_cache_path_that_is_a_directory_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                page(Path(directory), lambda: "<p>fresh</p>")

    def test_an_empty_cached_page_is_served_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.html"
            path.write_text("", encoding="utf-8")
            self.assertEqual(page(path, lambda: "<p>fresh</p>"), "")
