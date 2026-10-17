import { test } from "node:test";
import assert from "node:assert/strict";

import { addNote, createNote, deleteNote, displayOrder, togglePin, updateText } from "../src/notes.js";

const board = () => addNote(addNote([], createNote("a", "first")), createNote("b", "second"));

test("new notes are added at the top, unpinned", () => {
  const notes = board();
  assert.deepEqual(notes.map((note) => note.id), ["b", "a"]);
  assert.equal(notes[0].pinned, false);
});

test("operations return new lists and leave the input unchanged", () => {
  const notes = board();
  const edited = updateText(notes, "a", "changed");
  assert.equal(notes.find((note) => note.id === "a").text, "first");
  assert.equal(edited.find((note) => note.id === "a").text, "changed");
  assert.ok(Object.isFrozen(edited));
});

test("pinned notes are displayed first", () => {
  const notes = togglePin(board(), "a");
  assert.deepEqual(displayOrder(notes).map((note) => note.id), ["a", "b"]);
  assert.deepEqual(displayOrder(togglePin(notes, "a")).map((note) => note.id), ["b", "a"]);
});

test("deleting removes only that note", () => {
  assert.deepEqual(deleteNote(board(), "b").map((note) => note.id), ["a"]);
});

test("unknown ids and duplicate ids are errors", () => {
  assert.throws(() => deleteNote(board(), "missing"), RangeError);
  assert.throws(() => togglePin(board(), "missing"), RangeError);
  assert.throws(() => addNote(board(), createNote("a", "again")), RangeError);
  assert.throws(() => createNote("", "x"), TypeError);
});
