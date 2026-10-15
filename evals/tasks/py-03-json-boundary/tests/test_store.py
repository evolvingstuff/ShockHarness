import unittest

from app.store import StoreError, load_store


class StoreTest(unittest.TestCase):
    def test_valid_store_loads(self) -> None:
        self.assertEqual(load_store('{"a": "1", "b": "2"}'), {"a": "1", "b": "2"})

    def test_malformed_json_is_a_store_error(self) -> None:
        with self.assertRaisesRegex(StoreError, "malformed"):
            load_store("{not json")

    def test_non_object_is_a_store_error(self) -> None:
        with self.assertRaises(StoreError):
            load_store("[1, 2]")

    def test_non_string_value_is_a_store_error(self) -> None:
        with self.assertRaises(StoreError):
            load_store('{"a": 1}')


if __name__ == "__main__":
    unittest.main()
