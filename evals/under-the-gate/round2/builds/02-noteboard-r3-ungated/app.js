import { loadNotes, saveNotes, MemoryStorage } from './src/storage.js';
import { addNote, updateNote, deleteNote, togglePin, findNote, sortForDisplay } from './src/state.js';
import { decidePress, decideKey, decideNoteClick } from './src/editMode.js';
import { renderNote } from './src/ui/render.js';
import { showToast } from './src/ui/toast.js';
import { confirmDialog, isModalOpen } from './src/ui/modal.js';

const list = document.getElementById('notes');
const addButton = document.getElementById('add-note');
const emptyHint = document.getElementById('empty-hint');

let storage;
try {
  storage = window.localStorage;
} catch {
  storage = null;
}
if (!storage) {
  storage = new MemoryStorage();
  showToast('localStorage is unavailable; notes will not be kept after this page closes.', { duration: 0, kind: 'error' });
}

const loaded = loadNotes(storage);
let notes = loaded.notes;
let editingId = null;
if (loaded.error) showToast(loaded.error.message, { duration: 0, kind: 'error' });

function persist() {
  const error = saveNotes(storage, notes);
  if (error) showToast(error, { duration: 0, kind: 'error', tag: 'save-error' });
  return !error;
}

function noteElement(id) {
  return [...list.children].find((li) => li.dataset.noteId === id) ?? null;
}

function render() {
  list.replaceChildren(...sortForDisplay(notes).map((n) => renderNote(n, { editing: n.id === editingId })));
  emptyHint.hidden = notes.length > 0;
}

// Swap a single note in place. Used when leaving edit mode from a press, so
// the element the user is pressing on (e.g. another note's button) survives
// and still receives its click.
function rerenderNote(id) {
  const old = noteElement(id);
  const note = findNote(notes, id);
  if (!old || !note) return render();
  old.replaceWith(renderNote(note, { editing: id === editingId }));
}

function commitEdit() {
  if (editingId == null) return;
  const id = editingId;
  const editor = noteElement(id)?.querySelector('.note-editor');
  editingId = null;
  if (editor && findNote(notes, id)) {
    notes = updateNote(notes, id, editor.value);
    if (persist()) showToast('Saved', { tag: 'saved' });
  }
  rerenderNote(id);
}

function cancelEdit() {
  if (editingId == null) return;
  const id = editingId;
  editingId = null;
  rerenderNote(id);
}

function startEdit(id) {
  if (editingId != null && editingId !== id) commitEdit();
  editingId = id;
  render();
  const editor = noteElement(id)?.querySelector('.note-editor');
  if (editor) {
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
  }
}

document.addEventListener('pointerdown', (e) => {
  const target = e.target instanceof Element ? e.target : e.target?.parentElement;
  const decision = decidePress({
    editingId,
    targetNoteId: target?.closest('[data-note-id]')?.dataset.noteId ?? null,
    inOverlay: Boolean(target?.closest('[data-overlay]')),
    modalOpen: isModalOpen(),
  });
  if (decision === 'save') commitEdit();
});

document.addEventListener('keydown', (e) => {
  if (decideKey({ key: e.key, editingId, modalOpen: isModalOpen() }) === 'cancel') {
    e.preventDefault();
    const id = editingId;
    cancelEdit();
    noteElement(id)?.querySelector('.note-text')?.focus();
  }
});

// One delegated listener for everything inside the list.
list.addEventListener('click', async (e) => {
  const target = e.target instanceof Element ? e.target : e.target?.parentElement;
  const li = target?.closest('[data-note-id]');
  if (!li || !list.contains(li)) return;
  const id = li.dataset.noteId;
  const button = target.closest('button[data-action]');

  if (button) {
    if (button.dataset.action === 'pin') {
      if (editingId === id) commitEdit();
      notes = togglePin(notes, id);
      persist();
      render();
    } else if (button.dataset.action === 'delete') {
      const ok = await confirmDialog('Delete this note? This cannot be undone.');
      if (!ok || !findNote(notes, id)) return;
      if (editingId === id) editingId = null;
      notes = deleteNote(notes, id);
      persist();
      render();
    }
    return;
  }

  if (decideNoteClick({ editingId, noteId: id }) === 'edit') startEdit(id);
});

list.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList?.contains('note-text')) {
    e.preventDefault();
    const id = e.target.closest('[data-note-id]').dataset.noteId;
    if (decideNoteClick({ editingId, noteId: id }) === 'edit') startEdit(id);
  }
});

addButton.addEventListener('click', () => {
  notes = addNote(notes);
  persist();
  startEdit(notes[notes.length - 1].id);
});

render();
