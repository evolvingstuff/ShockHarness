import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ACTION_CANCEL,
  ACTION_NONE,
  ACTION_SAVE,
  NOT_EDITING,
  isEditing,
  keyAction,
  pressAction,
  startEditing,
  withDraft,
} from "../src/editing.js";

const OUTSIDE_OVERLAY = false;
const IN_OVERLAY = true;
const NO_NOTE = null;

test("pressing outside the edited note saves it", () => {
  const editing = startEditing("a", "text");
  assert.equal(pressAction(editing, NO_NOTE, OUTSIDE_OVERLAY), ACTION_SAVE);
  assert.equal(pressAction(editing, "b", OUTSIDE_OVERLAY), ACTION_SAVE);
});

test("pressing inside the edited note keeps editing", () => {
  assert.equal(pressAction(startEditing("a", "text"), "a", OUTSIDE_OVERLAY), ACTION_NONE);
});

test("pressing in a modal or toast leaves edit mode alone", () => {
  assert.equal(pressAction(startEditing("a", "text"), NO_NOTE, IN_OVERLAY), ACTION_NONE);
});

test("presses do nothing when no note is being edited", () => {
  assert.equal(pressAction(NOT_EDITING, NO_NOTE, OUTSIDE_OVERLAY), ACTION_NONE);
  assert.equal(pressAction(NOT_EDITING, "a", OUTSIDE_OVERLAY), ACTION_NONE);
});

test("Escape cancels editing; other keys do nothing", () => {
  const editing = startEditing("a", "text");
  assert.equal(keyAction(editing, "Escape"), ACTION_CANCEL);
  assert.equal(keyAction(editing, "Enter"), ACTION_NONE);
  assert.equal(keyAction(NOT_EDITING, "Escape"), ACTION_NONE);
});

test("the draft follows typing and cannot change outside edit mode", () => {
  const editing = withDraft(startEditing("a", "text"), "new text");
  assert.equal(editing.draft, "new text");
  assert.equal(editing.noteId, "a");
  assert.ok(isEditing(editing));
  assert.ok(!isEditing(NOT_EDITING));
  assert.throws(() => withDraft(NOT_EDITING, "x"), Error);
});
