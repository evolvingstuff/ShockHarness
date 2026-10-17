import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, STORAGE_KEY, CORRUPT_KEY } from '../src/storage.js';

function fakeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

test('empty storage loads an empty board without error', () => {
  assert.deepEqual(loadNotes(fakeStorage()), { notes: [], error: null });
});

test('round-trips saved notes', () => {
  const s = fakeStorage();
  const notes = [{ id: 'a', text: 'hi', pinned: true }];
  assert.equal(saveNotes(s, notes), null);
  assert.deepEqual(loadNotes(s), { notes, error: null });
});

for (const [label, raw] of [
  ['invalid JSON', '{not json'],
  ['non-array JSON', '{"a":1}'],
  ['malformed notes', '[{"id":1}]'],
]) {
  test(`${label}: reported once, board starts empty, data kept`, () => {
    const s = fakeStorage({ [STORAGE_KEY]: raw });
    const first = loadNotes(s);
    assert.deepEqual(first.notes, []);
    assert.match(first.error, /could not be read/);
    assert.equal(s.data.get(CORRUPT_KEY), raw, 'unreadable data is preserved');
    assert.equal(s.data.has(STORAGE_KEY), false);

    const second = loadNotes(s);
    assert.deepEqual(second, { notes: [], error: null }, 'not reported again');
  });
}

test('still reports when the bad data cannot be backed up', () => {
  const s = fakeStorage({ [STORAGE_KEY]: 'garbage' });
  s.setItem = () => { throw new Error('quota'); };
  const r = loadNotes(s);
  assert.deepEqual(r.notes, []);
  assert.match(r.error, /could not be read/);
});

test('storage access failure is reported', () => {
  const r = loadNotes({ getItem() { throw new Error('denied'); } });
  assert.deepEqual(r.notes, []);
  assert.match(r.error, /denied/);
});

test('save failure returns a message', () => {
  const s = fakeStorage();
  s.setItem = () => { throw new Error('quota exceeded'); };
  assert.match(saveNotes(s, []), /quota exceeded/);
});
