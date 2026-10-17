import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addNote, updateNote, deleteNote, togglePin, findNote, sortForDisplay, newId } from '../src/state.js';

test('add, update, delete, pin', () => {
  let n = addNote([], { id: 'a', text: 'hi', now: 1 });
  n = addNote(n, { id: 'b', now: 2 });
  assert.deepEqual(n.map((x) => x.id), ['a', 'b']);
  const before = n;
  n = updateNote(n, 'a', 'hello', 5);
  assert.equal(findNote(n, 'a').text, 'hello');
  assert.equal(findNote(n, 'a').updatedAt, 5);
  assert.equal(findNote(before, 'a').text, 'hi', 'immutable');
  n = togglePin(n, 'b');
  assert.equal(findNote(n, 'b').pinned, true);
  n = deleteNote(n, 'a');
  assert.deepEqual(n.map((x) => x.id), ['b']);
  assert.equal(findNote(n, 'a'), null);
});

test('updating with unchanged text keeps timestamp', () => {
  const n = addNote([], { id: 'a', text: 'x', now: 1 });
  assert.equal(updateNote(n, 'a', 'x', 9)[0].updatedAt, 1);
});

test('pinned notes sort first, stable otherwise', () => {
  let n = ['a', 'b', 'c', 'd'].reduce((acc, id) => addNote(acc, { id }), []);
  n = togglePin(togglePin(n, 'c'), 'd');
  assert.deepEqual(sortForDisplay(n).map((x) => x.id), ['c', 'd', 'a', 'b']);
});

test('ids are unique', () => {
  const ids = new Set(Array.from({ length: 100 }, newId));
  assert.equal(ids.size, 100);
});
