import test from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, STORAGE_KEY, BACKUP_PREFIX } from '../src/storage.js';

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => void data.set(k, String(v)),
    removeItem: (k) => void data.delete(k),
  };
}

const note = { id: 'a', text: 'hello', pinned: false, updatedAt: 1 };

test('empty storage loads an empty board without error', () => {
  assert.deepEqual(loadNotes(memoryStorage()), { notes: [], error: null });
});

test('saved notes round-trip', () => {
  const s = memoryStorage();
  assert.equal(saveNotes(s, [note]), null);
  assert.deepEqual(loadNotes(s), { notes: [note], error: null });
});

for (const [label, raw] of [
  ['invalid JSON', '{nope'],
  ['wrong shape', '[1,2,3]'],
  ['null', 'null'],
  ['bad note', JSON.stringify({ notes: [{ id: 1, text: 'x' }] })],
]) {
  test(`unreadable data (${label}) is reported and backed up, not silently discarded`, () => {
    const s = memoryStorage({ [STORAGE_KEY]: raw });
    const result = loadNotes(s, 42);
    assert.deepEqual(result.notes, []);
    assert.match(result.error, /could not be read/);
    assert.equal(s.getItem(BACKUP_PREFIX + 42), raw);
    assert.equal(s.getItem(STORAGE_KEY), null);
  });
}

test('unreadable data is reported once: the next load is clean', () => {
  const s = memoryStorage({ [STORAGE_KEY]: '{nope' });
  assert.ok(loadNotes(s, 1).error);
  assert.deepEqual(loadNotes(s, 2), { notes: [], error: null });
});

test('failure to back up is still reported', () => {
  const s = memoryStorage({ [STORAGE_KEY]: '{nope' });
  s.setItem = () => { throw new Error('quota'); };
  const result = loadNotes(s);
  assert.deepEqual(result.notes, []);
  assert.match(result.error, /could not be backed up/);
});

test('inaccessible storage is reported, not thrown', () => {
  const s = { getItem() { throw new Error('denied'); } };
  const result = loadNotes(s);
  assert.deepEqual(result.notes, []);
  assert.ok(result.error);
});

test('save failure returns a message instead of throwing', () => {
  const s = memoryStorage();
  s.setItem = () => { throw new Error('quota'); };
  assert.equal(typeof saveNotes(s, [note]), 'string');
});
