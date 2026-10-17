import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addNote, updateText, togglePin, deleteNote, displayOrder, newId } from '../src/state.js';

const base = [
  { id: 'a', text: 'A', pinned: false },
  { id: 'b', text: 'B', pinned: false },
];

test('addNote prepends with defaults and does not mutate', () => {
  const r = addNote(base, { id: 'c' });
  assert.deepEqual(r[0], { id: 'c', text: '', pinned: false });
  assert.equal(base.length, 2);
});

test('updateText, togglePin, deleteNote', () => {
  assert.equal(updateText(base, 'b', 'new')[1].text, 'new');
  assert.equal(togglePin(base, 'a')[0].pinned, true);
  assert.equal(togglePin(togglePin(base, 'a'), 'a')[0].pinned, false);
  assert.deepEqual(deleteNote(base, 'a').map((n) => n.id), ['b']);
});

test('displayOrder puts pinned first, stable otherwise', () => {
  const notes = [...base, { id: 'c', text: '', pinned: true }];
  assert.deepEqual(displayOrder(notes).map((n) => n.id), ['c', 'a', 'b']);
});

test('newId is unique', () => {
  assert.notEqual(newId(1), newId(1));
});
