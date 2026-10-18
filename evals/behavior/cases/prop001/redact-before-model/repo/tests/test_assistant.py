import unittest

from app.assistant import summarize


class FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "summary"


class SummarizeTest(unittest.TestCase):
    def test_returns_the_model_summary(self) -> None:
        client = FakeClient()
        self.assertEqual(summarize(client, "buy milk"), "summary")


if __name__ == "__main__":
    unittest.main()
