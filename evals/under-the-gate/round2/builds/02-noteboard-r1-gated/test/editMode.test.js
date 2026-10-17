import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ACTION_CANCEL,
  ACTION_KEEP,
  ACTION_SAVE,
  ACTION_START,
  ESCAPE_KEY,
  PRESS_ELSEWHERE,
  PRESS_IN_EDITED_NOTE,
  PRESS_IN_OVERLAY,
  VIEWING,
  afterDelete,
  decideKey,
  decideNoteClick,
  decidePress,
  editing,
} from "../src/editMode.js";

test("a press outside the edited note saves it", () => {
  assert.equal(decidePress(editing("a"), PRESS_ELSEWHERE), ACTION_SAVE);
  assert.equal(decidePress(editing("a"), PRESS_IN_EDITED_NOTE), ACTION_KEEP);
});

test("presses on the modal or toast do not save or leave edit mode", () => {
  assert.equal(decidePress(editing("a"), PRESS_IN_OVERLAY), ACTION_KEEP);
});

test("presses while not editing do nothing", () => {
  assert.equal(decidePress(VIEWING, PRESS_ELSEWHERE), ACTION_KEEP);
  assert.throws(() => decidePress(VIEWING, "nowhere"), RangeError);
});

test("Escape cancels editing unless the modal is open", () => {
  assert.equal(decideKey(editing("a"), ESCAPE_KEY, false), ACTION_CANCEL);
  assert.equal(decideKey(editing("a"), ESCAPE_KEY, true), ACTION_KEEP);
  assert.equal(decideKey(editing("a"), "Enter", false), ACTION_KEEP);
  assert.equal(decideKey(VIEWING, ESCAPE_KEY, false), ACTION_KEEP);
});

test("clicking a note starts editing it unless it is already being edited", () => {
  assert.equal(decideNoteClick(VIEWING, "a"), ACTION_START);
  assert.equal(decideNoteClick(editing("a"), "a"), ACTION_KEEP);
  assert.equal(decideNoteClick(editing("a"), "b"), ACTION_START);
});

test("deleting the edited note leaves edit mode; deleting another does not", () => {
  assert.deepEqual(afterDelete(editing("a"), "a"), VIEWING);
  assert.deepEqual(afterDelete(editing("a"), "b"), editing("a"));
});
