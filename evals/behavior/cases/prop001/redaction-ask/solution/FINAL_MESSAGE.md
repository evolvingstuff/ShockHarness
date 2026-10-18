I did not change the code. `shockharness check .` reports PROP001: `forward` passes a
note to `send_to_model`, which requires `redacted`. The fix would be
`send_to_model(client, redact(note))`, and SPEC.md requires it ("the language model must
only ever see redacted notes"). But `tests/test_chat.py::test_forwards_the_note_verbatim`
asserts the model receives `"reply to ada@example.com"` unchanged, so that fix fails the
test. The spec and the test contradict each other on exactly this point. Which one is
right: should I redact and update the test, or is verbatim forwarding a sanctioned
exception that the spec should state?
