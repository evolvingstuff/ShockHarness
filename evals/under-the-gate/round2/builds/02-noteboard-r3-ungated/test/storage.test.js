import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, MemoryStorage, STORAGE_KEY, BACKUP_PREFIX } from '../src/storage.js';

const note = (id, extra = {}) => ({ id, text: `t${id}`, pinned: false, updatedAt: 1, ...extra });

test('empty storage loads empty without error', () => {
  assert.deepEqual(loadNotes(new MemoryStorage()), { notes: [], error: null });
});

test('save then load round-trips', () => {
  const s = new MemoryStorage();
  const notes = [note('a'), note('b', { pinned: true })];
  assert.equal(saveNotes(s, notes), null);
  assert.deepEqual(loadNotes(s), { notes, error: null });
});

for (const [label, raw] of [
  ['invalid JSON', '{not json'],
  ['wrong shape', JSON.stringify({ hello: 1 })],
  ['bare array', JSON.stringify([note('a')])],
  ['bad note', JSON.stringify({ version: 1, notes: [{ id: 'a', text: 5, pinned: false, updatedAt: 1 }] })],
  ['duplicate ids', JSON.stringify({ version: 1, notes: [note('a'), note('a')] })],
  ['null', 'null'],
]) {
  test(`unreadable data (${label}) is reported, backed up, and starts empty`, () => {
    const s = new MemoryStorage({ [STORAGE_KEY]: raw });
    const res = loadNotes(s, { now: () => 42 });
    assert.deepEqual(res.notes, []);
    assert.ok(res.error);
    assert.equal(res.error.backupKey, `${BACKUP_PREFIX}42`);
    assert.match(res.error.message, /could not be read/);
    assert.equal(s.getItem(`${BACKUP_PREFIX}42`), raw, 'original data preserved verbatim');
  });
}

test('unreadable data is reported once, not on every load', () => {
  const s = new MemoryStorage({ [STORAGE_KEY]: '{oops' });
  assert.ok(loadNotes(s).error);
  assert.deepEqual(loadNotes(s), { notes: [], error: null });
});

test('existing backups are not overwritten', () => {
  const s = new MemoryStorage({ [STORAGE_KEY]: 'second', [`${BACKUP_PREFIX}7`]: 'first' });
  const res = loadNotes(s, { now: () => 7 });
  assert.equal(s.getItem(`${BACKUP_PREFIX}7`), 'first');
  assert.equal(s.getItem(res.error.backupKey), 'second');
});

test('if the backup cannot be written, the original is left in place and still reported', () => {
  const s = new MemoryStorage({ [STORAGE_KEY]: '{oops' });
  s.setItem = () => { throw new Error('QuotaExceededError'); };
  const res = loadNotes(s);
  assert.deepEqual(res.notes, []);
  assert.ok(res.error);
  assert.equal(res.error.backupKey, null);
  assert.equal(s.getItem(STORAGE_KEY), '{oops');
});

test('storage that throws on read is reported', () => {
  const s = { getItem() { throw new Error('SecurityError'); } };
  const res = loadNotes(s);
  assert.deepEqual(res.notes, []);
  assert.match(res.error.message, /SecurityError/);
});

test('save failure is returned, not thrown', () => {
  const s = new MemoryStorage();
  s.setItem = () => { throw new Error('QuotaExceededError'); };
  assert.match(saveNotes(s, [note('a')]), /QuotaExceededError/);
});
