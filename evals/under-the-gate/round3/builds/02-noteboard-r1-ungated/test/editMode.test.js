import { test } from 'node:test';
import assert from 'node:assert/strict';
import { onPress, onKey } from '../src/editMode.js';

test('clicking a note when not editing enters edit mode', () => {
  assert.equal(onPress({ editingId: null, pressedNoteId: 'a', inOverlay: false }), 'enter');
});

test('clicking a toolbar button does not enter edit mode', () => {
  assert.equal(onPress({ editingId: null, pressedNoteId: 'a', inOverlay: false, onToolbar: true }), 'none');
});

test('pressing inside the edited note does nothing', () => {
  assert.equal(onPress({ editingId: 'a', pressedNoteId: 'a', inOverlay: false }), 'none');
  assert.equal(onPress({ editingId: 'a', pressedNoteId: 'a', inOverlay: false, onToolbar: true }), 'none');
});

test('pressing outside the edited note commits', () => {
  assert.equal(onPress({ editingId: 'a', pressedNoteId: null, inOverlay: false }), 'commit');
  assert.equal(onPress({ editingId: 'a', pressedNoteId: 'b', inOverlay: false }), 'commit');
  assert.equal(onPress({ editingId: 'a', pressedNoteId: 'b', inOverlay: false, onToolbar: true }), 'commit');
});

test('presses in the modal or toast never change edit mode', () => {
  assert.equal(onPress({ editingId: 'a', pressedNoteId: null, inOverlay: true }), 'none');
  assert.equal(onPress({ editingId: null, pressedNoteId: null, inOverlay: true }), 'none');
});

test('Escape closes the modal first, else cancels editing', () => {
  assert.equal(onKey({ key: 'Escape', editingId: 'a', modalOpen: true }), 'close-modal');
  assert.equal(onKey({ key: 'Escape', editingId: 'a', modalOpen: false }), 'cancel');
  assert.equal(onKey({ key: 'Escape', editingId: null, modalOpen: false }), 'none');
  assert.equal(onKey({ key: 'Enter', editingId: 'a', modalOpen: false }), 'none');
});
