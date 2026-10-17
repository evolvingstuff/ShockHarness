import { test } from 'node:test';
import assert from 'node:assert/strict';
import { onPress, onNoteClick, onKey } from '../src/editMode.js';

test('press outside the edited note commits', () => {
  assert.equal(onPress({ editingId: 'a', pressedNoteId: null, inOverlay: false }), 'commit');
  assert.equal(onPress({ editingId: 'a', pressedNoteId: 'b', inOverlay: false }), 'commit');
});

test('press inside the edited note is ignored', () => {
  assert.equal(onPress({ editingId: 'a', pressedNoteId: 'a', inOverlay: false }), 'ignore');
});

test('press in a modal or toast never ends the edit', () => {
  assert.equal(onPress({ editingId: 'a', pressedNoteId: null, inOverlay: true }), 'ignore');
});

test('press when not editing is ignored', () => {
  assert.equal(onPress({ editingId: null, pressedNoteId: 'b', inOverlay: false }), 'ignore');
});

test('clicking a note enters edit mode unless on toolbar or already editing it', () => {
  assert.equal(onNoteClick({ editingId: null, clickedNoteId: 'a', onToolbar: false }), 'enter');
  assert.equal(onNoteClick({ editingId: 'b', clickedNoteId: 'a', onToolbar: false }), 'enter');
  assert.equal(onNoteClick({ editingId: 'a', clickedNoteId: 'a', onToolbar: false }), 'ignore');
  assert.equal(onNoteClick({ editingId: null, clickedNoteId: 'a', onToolbar: true }), 'ignore');
});

test('Escape cancels editing, but not while a modal is open', () => {
  assert.equal(onKey({ editingId: 'a', key: 'Escape', modalOpen: false }), 'cancel');
  assert.equal(onKey({ editingId: 'a', key: 'Escape', modalOpen: true }), 'ignore');
  assert.equal(onKey({ editingId: 'a', key: 'Enter', modalOpen: false }), 'ignore');
  assert.equal(onKey({ editingId: null, key: 'Escape', modalOpen: false }), 'ignore');
});

test('logic modules do not touch the DOM', async () => {
  const { readFile } = await import('node:fs/promises');
  for (const f of ['storage.js', 'state.js', 'editMode.js']) {
    const src = await readFile(new URL(`../src/${f}`, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /\b(document|window)\b/, f);
  }
});
