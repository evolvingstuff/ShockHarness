import { test } from "node:test";
import assert from "node:assert/strict";
import {
  KEY, LIST_CLICK, NOT_EDITING, PRESS, decideKey, decideListClick, decidePress,
} from "../src/editMode.js";

test("a press outside the edited note saves it", () => {
  assert.equal(decidePress({ editingId: "a", pressedNoteId: null, onOverlay: false }), PRESS.SAVE);
  assert.equal(decidePress({ editingId: "a", pressedNoteId: "b", onOverlay: false }), PRESS.SAVE);
});

test("a press inside the edited note does nothing", () => {
  assert.equal(decidePress({ editingId: "a", pressedNoteId: "a", onOverlay: false }), PRESS.IGNORE);
});

test("presses on the modal or a toast leave edit mode alone", () => {
  assert.equal(decidePress({ editingId: "a", pressedNoteId: null, onOverlay: true }), PRESS.IGNORE);
});

test("presses while not editing do nothing", () => {
  assert.equal(
    decidePress({ editingId: NOT_EDITING, pressedNoteId: "b", onOverlay: false }),
    PRESS.IGNORE,
  );
});

test("Escape cancels editing, or closes the modal first", () => {
  assert.equal(decideKey({ key: "Escape", editingId: "a", modalOpen: false }), KEY.CANCEL_EDIT);
  assert.equal(decideKey({ key: "Escape", editingId: "a", modalOpen: true }), KEY.CLOSE_MODAL);
  assert.equal(decideKey({ key: "Escape", editingId: NOT_EDITING, modalOpen: true }), KEY.CLOSE_MODAL);
  assert.equal(decideKey({ key: "Escape", editingId: NOT_EDITING, modalOpen: false }), KEY.IGNORE);
  assert.equal(decideKey({ key: "a", editingId: "a", modalOpen: false }), KEY.IGNORE);
});

test("list clicks: toolbar buttons, entering edit mode, and the edited note", () => {
  assert.equal(decideListClick({ noteId: "a", action: "pin", editingId: NOT_EDITING }), LIST_CLICK.PIN);
  assert.equal(decideListClick({ noteId: "a", action: "delete", editingId: "a" }), LIST_CLICK.DELETE);
  assert.equal(decideListClick({ noteId: "a", action: null, editingId: NOT_EDITING }), LIST_CLICK.EDIT);
  assert.equal(decideListClick({ noteId: "a", action: null, editingId: "a" }), LIST_CLICK.NONE);
  assert.equal(decideListClick({ noteId: null, action: null, editingId: "a" }), LIST_CLICK.NONE);
  assert.throws(() => decideListClick({ noteId: "a", action: "explode", editingId: null }));
});
