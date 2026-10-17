import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decidePress, decideKey, decideNoteClick } from '../src/editMode.js';

const press = (o) => decidePress({ editingId: 'a', targetNoteId: null, inOverlay: false, modalOpen: false, ...o });

test('press outside the edited note saves', () => {
  assert.equal(press({}), 'save');
  assert.equal(press({ targetNoteId: 'b' }), 'save');
});

test('press inside the edited note (including its toolbar) does nothing', () => {
  assert.equal(press({ targetNoteId: 'a' }), 'none');
});

test('press in the modal or a toast does not end editing', () => {
  assert.equal(press({ inOverlay: true }), 'none');
  assert.equal(press({ modalOpen: true }), 'none');
});

test('press with nothing being edited does nothing', () => {
  assert.equal(press({ editingId: null }), 'none');
});

test('Escape cancels edit unless the modal owns it', () => {
  assert.equal(decideKey({ key: 'Escape', editingId: 'a', modalOpen: false }), 'cancel');
  assert.equal(decideKey({ key: 'Escape', editingId: 'a', modalOpen: true }), 'none');
  assert.equal(decideKey({ key: 'Escape', editingId: null, modalOpen: false }), 'none');
  assert.equal(decideKey({ key: 'Enter', editingId: 'a', modalOpen: false }), 'none');
});

test('clicking a note starts editing it unless already editing it', () => {
  assert.equal(decideNoteClick({ editingId: null, noteId: 'a' }), 'edit');
  assert.equal(decideNoteClick({ editingId: 'b', noteId: 'a' }), 'edit');
  assert.equal(decideNoteClick({ editingId: 'a', noteId: 'a' }), 'none');
});
