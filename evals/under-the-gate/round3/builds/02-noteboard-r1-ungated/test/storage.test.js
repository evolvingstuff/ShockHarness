import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, memoryStorage, STORAGE_KEY, BACKUP_KEY } from '../src/storage.js';

const note = { id: 'a', text: 'hi', pinned: false, updatedAt: 1 };

test('empty storage loads no notes and no error', () => {
  assert.deepEqual(loadNotes(memoryStorage()), { notes: [], error: null });
});

test('save then load round-trips', () => {
  const s = memoryStorage();
  assert.deepEqual(saveNotes(s, [note]), { ok: true, error: null });
  assert.deepEqual(loadNotes(s), { notes: [note], error: null });
});

for (const [name, raw] of [
  ['invalid JSON', '{not json'],
  ['wrong shape', '{"notes":5}'],
  ['bad note', JSON.stringify({ notes: [{ id: 1 }] })],
  ['null', 'null'],
]) {
  test(`unreadable data (${name}) is reported, backed up, and reported only once`, () => {
    const s = memoryStorage({ [STORAGE_KEY]: raw });
    const first = loadNotes(s);
    assert.deepEqual(first.notes, []);
    assert.match(first.error, /could not be read/);
    assert.equal(s.getItem(BACKUP_KEY), raw);
    assert.equal(s.getItem(STORAGE_KEY), null);
    assert.deepEqual(loadNotes(s), { notes: [], error: null });
  });
}

test('if backup fails, original data is left in place and still reported', () => {
  const s = memoryStorage({ [STORAGE_KEY]: 'garbage' });
  s.setItem = () => { throw new Error('quota'); };
  const r = loadNotes(s);
  assert.ok(r.error);
  assert.equal(s.getItem(STORAGE_KEY), 'garbage');
});

test('getItem throwing is reported', () => {
  const r = loadNotes({ getItem() { throw new Error('denied'); } });
  assert.deepEqual(r.notes, []);
  assert.ok(r.error);
});

test('save failure is reported, not thrown', () => {
  const r = saveNotes({ setItem() { throw new Error('quota'); } }, [note]);
  assert.equal(r.ok, false);
  assert.ok(r.error);
});
