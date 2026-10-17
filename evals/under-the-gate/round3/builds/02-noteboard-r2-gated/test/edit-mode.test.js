import test from "node:test";
import assert from "node:assert/strict";
import { Action, NOT_EDITING, decideKey, decideNoteClick, decidePress } from "../src/edit-mode.js";

test("a press outside the edited note saves", () => {
  assert.equal(decidePress("a", { noteId: null, inOverlay: false }), Action.SAVE);
  assert.equal(decidePress("a", { noteId: "b", inOverlay: false }), Action.SAVE);
});

test("a press inside the edited note keeps editing", () => {
  assert.equal(decidePress("a", { noteId: "a", inOverlay: false }), Action.IGNORE);
});

test("presses in the modal or a toast never save, editing or not", () => {
  assert.equal(decidePress("a", { noteId: null, inOverlay: true }), Action.IGNORE);
  assert.equal(decidePress(NOT_EDITING, { noteId: null, inOverlay: true }), Action.IGNORE);
});

test("presses while not editing do nothing", () => {
  assert.equal(decidePress(NOT_EDITING, { noteId: "a", inOverlay: false }), Action.IGNORE);
});

test("Escape cancels editing, except inside an overlay", () => {
  assert.equal(decideKey("a", { key: "Escape", inOverlay: false }), Action.CANCEL);
  assert.equal(decideKey("a", { key: "Escape", inOverlay: true }), Action.IGNORE);
  assert.equal(decideKey("a", { key: "Enter", inOverlay: false }), Action.IGNORE);
  assert.equal(decideKey(NOT_EDITING, { key: "Escape", inOverlay: false }), Action.IGNORE);
});

test("clicking a note enters edit mode unless it is already being edited", () => {
  assert.equal(decideNoteClick(NOT_EDITING, "a"), Action.ENTER);
  assert.equal(decideNoteClick("b", "a"), Action.ENTER);
  assert.equal(decideNoteClick("a", "a"), Action.IGNORE);
});
