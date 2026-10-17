import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addNote, updateNoteText, togglePin, deleteNote, findNote, sortedForDisplay, newId } from '../src/state.js';

test('add, update, pin, delete without mutating input', () => {
  const empty = [];
  const one = addNote(empty, 'x', 10, 'a');
  assert.deepEqual(empty, []);
  assert.deepEqual(one, [{ id: 'a', text: 'x', pinned: false, updatedAt: 10 }]);
  const edited = updateNoteText(one, 'a', 'y', 20);
  assert.equal(one[0].text, 'x');
  assert.deepEqual(findNote(edited, 'a'), { id: 'a', text: 'y', pinned: false, updatedAt: 20 });
  assert.equal(updateNoteText(edited, 'a', 'y', 30)[0].updatedAt, 20, 'unchanged text keeps timestamp');
  assert.equal(togglePin(edited, 'a')[0].pinned, true);
  assert.deepEqual(deleteNote(edited, 'a'), []);
  assert.equal(findNote(edited, 'zz'), null);
});

test('ids are unique', () => {
  const ids = new Set(Array.from({ length: 1000 }, () => newId(5)));
  assert.equal(ids.size, 1000);
});

test('display order: pinned first, then newest', () => {
  const notes = [
    { id: 'old', text: '', pinned: false, updatedAt: 1 },
    { id: 'new', text: '', pinned: false, updatedAt: 3 },
    { id: 'pin', text: '', pinned: true, updatedAt: 0 },
  ];
  assert.deepEqual(sortedForDisplay(notes).map((n) => n.id), ['pin', 'new', 'old']);
});
