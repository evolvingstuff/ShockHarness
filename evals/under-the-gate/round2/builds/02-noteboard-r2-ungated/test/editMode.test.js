import test from 'node:test';
import assert from 'node:assert/strict';
import * as edit from '../src/editMode.js';

const editing = (id) => ({ editingId: id });

test('clicking a note enters edit mode', () => {
  assert.deepEqual(edit.startEditing(edit.IDLE, 'a'), { state: editing('a'), action: null });
});

test('switching directly to another note saves the previous one', () => {
  assert.deepEqual(edit.startEditing(editing('a'), 'b'), {
    state: editing('b'),
    action: { type: 'save', id: 'a' },
  });
});

test('pressing outside the edited note saves and leaves edit mode', () => {
  assert.deepEqual(edit.press(editing('a'), { noteId: null }), {
    state: edit.IDLE,
    action: { type: 'save', id: 'a' },
  });
  assert.deepEqual(edit.press(editing('a'), { noteId: 'b' }).action, { type: 'save', id: 'a' });
});

test('pressing inside the edited note (including its toolbar) does nothing', () => {
  const s = editing('a');
  assert.deepEqual(edit.press(s, { noteId: 'a' }), { state: s, action: null });
});

test('pressing in a modal or toast does not save or leave edit mode', () => {
  const s = editing('a');
  assert.deepEqual(edit.press(s, { noteId: null, inOverlay: true }), { state: s, action: null });
});

test('pressing anywhere when not editing does nothing', () => {
  assert.deepEqual(edit.press(edit.IDLE, { noteId: 'a' }), { state: edit.IDLE, action: null });
});

test('Escape leaves edit mode without saving', () => {
  assert.deepEqual(edit.escape(editing('a')), { state: edit.IDLE, action: { type: 'cancel', id: 'a' } });
  assert.deepEqual(edit.escape(edit.IDLE), { state: edit.IDLE, action: null });
});

test('deleting the edited note leaves edit mode without saving', () => {
  assert.deepEqual(edit.noteRemoved(editing('a'), 'a'), {
    state: edit.IDLE,
    action: { type: 'cancel', id: 'a' },
  });
  const s = editing('a');
  assert.deepEqual(edit.noteRemoved(s, 'b'), { state: s, action: null });
});
