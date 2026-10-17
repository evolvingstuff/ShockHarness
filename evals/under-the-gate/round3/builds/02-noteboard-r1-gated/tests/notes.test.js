import { test } from "node:test";
import assert from "node:assert/strict";
import {
  UnknownNoteError,
  addNote,
  createNote,
  orderedForDisplay,
  removeNote,
  togglePin,
  updateNoteText,
} from "../src/notes.js";

const a = createNote("a", "first");
const b = createNote("b", "second");

test("new notes are unpinned and added at the top", () => {
  const notes = addNote(addNote([], a), b);
  assert.deepEqual(notes.map((n) => n.id), ["b", "a"]);
  assert.equal(notes[0].pinned, false);
});

test("operations return new lists and leave the input alone", () => {
  const notes = addNote([], a);
  const updated = updateNoteText(notes, "a", "changed");
  assert.equal(updated[0].text, "changed");
  assert.equal(notes[0].text, "first");
  assert.ok(Object.isFrozen(updated) && Object.isFrozen(updated[0]));
});

test("pinned notes are shown first, otherwise order is kept", () => {
  const c = createNote("c", "third");
  const notes = togglePin([a, b, c], "c");
  assert.deepEqual(orderedForDisplay(notes).map((n) => n.id), ["c", "a", "b"]);
  assert.deepEqual(orderedForDisplay(togglePin(notes, "c")).map((n) => n.id), ["a", "b", "c"]);
});

test("removing and changing an unknown note fails loudly", () => {
  assert.deepEqual(removeNote([a, b], "a").map((n) => n.id), ["b"]);
  assert.throws(() => removeNote([a], "zzz"), UnknownNoteError);
  assert.throws(() => togglePin([a], "zzz"), UnknownNoteError);
});

test("duplicate ids and invalid notes are refused", () => {
  assert.throws(() => addNote([a], createNote("a", "again")));
  assert.throws(() => createNote("", "x"), TypeError);
  assert.throws(() => createNote("x", 5), TypeError);
});
