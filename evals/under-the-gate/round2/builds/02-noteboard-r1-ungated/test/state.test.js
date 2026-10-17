import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as S from '../src/state.js';

const base = [
  { id: 'a', text: 'A', pinned: false },
  { id: 'b', text: 'B', pinned: false },
];

test('addNote prepends an unpinned note with a unique id', () => {
  const n = S.addNote(base, 'C');
  assert.equal(n.length, 3);
  assert.deepEqual({ ...n[0], id: undefined }, { id: undefined, text: 'C', pinned: false });
  assert.notEqual(S.newId(), S.newId());
});

test('updateText, togglePin and deleteNote do not mutate input', () => {
  const frozen = Object.freeze(base.map((n) => Object.freeze({ ...n })));
  assert.equal(S.findNote(S.updateText(frozen, 'b', 'x'), 'b').text, 'x');
  assert.equal(S.findNote(S.togglePin(frozen, 'a'), 'a').pinned, true);
  assert.deepEqual(S.deleteNote(frozen, 'a').map((n) => n.id), ['b']);
  assert.equal(S.findNote(frozen, 'zzz'), null);
});

test('sortedForDisplay puts pinned first, keeping order', () => {
  const notes = [
    { id: '1', pinned: false }, { id: '2', pinned: true },
    { id: '3', pinned: false }, { id: '4', pinned: true },
  ];
  assert.deepEqual(S.sortedForDisplay(notes).map((n) => n.id), ['2', '4', '1', '3']);
});
