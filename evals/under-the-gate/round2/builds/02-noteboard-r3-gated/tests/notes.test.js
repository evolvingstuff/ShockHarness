import { test } from "node:test";
import assert from "node:assert/strict";
import { addNote, createNote, displayOrder, removeNote, togglePin, updateText } from "../src/notes.js";

const EMPTY = Object.freeze([]);

test("addNote puts the new note first and leaves the input unchanged", () => {
  const first = addNote(EMPTY, createNote("a", "one"));
  const second = addNote(first, createNote("b", "two"));
  assert.deepEqual(second.map((note) => note.id), ["b", "a"]);
  assert.deepEqual(first.map((note) => note.id), ["a"]);
  assert.ok(Object.isFrozen(second));
});

test("addNote refuses a duplicate id", () => {
  const notes = addNote(EMPTY, createNote("a", "one"));
  assert.throws(() => addNote(notes, createNote("a", "again")), RangeError);
});

test("updateText, togglePin and removeNote return new arrays", () => {
  const notes = addNote(addNote(EMPTY, createNote("a", "one")), createNote("b", "two"));
  const updated = updateText(notes, "a", "uno");
  assert.equal(updated.find((note) => note.id === "a").text, "uno");
  assert.equal(notes.find((note) => note.id === "a").text, "one");
  const pinned = togglePin(updated, "a");
  assert.equal(pinned.find((note) => note.id === "a").pinned, true);
  assert.equal(togglePin(pinned, "a").find((note) => note.id === "a").pinned, false);
  assert.deepEqual(removeNote(pinned, "b").map((note) => note.id), ["a"]);
});

test("operations on an unknown id throw", () => {
  assert.throws(() => updateText(EMPTY, "x", "t"), RangeError);
  assert.throws(() => togglePin(EMPTY, "x"), RangeError);
  assert.throws(() => removeNote(EMPTY, "x"), RangeError);
});

test("createNote validates its input", () => {
  assert.throws(() => createNote("", "t"), TypeError);
  assert.throws(() => createNote("a", null), TypeError);
});

test("displayOrder shows pinned notes first and keeps the rest in order", () => {
  let notes = EMPTY;
  for (const id of ["c", "b", "a"]) {
    notes = addNote(notes, createNote(id, id));
  }
  notes = togglePin(notes, "c");
  assert.deepEqual(displayOrder(notes).map((note) => note.id), ["c", "a", "b"]);
});
