import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addNote, updateText, togglePin, deleteNote, findNote, orderForDisplay, newId } from '../src/state.js';

test('add, edit, pin, delete without mutating input', () => {
  const empty = Object.freeze([]);
  let notes = addNote(empty, 'a', 'one');
  notes = addNote(notes, 'b');
  assert.deepEqual(notes, [{ id: 'a', text: 'one', pinned: false }, { id: 'b', text: '', pinned: false }]);
  const frozen = Object.freeze(notes);
  notes = updateText(frozen, 'b', 'two');
  assert.equal(findNote(notes, 'b').text, 'two');
  assert.equal(frozen[1].text, '');
  notes = togglePin(notes, 'b');
  assert.equal(findNote(notes, 'b').pinned, true);
  notes = togglePin(notes, 'b');
  assert.equal(findNote(notes, 'b').pinned, false);
  notes = deleteNote(notes, 'a');
  assert.deepEqual(notes.map((n) => n.id), ['b']);
  assert.equal(findNote(notes, 'a'), null);
});

test('pinned notes come first, order otherwise stable', () => {
  const notes = [
    { id: 'a', text: '', pinned: false },
    { id: 'b', text: '', pinned: true },
    { id: 'c', text: '', pinned: false },
    { id: 'd', text: '', pinned: true },
  ];
  assert.deepEqual(orderForDisplay(notes).map((n) => n.id), ['b', 'd', 'a', 'c']);
});

test('ids are unique even at the same timestamp', () => {
  const now = () => 1000;
  assert.notEqual(newId(now), newId(now));
});
