import { iconButton } from './icons.js';

// Rendering of the notes list. A note is
//   <li class="note" data-id>
//     <div class="note-body">…text or textarea…</div>
//     <div class="note-toolbar">pin, delete buttons</div>
//   </li>
// Entering/leaving edit mode only swaps the contents of .note-body, so the
// toolbar buttons stay in the document while a press elsewhere saves an edit.

export function noteElement(list, id) {
  return list.querySelector(`li.note[data-id="${CSS.escape(id)}"]`);
}

function fillBody(body, note, draft) {
  body.replaceChildren();
  if (draft !== undefined) {
    const textarea = document.createElement('textarea');
    textarea.className = 'note-editor';
    textarea.value = draft;
    textarea.setAttribute('aria-label', 'Note text');
    body.append(textarea);
  } else {
    const text = document.createElement('div');
    text.className = 'note-text';
    if (note.text.trim() === '') {
      text.classList.add('empty');
      text.textContent = 'Empty note — click to edit';
    } else {
      text.textContent = note.text;
    }
    body.append(text);
  }
}

function createNote(note, draft) {
  const li = document.createElement('li');
  li.className = 'note';
  li.dataset.id = note.id;
  li.classList.toggle('pinned', note.pinned);
  li.classList.toggle('editing', draft !== undefined);

  const body = document.createElement('div');
  body.className = 'note-body';
  fillBody(body, note, draft);

  const toolbar = document.createElement('div');
  toolbar.className = 'note-toolbar';
  const pin = iconButton('pin', note.pinned ? 'Unpin note' : 'Pin note', {
    'data-action': 'pin',
    'aria-pressed': String(note.pinned),
  });
  const del = iconButton('delete', 'Delete note', { 'data-action': 'delete' });
  toolbar.append(pin, del);

  li.append(body, toolbar);
  return li;
}

/** Re-render the whole list. `editing` is { id, draft } or null. */
export function renderList(list, notes, editing) {
  list.replaceChildren(
    ...notes.map((n) => createNote(n, editing && editing.id === n.id ? editing.draft : undefined)),
  );
  if (editing) focusEditor(list, editing.id);
}

/** Switch one note between view and edit mode in place. */
export function setNoteEditing(list, note, draft) {
  const li = noteElement(list, note.id);
  if (!li) return;
  li.classList.toggle('editing', draft !== undefined);
  fillBody(li.querySelector('.note-body'), note, draft);
  if (draft !== undefined) focusEditor(list, note.id);
}

export function readDraft(list, id) {
  const li = noteElement(list, id);
  const textarea = li && li.querySelector('textarea.note-editor');
  return textarea ? textarea.value : null;
}

function focusEditor(list, id) {
  const li = noteElement(list, id);
  const textarea = li && li.querySelector('textarea.note-editor');
  if (textarea) {
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }
}
