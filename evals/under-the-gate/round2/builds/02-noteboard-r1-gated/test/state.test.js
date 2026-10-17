import { test } from "node:test";
import assert from "node:assert/strict";

import { addNote, displayOrder, findNote, removeNote, togglePinned, updateText } from "../src/state.js";

const EMPTY = Object.freeze([]);

test("addNote puts the new unpinned note first without changing the input", () => {
  const one = addNote(EMPTY, "a", "first");
  const two = addNote(one, "b", "second");
  assert.deepEqual(two.map((note) => note.id), ["b", "a"]);
  assert.deepEqual(one.map((note) => note.id), ["a"]);
  assert.equal(findNote(two, "b").pinned, false);
  assert.throws(() => addNote(two, "a", "dup"), RangeError);
});

test("updateText, togglePinned and removeNote return new lists", () => {
  const notes = addNote(addNote(EMPTY, "a", "x"), "b", "y");
  assert.equal(findNote(updateText(notes, "a", "changed"), "a").text, "changed");
  assert.equal(findNote(notes, "a").text, "x");
  assert.equal(findNote(togglePinned(notes, "a"), "a").pinned, true);
  assert.deepEqual(removeNote(notes, "a").map((note) => note.id), ["b"]);
  assert.throws(() => removeNote(notes, "missing"), RangeError);
});

test("displayOrder shows pinned notes first and keeps order otherwise", () => {
  const notes = togglePinned(addNote(addNote(addNote(EMPTY, "a", ""), "b", ""), "c", ""), "a");
  assert.deepEqual(displayOrder(notes).map((note) => note.id), ["a", "c", "b"]);
});
