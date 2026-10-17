import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldSaveOnPress, noteToEditOnClick, decideKey, editingAfterDelete } from '../src/editMode.js';

const outside = { noteId: null, onToolbar: false };

test('press outside the edited note saves; inside does not', () => {
  assert.equal(shouldSaveOnPress('a', outside), true);
  assert.equal(shouldSaveOnPress('a', { noteId: 'b', onToolbar: false }), true);
  assert.equal(shouldSaveOnPress('a', { noteId: 'b', onToolbar: true }), true);
  assert.equal(shouldSaveOnPress('a', { noteId: 'a', onToolbar: false }), false);
  assert.equal(shouldSaveOnPress('a', { noteId: 'a', onToolbar: true }), false);
});

test('press does nothing when not editing', () => {
  assert.equal(shouldSaveOnPress(null, outside), false);
  assert.equal(shouldSaveOnPress(null, { noteId: 'a', onToolbar: false }), false);
});

test('clicking a note enters edit mode, but not via its toolbar', () => {
  assert.equal(noteToEditOnClick(null, { noteId: 'a', onToolbar: false }), 'a');
  assert.equal(noteToEditOnClick(null, { noteId: 'a', onToolbar: true }), null);
  assert.equal(noteToEditOnClick(null, outside), null);
  assert.equal(noteToEditOnClick('a', { noteId: 'a', onToolbar: false }), null);
  assert.equal(noteToEditOnClick(null, { noteId: 'b', onToolbar: false }), 'b');
});

test('Escape cancels editing unless a modal owns the keyboard', () => {
  assert.equal(decideKey('a', 'Escape'), 'cancel');
  assert.equal(decideKey('a', 'Escape', true), null);
  assert.equal(decideKey(null, 'Escape'), null);
  assert.equal(decideKey('a', 'Enter'), null);
});

test('deleting the edited note ends edit mode', () => {
  assert.equal(editingAfterDelete('a', 'a'), null);
  assert.equal(editingAfterDelete('a', 'b'), 'a');
  assert.equal(editingAfterDelete(null, 'b'), null);
});
