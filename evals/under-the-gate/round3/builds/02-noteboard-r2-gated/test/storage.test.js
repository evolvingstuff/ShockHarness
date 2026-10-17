import test from "node:test";
import assert from "node:assert/strict";
import { createNote } from "../src/notes.js";
import { parseNotes, readNotes, serializeNotes, UnreadableNotesError, writeNotes } from "../src/storage.js";
import { memoryStorage } from "./helpers.js";

const notes = [createNote("a", "hello", 1), { ...createNote("b", "pinned", 2), pinned: true }];

test("notes round-trip through storage", () => {
  const storage = memoryStorage({});
  writeNotes(storage, "k", notes);
  assert.deepEqual(readNotes(storage, "k"), notes);
});

test("nothing stored reads as an empty board", () => {
  assert.deepEqual(readNotes(memoryStorage({}), "k"), []);
});

test("invalid JSON is an UnreadableNotesError that keeps the raw text and cause", () => {
  assert.throws(
    () => parseNotes("{not json"),
    (err) => err instanceof UnreadableNotesError && err.raw === "{not json" && err.cause instanceof SyntaxError,
  );
});

test("wrong shapes are UnreadableNotesError", () => {
  const bad = [
    "null",
    "[]",
    JSON.stringify({ version: 99, notes: [] }),
    JSON.stringify({ version: 1, notes: {} }),
    JSON.stringify({ version: 1, notes: [{ id: "a", text: 5, pinned: false, createdAt: 1 }] }),
    JSON.stringify({ version: 1, notes: [notes[0], notes[0]] }),
  ];
  for (const raw of bad) {
    assert.throws(() => parseNotes(raw), UnreadableNotesError, raw);
  }
});

test("serialized format carries a version", () => {
  assert.equal(JSON.parse(serializeNotes([])).version, 1);
});
