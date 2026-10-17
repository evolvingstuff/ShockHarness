import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, memoryStorage, STORAGE_KEY, BACKUP_KEY } from '../src/storage.js';

test('empty storage loads an empty board without error', () => {
  assert.deepEqual(loadNotes(memoryStorage()), { notes: [], error: null });
});

test('save then load round-trips notes', () => {
  const s = memoryStorage();
  const notes = [{ id: 'a', text: 'hello', pinned: true }, { id: 'b', text: '', pinned: false }];
  assert.equal(saveNotes(s, notes), null);
  assert.deepEqual(loadNotes(s), { notes, error: null });
});

for (const [name, raw] of [
  ['invalid JSON', '{not json'],
  ['wrong shape', JSON.stringify({ foo: 1 })],
  ['null', 'null'],
  ['bad note', JSON.stringify({ version: 1, notes: [{ id: 1, text: 'x', pinned: false }] })],
  ['unknown version', JSON.stringify({ version: 99, notes: [] })],
]) {
  test(`unreadable data (${name}) is reported and preserved`, () => {
    const s = memoryStorage({ [STORAGE_KEY]: raw });
    const { notes, error } = loadNotes(s);
    assert.deepEqual(notes, []);
    assert.match(error, /could not be read/);
    assert.equal(s.getItem(BACKUP_KEY), raw);
    // Reported once: the next load is clean.
    assert.deepEqual(loadNotes(s), { notes: [], error: null });
  });
}

test('if backup fails, original data is left in place and still reported', () => {
  const s = memoryStorage({ [STORAGE_KEY]: 'garbage' });
  s.setItem = () => { throw new Error('quota'); };
  const { notes, error } = loadNotes(s);
  assert.deepEqual(notes, []);
  assert.ok(error);
  assert.equal(s.getItem(STORAGE_KEY), 'garbage');
});

test('storage access failure is reported', () => {
  const s = { getItem() { throw new Error('denied'); } };
  const { notes, error } = loadNotes(s);
  assert.deepEqual(notes, []);
  assert.ok(error);
});

test('save failure returns a message', () => {
  const s = memoryStorage();
  s.setItem = () => { throw new Error('quota'); };
  assert.match(saveNotes(s, []), /could not be saved/);
});
