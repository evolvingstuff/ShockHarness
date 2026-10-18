import unittest

from app.contracts import enable

enable("check", ["redacted"])

from app.assistant import summarize  # noqa: E402  (after enable, as a bootstrap does)


class FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "summary"


class HiddenRedactionTest(unittest.TestCase):
    def test_the_model_never_sees_an_address(self) -> None:
        client = FakeClient()
        summarize(client, "write to ada@example.com")
        self.assertEqual(client.prompts, ["write to [email]"])
