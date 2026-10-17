import { PIN, TRASH } from './icons.js';

// Renders the notes into `list`. The note with `editingId` gets a textarea.
export function renderBoard(list, notes, editingId) {
  const frag = document.createDocumentFragment();
  for (const note of notes) {
    const li = document.createElement('li');
    li.className = 'note' + (note.pinned ? ' pinned' : '') + (note.id === editingId ? ' editing' : '');
    li.dataset.id = note.id;

    const toolbar = document.createElement('div');
    toolbar.className = 'note-toolbar';
    toolbar.append(
      iconButton('pin', PIN, note.pinned ? 'Unpin note' : 'Pin note', note.pinned),
      iconButton('delete', TRASH, 'Delete note'),
    );

    let body;
    if (note.id === editingId) {
      body = document.createElement('textarea');
      body.className = 'note-editor';
      body.value = note.text;
      body.setAttribute('aria-label', 'Note text');
    } else {
      body = document.createElement('div');
      body.className = 'note-text';
      body.textContent = note.text || 'Empty note';
      if (!note.text) body.classList.add('placeholder');
      body.tabIndex = 0;
      body.setAttribute('role', 'button');
      body.setAttribute('aria-label', 'Edit note');
    }
    li.append(body, toolbar);
    frag.append(li);
  }
  list.replaceChildren(frag);
  if (notes.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'empty';
    empty.textContent = 'No notes yet.';
    list.append(empty);
  }
  const editor = list.querySelector('.note-editor');
  if (editor) {
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
  }
}

function iconButton(action, icon, label, pressed) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'icon-btn';
  b.dataset.action = action;
  b.setAttribute('aria-label', label);
  b.title = label;
  if (pressed !== undefined) b.setAttribute('aria-pressed', String(pressed));
  b.innerHTML = icon;
  return b;
}
