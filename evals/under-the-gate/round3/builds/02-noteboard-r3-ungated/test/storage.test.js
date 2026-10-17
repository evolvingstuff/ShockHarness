import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, STORAGE_KEY, BACKUP_PREFIX } from '../src/storage.js';

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
  };
}

test('empty storage loads an empty board without error', () => {
  assert.deepEqual(loadNotes(memoryStorage()), { notes: [], error: null });
});

test('saved notes round-trip', () => {
  const s = memoryStorage();
  const notes = [{ id: 'a', text: 'hi', pinned: true }, { id: 'b', text: '', pinned: false }];
  assert.equal(saveNotes(s, notes), null);
  assert.deepEqual(loadNotes(s), { notes, error: null });
});

for (const [name, raw] of [
  ['invalid JSON', '{not json'],
  ['not an array', '{"a":1}'],
  ['bad entry', '[{"id":"a","text":5,"pinned":false}]'],
  ['duplicate ids', '[{"id":"a","text":"","pinned":false},{"id":"a","text":"","pinned":false}]'],
]) {
  test(`unreadable data (${name}) is reported, backed up, and reported only once`, () => {
    const s = memoryStorage({ [STORAGE_KEY]: raw });
    const first = loadNotes(s, () => 42);
    assert.deepEqual(first.notes, []);
    assert.match(first.error, /could not be read/);
    assert.equal(first.backupKey, BACKUP_PREFIX + '42');
    assert.equal(s.getItem(BACKUP_PREFIX + '42'), raw, 'original data is kept');
    assert.match(first.error, new RegExp(BACKUP_PREFIX + '42'));
    assert.deepEqual(loadNotes(s), { notes: [], error: null }, 'not reported again');
  });
}

test('if the backup cannot be written, the original data is left alone', () => {
  const raw = 'garbage';
  const s = memoryStorage({ [STORAGE_KEY]: raw });
  s.setItem = () => { throw new Error('quota'); };
  const r = loadNotes(s);
  assert.deepEqual(r.notes, []);
  assert.ok(r.error);
  assert.equal(s.getItem(STORAGE_KEY), raw);
});

test('storage that throws on read is reported', () => {
  const r = loadNotes({ getItem() { throw new Error('denied'); }, setItem() {} });
  assert.deepEqual(r.notes, []);
  assert.match(r.error, /denied/);
});

test('save failure is returned as a message', () => {
  const msg = saveNotes({ setItem() { throw new Error('quota'); } }, []);
  assert.match(msg, /quota/);
});
