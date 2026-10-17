import test from 'node:test';
import assert from 'node:assert/strict';
import { loadNotes, saveNotes, KEY } from '../src/storage.js';
import { createStore } from '../src/state.js';
import { onPressOutcome, onKeyOutcome, onNoteClickOutcome } from '../src/editMode.js';

const mem = (init = {}) => {
  const d = { ...init };
  return { d, getItem: (k) => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); } };
};

test('storage round trip', () => {
  const s = mem();
  const notes = [{ id: 'a', text: 'hi', pinned: true }];
  assert.ok(saveNotes(s, notes));
  assert.deepEqual(loadNotes(s), { notes, error: null });
});

test('missing data is not an error', () => {
  assert.deepEqual(loadNotes(mem()), { notes: [], error: null });
});

test('corrupt data is reported and preserved', () => {
  for (const bad of ['{nope', '{"a":1}', '[{"id":1}]']) {
    const s = mem({ [KEY]: bad });
    const r = loadNotes(s);
    assert.deepEqual(r.notes, []);
    assert.ok(r.error);
    assert.equal(s.d[KEY + '.corrupt'], bad);
  }
});

test('store operations', () => {
  const st = createStore();
  const a = st.add('a'); const b = st.add('b');
  assert.notEqual(a.id, b.id);
  st.togglePin(b.id);
  assert.deepEqual(st.sorted().map((n) => n.text), ['b', 'a']);
  st.update(a.id, 'A');
  st.remove(b.id);
  assert.deepEqual(st.notes.map((n) => n.text), ['A']);
});

test('edit mode decisions', () => {
  assert.equal(onPressOutcome(null, null), 'none');
  assert.equal(onPressOutcome('a', 'a'), 'none');
  assert.equal(onPressOutcome('a', 'b'), 'save');
  assert.equal(onPressOutcome('a', null), 'save');
  assert.equal(onKeyOutcome('a', 'Escape'), 'cancel');
  assert.equal(onKeyOutcome(null, 'Escape'), 'none');
  assert.equal(onKeyOutcome('a', 'x'), 'none');
  assert.equal(onNoteClickOutcome(null, 'a'), 'edit');
  assert.equal(onNoteClickOutcome('a', 'a'), 'none');
});
