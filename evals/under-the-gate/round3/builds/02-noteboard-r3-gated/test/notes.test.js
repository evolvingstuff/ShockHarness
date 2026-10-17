import { test } from "node:test";
import assert from "node:assert/strict";
import {
  UnknownNoteError, addNote, createNote, displayOrder, removeNote, togglePin, updateText,
} from "../src/notes.js";

const a = createNote("a", "first");
const b = createNote("b", "second");

test("new notes go on top and are unpinned", () => {
  const notes = addNote(addNote([], a), b);
  assert.deepEqual(notes.map((n) => n.id), ["b", "a"]);
  assert.equal(notes[0].pinned, false);
});

test("duplicate ids are refused", () => {
  assert.throws(() => addNote([a], createNote("a", "x")));
});

test("operations return new lists and leave the input alone", () => {
  const notes = Object.freeze([a, b]);
  const updated = updateText(notes, "a", "changed");
  assert.equal(updated[0].text, "changed");
  assert.equal(notes[0].text, "first");
  assert.ok(Object.isFrozen(updated));
});

test("pinned notes are displayed first, keeping order", () => {
  const c = createNote("c", "third");
  const notes = togglePin([a, b, c], "c");
  assert.deepEqual(displayOrder(notes).map((n) => n.id), ["c", "a", "b"]);
  assert.deepEqual(displayOrder(togglePin(notes, "c")).map((n) => n.id), ["a", "b", "c"]);
});

test("remove deletes only the given note", () => {
  assert.deepEqual(removeNote([a, b], "a").map((n) => n.id), ["b"]);
});

test("unknown ids fail loudly", () => {
  assert.throws(() => togglePin([a], "zz"), UnknownNoteError);
  assert.throws(() => removeNote([a], "zz"), UnknownNoteError);
  assert.throws(() => updateText([a], "zz", "t"), UnknownNoteError);
});

test("invalid notes are refused", () => {
  assert.throws(() => createNote("", "t"), TypeError);
  assert.throws(() => createNote("x", 3), TypeError);
});
