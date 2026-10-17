import { loadNotes, saveNotes } from './src/storage.js';
import { addNote, updateNoteText, togglePin, deleteNote, findNote, sortedForDisplay } from './src/state.js';
import { onPress, onKey } from './src/editMode.js';
import { renderBoard } from './src/ui/board.js';
import { showToast } from './src/ui/toast.js';
import { confirmDialog, isModalOpen, closeModal } from './src/ui/modal.js';

const list = document.getElementById('notes');
const addButton = document.getElementById('add-note');

const loaded = loadNotes(localStorage);
let notes = loaded.notes;
let editingId = null;
let draft = '';

function render() {
  renderBoard(list, sortedForDisplay(notes), editingId);
}

function persist() {
  const result = saveNotes(localStorage, notes);
  if (!result.ok) showToast(result.error, { duration: 0, kind: 'error' });
  return result.ok;
}

function enterEdit(id) {
  const note = findNote(notes, id);
  if (!note) return;
  editingId = id;
  draft = note.text;
  render();
}

function commitEdit() {
  if (editingId === null) return;
  notes = updateNoteText(notes, editingId, draft);
  editingId = null;
  render();
  if (persist()) showToast('Saved');
}

function cancelEdit() {
  if (editingId === null) return;
  editingId = null;
  render();
}

// Edit-mode decisions for every press on the page. Capture phase so it runs
// before other handlers; it never stops propagation, so buttons elsewhere
// (toolbar, modal, toast) keep working.
document.addEventListener(
  'click',
  (e) => {
    const target = e.target instanceof Element ? e.target : null;
    const noteEl = target?.closest('.note');
    const action = onPress({
      editingId,
      pressedNoteId: noteEl && list.contains(noteEl) ? noteEl.dataset.id : null,
      inOverlay: Boolean(target?.closest('[data-overlay]')),
      onToolbar: Boolean(target?.closest('.note-toolbar')),
    });
    if (action === 'commit') commitEdit();
    else if (action === 'enter') enterEdit(noteEl.dataset.id);
  },
  true,
);

document.addEventListener('keydown', (e) => {
  const action = onKey({ key: e.key, editingId, modalOpen: isModalOpen() });
  if (action === 'close-modal') {
    e.preventDefault();
    closeModal();
  } else if (action === 'cancel') {
    e.preventDefault();
    cancelEdit();
  }
});

list.addEventListener('input', (e) => {
  if (e.target.classList.contains('note-editor')) draft = e.target.value;
});

// Keyboard access to edit mode for the focusable note text.
list.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList?.contains('note-text')) {
    e.preventDefault();
    const id = e.target.closest('.note').dataset.id;
    commitEdit();
    enterEdit(id);
  }
});

// One delegated listener for all toolbar buttons.
list.addEventListener('click', async (e) => {
  const button = e.target instanceof Element ? e.target.closest('button[data-action]') : null;
  const noteEl = button?.closest('.note');
  if (!button || !noteEl) return;
  const id = noteEl.dataset.id;

  if (button.dataset.action === 'pin') {
    notes = togglePin(notes, id);
    persist();
    render();
  } else if (button.dataset.action === 'delete') {
    const confirmed = await confirmDialog({
      message: 'Delete this note? This cannot be undone.',
      confirmLabel: 'Delete',
    });
    if (!confirmed || !findNote(notes, id)) return;
    notes = deleteNote(notes, id);
    if (editingId === id) editingId = null;
    persist();
    render();
  }
});

addButton.addEventListener('click', () => {
  // The capture handler has already committed any open edit.
  notes = addNote(notes, '');
  enterEdit(notes[notes.length - 1].id);
});

render();
if (loaded.error) showToast(loaded.error, { duration: 0, kind: 'error' });
