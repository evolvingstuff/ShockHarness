// Renders the notes list. Note elements are kept per id and reused, so a
// re-render never replaces a button the user is in the middle of clicking,
// and the editor of the note being edited keeps its draft and focus.

import { icon } from './icons.js';

function toolbarButton(action, label) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `icon-button ${action}`;
  b.dataset.action = action;
  b.setAttribute('aria-label', label);
  b.title = label;
  b.append(icon(action));
  return b;
}

function createNoteElement(id) {
  const li = document.createElement('li');
  li.className = 'note';
  li.dataset.id = id;
  const body = document.createElement('div');
  body.className = 'note-body';
  const toolbar = document.createElement('div');
  toolbar.className = 'note-toolbar';
  toolbar.append(toolbarButton('pin', 'Pin'), toolbarButton('delete', 'Delete'));
  li.append(body, toolbar);
  return li;
}

function renderBody(li, note, editing) {
  const body = li.querySelector('.note-body');
  const current = body.firstElementChild;
  if (editing) {
    if (current && current.classList.contains('note-editor')) return;
    const editor = document.createElement('textarea');
    editor.className = 'note-editor';
    editor.value = note.text;
    editor.setAttribute('aria-label', 'Note text');
    body.replaceChildren(editor);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
  } else {
    if (current && current.classList.contains('note-text') && current.textContent === note.text) return;
    const text = document.createElement('p');
    text.className = 'note-text';
    text.tabIndex = 0;
    text.textContent = note.text;
    if (note.text === '') text.dataset.placeholder = 'Empty note';
    body.replaceChildren(text);
  }
}

/** Renders `notes` (already in display order) into `list`. */
export function renderList(list, notes, editingId) {
  const existing = new Map();
  for (const li of list.querySelectorAll(':scope > li.note')) existing.set(li.dataset.id, li);

  let prev = null;
  for (const note of notes) {
    let li = existing.get(note.id);
    if (li) existing.delete(note.id);
    else li = createNoteElement(note.id);

    li.classList.toggle('pinned', note.pinned);
    li.classList.toggle('editing', note.id === editingId);
    const pin = li.querySelector('[data-action="pin"]');
    pin.setAttribute('aria-pressed', String(note.pinned));
    pin.setAttribute('aria-label', note.pinned ? 'Unpin' : 'Pin');
    pin.title = note.pinned ? 'Unpin' : 'Pin';

    const expected = prev ? prev.nextElementSibling : list.firstElementChild;
    if (expected !== li) list.insertBefore(li, expected);
    renderBody(li, note, note.id === editingId);
    prev = li;
  }
  for (const li of existing.values()) li.remove();
  list.dataset.empty = String(notes.length === 0);
}

/** Current text of the editor for note `id`, or null if it is not being edited. */
export function readEditor(list, id) {
  const li = list.querySelector(`:scope > li.note[data-id="${CSS.escape(id)}"]`);
  const editor = li?.querySelector('.note-editor');
  return editor ? editor.value : null;
}

/** Describes where an event landed: { noteId, onToolbar, action }. */
export function locate(list, target) {
  const el = target instanceof Element ? target : target?.parentElement;
  const li = el?.closest('li.note');
  if (!li || li.parentElement !== list) return { noteId: null, onToolbar: false, action: null };
  const button = el.closest('[data-action]');
  return {
    noteId: li.dataset.id,
    onToolbar: Boolean(el.closest('.note-toolbar')),
    action: button && li.contains(button) ? button.dataset.action : null,
  };
}
