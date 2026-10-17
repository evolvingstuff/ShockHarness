import { test } from "node:test";
import assert from "node:assert/strict";
import {
  KEY,
  NOTE_CLICK,
  NOT_EDITING,
  PRESS,
  beginEdit,
  commitEdit,
  decideKey,
  decideNoteClick,
  decidePress,
  deleteNote,
  withDraft,
} from "../src/edit-mode.js";
import { createNote } from "../src/notes.js";

const notes = [createNote("a", "alpha"), createNote("b", "beta")];

test("clicking a note begins editing with its text as the draft", () => {
  assert.equal(decideNoteClick(NOT_EDITING, "a"), NOTE_CLICK.BEGIN);
  const session = beginEdit(notes, "a");
  assert.deepEqual({ ...session }, { editingId: "a", draft: "alpha" });
  assert.equal(decideNoteClick(session, "a"), NOTE_CLICK.IGNORE);
  assert.equal(decideNoteClick(session, "b"), NOTE_CLICK.BEGIN);
});

test("a press outside the edited note saves", () => {
  const session = beginEdit(notes, "a");
  assert.equal(decidePress(session, { noteId: null, onFloatingControl: false }), PRESS.SAVE);
  assert.equal(decidePress(session, { noteId: "b", onFloatingControl: false }), PRESS.SAVE);
});

test("a press inside the edited note does nothing", () => {
  const session = beginEdit(notes, "a");
  assert.equal(decidePress(session, { noteId: "a", onFloatingControl: false }), PRESS.IGNORE);
});

test("presses on the modal or a toast never end edit mode", () => {
  const session = beginEdit(notes, "a");
  assert.equal(decidePress(session, { noteId: null, onFloatingControl: true }), PRESS.IGNORE);
});

test("presses while not editing do nothing", () => {
  assert.equal(decidePress(NOT_EDITING, { noteId: null, onFloatingControl: false }), PRESS.IGNORE);
  assert.equal(decidePress(NOT_EDITING, { noteId: "a", onFloatingControl: false }), PRESS.IGNORE);
});

test("Escape cancels only while editing", () => {
  assert.equal(decideKey(beginEdit(notes, "a"), "Escape"), KEY.CANCEL);
  assert.equal(decideKey(beginEdit(notes, "a"), "Enter"), KEY.IGNORE);
  assert.equal(decideKey(NOT_EDITING, "Escape"), KEY.IGNORE);
});

test("committing writes the draft and leaves edit mode", () => {
  const session = withDraft(beginEdit(notes, "a"), "edited");
  const result = commitEdit(notes, session);
  assert.equal(result.notes[0].text, "edited");
  assert.equal(result.session, NOT_EDITING);
  assert.throws(() => commitEdit(notes, NOT_EDITING));
  assert.throws(() => withDraft(NOT_EDITING, "x"));
});

test("deleting the edited note leaves edit mode; deleting another keeps it", () => {
  const session = withDraft(beginEdit(notes, "a"), "draft");
  const own = deleteNote(notes, session, "a");
  assert.deepEqual(own.notes.map((n) => n.id), ["b"]);
  assert.equal(own.session, NOT_EDITING);
  const other = deleteNote(notes, session, "b");
  assert.deepEqual(other.notes.map((n) => n.id), ["a"]);
  assert.equal(other.session, session);
});
