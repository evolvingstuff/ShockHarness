import test from "node:test";
import assert from "node:assert/strict";
import { addNote, createNote, displayOrder, removeNote, togglePin, updateText } from "../src/notes.js";

const a = createNote("a", "first", 1);
const b = createNote("b", "second", 2);
const c = createNote("c", "third", 3);

test("addNote appends and rejects duplicate ids", () => {
  const notes = addNote(addNote([], a), b);
  assert.deepEqual(notes.map((n) => n.id), ["a", "b"]);
  assert.throws(() => addNote(notes, a), RangeError);
});

test("updateText returns a new list and leaves the input unchanged", () => {
  const before = Object.freeze([a, b]);
  const after = updateText(before, "a", "changed");
  assert.equal(after[0].text, "changed");
  assert.equal(before[0].text, "first");
  assert.ok(Object.isFrozen(after) && Object.isFrozen(after[0]));
});

test("togglePin flips pinned and displayOrder puts pinned notes first", () => {
  const notes = togglePin([a, b, c], "c");
  assert.equal(notes[2].pinned, true);
  assert.deepEqual(displayOrder(notes).map((n) => n.id), ["c", "a", "b"]);
  assert.deepEqual(displayOrder(togglePin(notes, "c")).map((n) => n.id), ["a", "b", "c"]);
});

test("removeNote removes, and operations on a missing id throw", () => {
  assert.deepEqual(removeNote([a, b], "a").map((n) => n.id), ["b"]);
  assert.throws(() => removeNote([a], "zzz"), RangeError);
  assert.throws(() => updateText([a], "zzz", "x"), RangeError);
  assert.throws(() => togglePin([a], "zzz"), RangeError);
});
