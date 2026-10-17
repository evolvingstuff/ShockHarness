import { loadNotes, saveNotes } from './src/storage.js';
import { createStore } from './src/state.js';
import { onPressOutcome, onKeyOutcome, onNoteClickOutcome } from './src/editMode.js';
import { renderList } from './src/view.js';
import { showToast } from './src/toast.js';
import { confirmDialog } from './src/modal.js';

const list = document.getElementById('notes');
const loaded = loadNotes(localStorage);
const store = createStore(loaded.notes);
let editingId = null;

const persist = () => saveNotes(localStorage, store.notes);
const render = () => renderList(document, list, store.sorted(), editingId);
const noteIdOf = (el) => el?.closest?.('li.note')?.dataset.id ?? null;

function leaveEdit({ save }) {
  if (editingId == null) return;
  const id = editingId;
  if (save) {
    const ta = list.querySelector(`li[data-id="${CSS.escape(id)}"] textarea`);
    if (ta) {
      store.update(id, ta.value);
      persist();
      showToast(document, 'Saved');
    }
  }
  editingId = null;
  render();
}

// Outside press: decide from the target at event time, before any re-render.
document.addEventListener('mousedown', (e) => {
  if (onPressOutcome(editingId, noteIdOf(e.target)) === 'save') leaveEdit({ save: true });
});

document.addEventListener('keydown', (e) => {
  if (onKeyOutcome(editingId, e.key) === 'cancel') leaveEdit({ save: false });
});

// One delegated listener for toolbar buttons and note clicks.
list.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-action]');
  const id = noteIdOf(e.target);
  if (btn && id) {
    if (btn.dataset.action === 'pin') {
      store.togglePin(id);
      persist();
      render();
    } else if (btn.dataset.action === 'delete') {
      if (await confirmDialog(document, 'Delete this note?')) {
        if (editingId === id) editingId = null;
        store.remove(id);
        persist();
        render();
      }
    }
    return;
  }
  if (onNoteClickOutcome(editingId, id) === 'edit') {
    editingId = id;
    render();
    list.querySelector('textarea')?.focus();
  }
});

document.getElementById('add').addEventListener('click', () => {
  const n = store.add('');
  persist();
  editingId = n.id;
  render();
  list.querySelector('textarea')?.focus();
});

render();
if (loaded.error) showToast(document, loaded.error, { duration: 8000 });
