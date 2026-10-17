import { loadNotes, saveNotes } from './src/storage.js';
import { addNote, deleteNote, findNote, newId, orderForDisplay, togglePin, updateText } from './src/state.js';
import { decideKey, editingAfterDelete, noteToEditOnClick, shouldSaveOnPress } from './src/editMode.js';
import { renderList, readEditor, locate } from './src/view.js';
import { showToast } from './src/toast.js';
import { confirmDialog, isModalOpen } from './src/modal.js';

const list = document.getElementById('notes');
const addButton = document.getElementById('add-note');

const loaded = loadNotes(localStorage);
let notes = loaded.notes;
let editingId = null;

function render() {
  renderList(list, orderForDisplay(notes), editingId);
}

function persist() {
  const error = saveNotes(localStorage, notes);
  if (error) showToast(error, { duration: 0, kind: 'error' });
  return error === null;
}

function saveEditing() {
  if (editingId === null) return;
  const text = readEditor(list, editingId);
  if (text !== null) notes = updateText(notes, editingId, text);
  editingId = null;
  render();
  if (persist()) showToast('Saved');
}

function cancelEditing() {
  editingId = null;
  render();
}

function startEditing(id) {
  editingId = id;
  render();
}

// Pressing anywhere outside the note being edited saves it.
document.addEventListener('pointerdown', (e) => {
  if (shouldSaveOnPress(editingId, locate(list, e.target))) saveEditing();
});

document.addEventListener('keydown', (e) => {
  if (e.defaultPrevented) return;
  if (decideKey(editingId, e.key, isModalOpen()) === 'cancel') {
    e.preventDefault();
    const id = editingId;
    cancelEditing();
    list.querySelector(`li.note[data-id="${CSS.escape(id)}"] .note-text`)?.focus();
  } else if (e.key === 'Enter' && editingId === null && e.target.classList?.contains('note-text')) {
    const id = noteToEditOnClick(editingId, locate(list, e.target));
    if (id) {
      e.preventDefault();
      startEditing(id);
    }
  }
});

// One delegated listener handles toolbar buttons and entering edit mode.
list.addEventListener('click', async (e) => {
  const where = locate(list, e.target);
  if (where.action === 'pin') {
    notes = togglePin(notes, where.noteId);
    render();
    persist();
  } else if (where.action === 'delete') {
    const note = findNote(notes, where.noteId);
    if (!note) return;
    const label = note.text.trim() ? `"${note.text.trim().slice(0, 40)}"` : 'this empty note';
    if (await confirmDialog(`Delete ${label}?`)) {
      notes = deleteNote(notes, note.id);
      editingId = editingAfterDelete(editingId, note.id);
      render();
      persist();
    }
  } else {
    const id = noteToEditOnClick(editingId, where);
    if (id) startEditing(id);
  }
});

addButton.addEventListener('click', () => {
  const id = newId();
  notes = addNote(notes, id);
  persist();
  startEditing(id);
});

render();
if (loaded.error) showToast(loaded.error, { duration: 0, kind: 'error' });
