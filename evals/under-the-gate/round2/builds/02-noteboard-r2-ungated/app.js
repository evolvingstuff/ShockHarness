import { loadNotes, saveNotes } from './src/storage.js';
import { addNote, deleteNote, sortForDisplay, togglePin, updateNoteText } from './src/notes.js';
import * as edit from './src/editMode.js';
import { noteElement, readDraft, renderList, setNoteEditing } from './src/ui/board.js';
import { confirmDialog } from './src/ui/modal.js';
import { showToast } from './src/ui/toast.js';

const list = document.getElementById('notes');
const addButton = document.getElementById('add-note');
const storage = globalThis.localStorage;

const loaded = loadNotes(storage);
let notes = loaded.notes;
let editState = edit.IDLE;

if (loaded.error) showToast(loaded.error, { kind: 'error', duration: 0 });

function persist() {
  const error = saveNotes(storage, notes);
  if (error) showToast(error, { kind: 'error', duration: 0 });
  return error === null;
}

function findNote(id) {
  return notes.find((n) => n.id === id);
}

function render() {
  const editing =
    editState.editingId === null
      ? null
      : { id: editState.editingId, draft: readDraft(list, editState.editingId) ?? findNote(editState.editingId)?.text ?? '' };
  renderList(list, sortForDisplay(notes), editing);
}

// Carry out an action returned by the edit-mode module.
function perform(action) {
  if (!action) return;
  const note = findNote(action.id);
  if (!note) return;
  if (action.type === 'save') {
    const draft = readDraft(list, action.id);
    if (draft !== null) notes = updateNoteText(notes, action.id, draft);
    const saved = persist();
    setNoteEditing(list, findNote(action.id), undefined);
    if (saved) showToast('Saved');
  } else if (action.type === 'cancel') {
    setNoteEditing(list, note, undefined);
  }
}

function startEditing(id) {
  const { state, action } = edit.startEditing(editState, id);
  if (state === editState) return;
  perform(action);
  editState = state;
  setNoteEditing(list, findNote(id), findNote(id).text);
}

// Pressing anywhere outside the note being edited saves it. Presses inside a
// modal or toast are ignored so their buttons work while a note is edited.
document.addEventListener(
  'pointerdown',
  (e) => {
    const target = e.target instanceof Element ? e.target : null;
    const li = target && target.closest('li.note');
    const { state, action } = edit.press(editState, {
      noteId: li && list.contains(li) ? li.dataset.id : null,
      inOverlay: Boolean(target && target.closest('[data-overlay]')),
    });
    editState = state;
    perform(action);
  },
  true,
);

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (e.target instanceof Element && e.target.closest('[data-overlay]')) return;
  const { state, action } = edit.escape(editState);
  editState = state;
  perform(action);
});

// One delegated listener for everything inside the list.
list.addEventListener('click', async (e) => {
  const li = e.target instanceof Element ? e.target.closest('li.note') : null;
  if (!li || !list.contains(li)) return;
  const id = li.dataset.id;
  const button = e.target.closest('button[data-action]');

  if (!button) {
    startEditing(id);
    return;
  }

  if (button.dataset.action === 'pin') {
    notes = togglePin(notes, id);
    persist();
    render();
  } else if (button.dataset.action === 'delete') {
    const ok = await confirmDialog({
      title: 'Delete note?',
      message: 'This note will be permanently deleted.',
      confirmLabel: 'Delete',
    });
    if (!ok || !findNote(id)) return;
    const { state } = edit.noteRemoved(editState, id);
    editState = state;
    notes = deleteNote(notes, id);
    persist();
    render();
  }
});

addButton.addEventListener('click', () => {
  notes = addNote(notes);
  persist();
  const id = notes[notes.length - 1].id;
  render();
  startEditing(id);
  noteElement(list, id)?.scrollIntoView({ block: 'nearest' });
});

render();
