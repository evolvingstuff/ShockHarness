import unittest

from app.chat import forward


class FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "summary"


class ForwardTest(unittest.TestCase):
    def test_forwards_the_note_verbatim(self) -> None:
        client = FakeClient()
        forward(client, "reply to ada@example.com")
        self.assertEqual(client.prompts, ["reply to ada@example.com"])


if __name__ == "__main__":
    unittest.main()
