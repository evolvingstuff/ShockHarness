import test from 'node:test';
import assert from 'node:assert/strict';
import { addNote, deleteNote, sortForDisplay, togglePin, updateNoteText } from '../src/notes.js';

test('addNote appends an unpinned note', () => {
  const notes = addNote([], { id: 'x', text: 't', now: 5 });
  assert.deepEqual(notes, [{ id: 'x', text: 't', pinned: false, updatedAt: 5 }]);
});

test('addNote generates distinct ids', () => {
  const notes = addNote(addNote([]), {});
  assert.notEqual(notes[0].id, notes[1].id);
});

test('update, pin, delete do not mutate the input', () => {
  const start = Object.freeze([Object.freeze({ id: 'a', text: '', pinned: false, updatedAt: 0 })]);
  assert.equal(updateNoteText(start, 'a', 'new', 9)[0].text, 'new');
  assert.equal(togglePin(start, 'a')[0].pinned, true);
  assert.deepEqual(deleteNote(start, 'a'), []);
  assert.equal(start[0].text, '');
});

test('sortForDisplay puts pinned notes first and is stable', () => {
  const notes = [
    { id: '1', pinned: false }, { id: '2', pinned: true },
    { id: '3', pinned: false }, { id: '4', pinned: true },
  ];
  assert.deepEqual(sortForDisplay(notes).map((n) => n.id), ['2', '4', '1', '3']);
});
