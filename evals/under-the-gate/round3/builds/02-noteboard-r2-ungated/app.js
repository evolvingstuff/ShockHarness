import { loadNotes, saveNotes } from './src/storage.js';
import { addNote, updateText, togglePin, deleteNote, displayOrder, newId } from './src/state.js';
import { decidePress, decideListClick, decideKey } from './src/editmode.js';
import { ICONS } from './src/icons.js';
import { showToast } from './src/toast.js';
import { confirmDialog, isModalOpen, closeModal } from './src/modal.js';

const list = document.getElementById('notes');
const addButton = document.getElementById('add-note');

let { notes, error: loadError } = loadNotes(window.localStorage);
let editingId = null;
let draftId = null; // a newly added note that has never been saved
const elements = new Map(); // note id -> <li>, reused across renders

if (loadError) showToast(loadError, { timeout: 0, kind: 'error' });

function persist() {
  const err = saveNotes(window.localStorage, notes);
  if (err) showToast(err, { timeout: 0, kind: 'error' });
  return err === null;
}

function createItem(id) {
  const li = document.createElement('li');
  li.className = 'note';
  li.dataset.id = id;

  const body = document.createElement('div');
  body.className = 'note-body';

  const toolbar = document.createElement('div');
  toolbar.className = 'note-toolbar';
  for (const [action, label] of [['pin', 'Pin note'], ['delete', 'Delete note']]) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'icon-button';
    b.dataset.action = action;
    b.setAttribute('aria-label', label);
    b.title = label;
    b.innerHTML = ICONS[action];
    toolbar.appendChild(b);
  }
  li.append(body, toolbar);
  return li;
}

function fillBody(li, note) {
  const editing = note.id === editingId;
  const body = li.querySelector('.note-body');
  const existing = body.querySelector('textarea');
  li.classList.toggle('editing', editing);
  li.classList.toggle('pinned', note.pinned);
  li.querySelector('[data-action="pin"]').setAttribute('aria-pressed', String(note.pinned));

  if (editing) {
    if (existing) return;
    const ta = document.createElement('textarea');
    ta.value = note.text;
    ta.setAttribute('aria-label', 'Note text');
    body.replaceChildren(ta);
    body.removeAttribute('tabindex');
    body.removeAttribute('role');
  } else {
    body.textContent = note.text || 'Empty note';
    body.classList.toggle('placeholder', !note.text);
    body.tabIndex = 0;
    body.setAttribute('role', 'button');
  }
}

// Keyed render: existing <li>s (and their buttons) are kept, so a click whose
// pointerdown triggered a save still lands on the same button.
function render() {
  const ordered = displayOrder(notes);
  const live = new Set(ordered.map((n) => n.id));
  for (const [id, li] of elements) {
    if (!live.has(id)) {
      li.remove();
      elements.delete(id);
    }
  }
  ordered.forEach((note, i) => {
    let li = elements.get(note.id);
    if (!li) {
      li = createItem(note.id);
      elements.set(note.id, li);
    }
    fillBody(li, note);
    if (list.children[i] !== li) list.insertBefore(li, list.children[i] ?? null);
  });
  list.classList.toggle('empty', ordered.length === 0);
}

function enterEdit(id) {
  if (editingId !== null) saveEdit();
  editingId = id;
  render();
  const ta = elements.get(id)?.querySelector('textarea');
  if (ta) {
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
}

function saveEdit() {
  if (editingId === null) return;
  const ta = elements.get(editingId)?.querySelector('textarea');
  if (ta) notes = updateText(notes, editingId, ta.value);
  editingId = null;
  draftId = null;
  render();
  if (persist()) showToast('Saved');
}

function cancelEdit() {
  if (editingId === null) return;
  if (draftId === editingId) notes = deleteNote(notes, draftId);
  editingId = null;
  draftId = null;
  render();
}

function noteIdOf(target) {
  const li = target instanceof Element ? target.closest('li.note') : null;
  return li && list.contains(li) ? li.dataset.id : null;
}

document.addEventListener(
  'pointerdown',
  (e) => {
    const target = e.target instanceof Element ? e.target : null;
    const decision = decidePress({
      editingId,
      noteId: target ? noteIdOf(target) : null,
      inOverlay: Boolean(target?.closest('[data-overlay]')),
    });
    if (decision === 'save') saveEdit();
  },
  true,
);

document.addEventListener('keydown', (e) => {
  const decision = decideKey({ key: e.key, editingId, modalOpen: isModalOpen() });
  if (decision === 'close-modal') {
    e.preventDefault();
    closeModal(false);
  } else if (decision === 'cancel-edit') {
    e.preventDefault();
    cancelEdit();
  }
});

// One delegated listener for note clicks and toolbar buttons. `closest` is
// used because the click target is usually the <svg>/<path> inside a button.
list.addEventListener('click', async (e) => {
  const button = e.target.closest('button[data-action]');
  const decision = decideListClick({
    editingId,
    noteId: noteIdOf(e.target),
    action: button && list.contains(button) ? button.dataset.action : null,
  });

  if (decision.type === 'edit') {
    enterEdit(decision.id);
  } else if (decision.type === 'pin') {
    notes = togglePin(notes, decision.id);
    render();
    persist();
  } else if (decision.type === 'delete') {
    const ok = await confirmDialog('Delete this note? This cannot be undone.');
    if (!ok) return;
    if (editingId === decision.id) {
      editingId = null;
      draftId = null;
    }
    notes = deleteNote(notes, decision.id);
    render();
    persist();
  }
});

list.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList?.contains('note-body')) {
    const id = noteIdOf(e.target);
    if (id && id !== editingId) {
      e.preventDefault();
      enterEdit(id);
    }
  }
});

addButton.addEventListener('click', () => {
  const id = newId();
  notes = addNote(notes, { id });
  draftId = null;
  enterEdit(id);
  draftId = id;
});

render();
