import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decidePress, decideListClick, decideKey } from '../src/editmode.js';

test('press does nothing when not editing', () => {
  assert.equal(decidePress({ editingId: null, noteId: 'a', inOverlay: false }), 'none');
});

test('press inside the edited note keeps editing', () => {
  assert.equal(decidePress({ editingId: 'a', noteId: 'a', inOverlay: false }), 'none');
});

test('press outside the edited note saves', () => {
  assert.equal(decidePress({ editingId: 'a', noteId: null, inOverlay: false }), 'save');
  assert.equal(decidePress({ editingId: 'a', noteId: 'b', inOverlay: false }), 'save');
});

test('press in modal or toast does not save, so its buttons work while editing', () => {
  assert.equal(decidePress({ editingId: 'a', noteId: null, inOverlay: true }), 'none');
});

test('list clicks', () => {
  assert.deepEqual(decideListClick({ editingId: null, noteId: null, action: null }), { type: 'none' });
  assert.deepEqual(decideListClick({ editingId: null, noteId: 'a', action: null }), { type: 'edit', id: 'a' });
  assert.deepEqual(decideListClick({ editingId: 'a', noteId: 'a', action: null }), { type: 'none' });
  assert.deepEqual(decideListClick({ editingId: 'a', noteId: 'b', action: null }), { type: 'edit', id: 'b' });
  assert.deepEqual(decideListClick({ editingId: null, noteId: 'a', action: 'pin' }), { type: 'pin', id: 'a' });
  assert.deepEqual(decideListClick({ editingId: 'a', noteId: 'a', action: 'delete' }), { type: 'delete', id: 'a' });
});

test('Escape closes the modal first, then cancels the edit', () => {
  assert.equal(decideKey({ key: 'Escape', editingId: 'a', modalOpen: true }), 'close-modal');
  assert.equal(decideKey({ key: 'Escape', editingId: 'a', modalOpen: false }), 'cancel-edit');
  assert.equal(decideKey({ key: 'Escape', editingId: null, modalOpen: false }), 'none');
  assert.equal(decideKey({ key: 'Enter', editingId: 'a', modalOpen: false }), 'none');
});
