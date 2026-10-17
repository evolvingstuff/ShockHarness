import { PIN, TRASH } from './icons.js';
import { loadNotes, saveNotes } from './storage.js';
import * as S from './state.js';
import { onPress, onNoteClick, onKey } from './editMode.js';
import { confirmDialog, isModalOpen } from './modal.js';
import { showToast } from './toast.js';

export function createBoard({ list, addButton, storage }) {
  const loaded = loadNotes(storage);
  let notes = loaded.notes;
  let editingId = null;
  if (loaded.error) showToast(loaded.error, { kind: 'error', duration: 0 });

  function persist({ announce }) {
    const err = saveNotes(storage, notes);
    if (err) showToast(err, { kind: 'error', duration: 0 });
    else if (announce) showToast('Saved');
  }

  // --- rendering (keyed, so untouched notes keep their DOM nodes and an
  // in-progress click on them survives a re-render) ---

  function signature(n) {
    return JSON.stringify([n.text, n.pinned, n.id === editingId]);
  }

  function buildNote(n) {
    const li = document.createElement('li');
    li.className = 'note';
    li.dataset.id = n.id;
    li.dataset.sig = signature(n);
    if (n.pinned) li.classList.add('pinned');

    const editing = n.id === editingId;
    if (editing) {
      li.classList.add('editing');
      const ta = document.createElement('textarea');
      ta.className = 'note-editor';
      ta.value = n.text;
      ta.setAttribute('aria-label', 'Note text');
      li.appendChild(ta);
    } else {
      const body = document.createElement('div');
      body.className = 'note-body';
      body.textContent = n.text || 'Empty note';
      if (!n.text) body.classList.add('placeholder');
      body.tabIndex = 0;
      li.appendChild(body);
    }

    const tools = document.createElement('div');
    tools.className = 'note-toolbar';
    tools.append(
      iconButton('pin', n.pinned ? 'Unpin' : 'Pin', PIN, n.pinned),
      iconButton('delete', 'Delete', TRASH),
    );
    li.appendChild(tools);
    return li;
  }

  function iconButton(action, label, icon, pressed) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'icon-button';
    b.dataset.action = action;
    b.setAttribute('aria-label', label);
    b.title = label;
    if (pressed !== undefined) b.setAttribute('aria-pressed', String(pressed));
    b.innerHTML = icon;
    return b;
  }

  function render() {
    const existing = new Map();
    for (const el of list.children) existing.set(el.dataset.id, el);

    const ordered = S.sortedForDisplay(notes);
    ordered.forEach((n, i) => {
      let el = existing.get(n.id);
      if (el && el.dataset.sig !== signature(n)) {
        const fresh = buildNote(n);
        el.replaceWith(fresh);
        el = fresh;
      } else if (!el) {
        el = buildNote(n);
      }
      existing.delete(n.id);
      if (list.children[i] !== el) list.insertBefore(el, list.children[i] ?? null);
    });
    for (const el of existing.values()) el.remove();

    list.classList.toggle('empty', notes.length === 0);
  }

  function editorFor(id) {
    return list.querySelector(`li[data-id="${CSS.escape(id)}"] textarea`);
  }

  // --- edit mode ---

  function enterEdit(id) {
    editingId = id;
    render();
    const ta = editorFor(id);
    if (ta) {
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
    }
  }

  function commitEdit() {
    if (editingId === null) return;
    const ta = editorFor(editingId);
    const id = editingId;
    editingId = null;
    const note = S.findNote(notes, id);
    const changed = ta && note && ta.value !== note.text;
    if (changed) notes = S.updateText(notes, id, ta.value);
    render();
    if (changed) persist({ announce: true });
  }

  function cancelEdit() {
    if (editingId === null) return;
    const id = editingId;
    editingId = null;
    render();
    list.querySelector(`li[data-id="${CSS.escape(id)}"] .note-body`)?.focus();
  }

  // --- events ---

  // Capture phase so the decision is made before anything else reacts.
  document.addEventListener(
    'pointerdown',
    (e) => {
      const target = e.target instanceof Element ? e.target : null;
      const li = target?.closest('li.note');
      const decision = onPress({
        editingId,
        pressedNoteId: li && list.contains(li) ? li.dataset.id : null,
        inOverlay: Boolean(target?.closest('[data-overlay]')),
      });
      if (decision === 'commit') commitEdit();
    },
    true,
  );

  document.addEventListener('keydown', (e) => {
    if (onKey({ editingId, key: e.key, modalOpen: isModalOpen() }) === 'cancel') {
      e.preventDefault();
      cancelEdit();
    }
  });

  // One delegated listener for the whole list: toolbar actions and entering edit mode.
  list.addEventListener('click', (e) => {
    const li = e.target.closest('li.note');
    if (!li || !list.contains(li)) return;
    const id = li.dataset.id;
    const button = e.target.closest('button[data-action]');

    if (button) {
      if (button.dataset.action === 'pin') {
        notes = S.togglePin(notes, id);
        render();
        persist({ announce: false });
        if (id === editingId) editorFor(id)?.focus();
      } else if (button.dataset.action === 'delete') {
        requestDelete(id);
      }
      return;
    }

    if (onNoteClick({ editingId, clickedNoteId: id, onToolbar: Boolean(e.target.closest('.note-toolbar')) }) === 'enter') {
      enterEdit(id);
    }
  });

  list.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.classList?.contains('note-body')) {
      e.preventDefault();
      const id = e.target.closest('li.note').dataset.id;
      if (editingId !== null && editingId !== id) commitEdit();
      enterEdit(id);
    }
  });

  async function requestDelete(id) {
    const ok = await confirmDialog({ message: 'Delete this note?' });
    if (!S.findNote(notes, id)) return;
    if (ok) {
      if (editingId === id) editingId = null;
      notes = S.deleteNote(notes, id);
      render();
      persist({ announce: false });
    } else if (editingId === id) {
      editorFor(id)?.focus();
    }
  }

  addButton?.addEventListener('click', () => {
    notes = S.addNote(notes, '');
    persist({ announce: false });
    enterEdit(notes[0].id);
  });

  render();
  return { getNotes: () => notes, getEditingId: () => editingId };
}
