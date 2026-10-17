import test from "node:test";
import assert from "node:assert/strict";
import { NOT_EDITING, NO_NOTE, beginEdit, cancelEdit, pressOutside } from "../src/edit.js";
import { addNote, displayOrder, removeNote, togglePin, updateText } from "../src/notes.js";
import { STORAGE_KEYS, loadNotes, saveNotes } from "../src/storage.js";

function fakeStorage(initial) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, value),
  };
}

test("notes operations are immutable and ordered", () => {
  const empty = Object.freeze([]);
  const one = addNote(empty, "a");
  const two = addNote(one, "b");
  assert.equal(empty.length, 0);
  assert.equal(two.length, two[1].id);
  const pinned = togglePin(two, two[1].id);
  assert.deepEqual(displayOrder(pinned).map((n) => n.text), ["b", "a"]);
  assert.equal(updateText(pinned, two[0].id, "z")[0].text, "z");
  assert.equal(removeNote(pinned, two[0].id).length, one.length);
  assert.throws(() => removeNote(pinned, pinned.length + pinned.length), RangeError);
});

test("pressing outside the edited note saves it", () => {
  const first = 1;
  const second = first + 1;
  assert.deepEqual(pressOutside(first, NO_NOTE), { editingId: NOT_EDITING, saveId: first });
  assert.deepEqual(pressOutside(first, second), { editingId: NOT_EDITING, saveId: first });
  assert.deepEqual(pressOutside(first, first), { editingId: first, saveId: NOT_EDITING });
  assert.deepEqual(pressOutside(NOT_EDITING, second), { editingId: NOT_EDITING, saveId: NOT_EDITING });
});

test("switching notes saves the previous one; escape saves nothing", () => {
  const first = 1;
  const second = first + 1;
  assert.deepEqual(beginEdit(first, second), { editingId: second, saveId: first });
  assert.deepEqual(beginEdit(NOT_EDITING, first), { editingId: first, saveId: NOT_EDITING });
  assert.deepEqual(cancelEdit(), { editingId: NOT_EDITING, saveId: NOT_EDITING });
});

test("storage round trips", () => {
  const storage = fakeStorage({});
  assert.equal(loadNotes(storage).problem, null);
  const notes = addNote(Object.freeze([]), "hello");
  saveNotes(storage, notes);
  assert.deepEqual(loadNotes(storage).notes, notes);
});

test("unreadable stored data is reported and kept, board starts empty", () => {
  for (const raw of ["{not json", "{}", '[{"id":"x"}]']) {
    const storage = fakeStorage({ [STORAGE_KEYS.notes]: raw });
    const result = loadNotes(storage);
    assert.equal(result.notes.length, 0);
    assert.equal(typeof result.problem, "string");
    assert.equal(storage.getItem(STORAGE_KEYS.backup), raw);
  }
});
