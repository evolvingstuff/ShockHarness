import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CLICK_BEGIN_EDIT,
  CLICK_IGNORE,
  KEY_CANCEL,
  KEY_IGNORE,
  NOT_EDITING,
  PRESS_IGNORE,
  PRESS_SAVE,
  afterRemoval,
  beginEditing,
  decideKey,
  decideNoteClick,
  decidePress,
  withDraft,
} from "../src/editMode.js";
import { createNote } from "../src/notes.js";

const editingA = beginEditing(createNote("a", "hello"));

test("beginEditing starts with the note's text as the draft", () => {
  assert.deepEqual({ ...editingA }, { active: true, id: "a", draft: "hello" });
  assert.equal(withDraft(editingA, "changed").draft, "changed");
  assert.equal(editingA.draft, "hello");
  assert.throws(() => withDraft(NOT_EDITING, "x"));
});

test("a press outside the edited note saves it", () => {
  assert.equal(decidePress(editingA, { noteId: "b", inDialog: false }), PRESS_SAVE);
  assert.equal(decidePress(editingA, { noteId: null, inDialog: false }), PRESS_SAVE);
});

test("a press inside the edited note, inside a dialog, or with nothing edited does not save", () => {
  assert.equal(decidePress(editingA, { noteId: "a", inDialog: false }), PRESS_IGNORE);
  assert.equal(decidePress(editingA, { noteId: null, inDialog: true }), PRESS_IGNORE);
  assert.equal(decidePress(NOT_EDITING, { noteId: null, inDialog: false }), PRESS_IGNORE);
});

test("Escape cancels editing unless a dialog is open", () => {
  assert.equal(decideKey(editingA, { key: "Escape", dialogOpen: false }), KEY_CANCEL);
  assert.equal(decideKey(editingA, { key: "Escape", dialogOpen: true }), KEY_IGNORE);
  assert.equal(decideKey(editingA, { key: "Enter", dialogOpen: false }), KEY_IGNORE);
  assert.equal(decideKey(NOT_EDITING, { key: "Escape", dialogOpen: false }), KEY_IGNORE);
});

test("clicking a note begins editing it unless it is already being edited", () => {
  assert.equal(decideNoteClick(NOT_EDITING, "a"), CLICK_BEGIN_EDIT);
  assert.equal(decideNoteClick(editingA, "b"), CLICK_BEGIN_EDIT);
  assert.equal(decideNoteClick(editingA, "a"), CLICK_IGNORE);
});

test("deleting the edited note leaves edit mode; deleting another keeps it", () => {
  assert.equal(afterRemoval(editingA, "a"), NOT_EDITING);
  assert.equal(afterRemoval(editingA, "b"), editingA);
});
