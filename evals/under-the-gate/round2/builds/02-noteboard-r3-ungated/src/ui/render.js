// Builds note elements. Pure DOM construction; no event handling here.

const SVG_NS = 'http://www.w3.org/2000/svg';

const ICONS = {
  pin: 'M16 3l5 5-3 1-4 4 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 4-4z',
  delete: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
};

function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', ICONS[name]);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', 'currentColor');
  path.setAttribute('stroke-width', '2');
  path.setAttribute('stroke-linejoin', 'round');
  path.setAttribute('stroke-linecap', 'round');
  svg.append(path);
  return svg;
}

function toolButton(action, label, pressed) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `tool tool-${action}`;
  b.dataset.action = action;
  b.setAttribute('aria-label', label);
  b.title = label;
  if (pressed !== undefined) b.setAttribute('aria-pressed', String(pressed));
  b.append(icon(action));
  return b;
}

export function renderNote(note, { editing = false, draft = note.text } = {}) {
  const li = document.createElement('li');
  li.className = 'note';
  li.dataset.noteId = note.id;
  li.classList.toggle('pinned', note.pinned);
  li.classList.toggle('editing', editing);

  let body;
  if (editing) {
    body = document.createElement('textarea');
    body.className = 'note-editor';
    body.value = draft;
    body.setAttribute('aria-label', 'Note text');
  } else {
    body = document.createElement('div');
    body.className = 'note-text';
    body.tabIndex = 0;
    body.setAttribute('role', 'button');
    body.setAttribute('aria-label', 'Edit note');
    body.textContent = note.text || 'Empty note';
    body.classList.toggle('empty', !note.text);
  }

  const toolbar = document.createElement('div');
  toolbar.className = 'note-toolbar';
  toolbar.append(
    toolButton('pin', note.pinned ? 'Unpin' : 'Pin', note.pinned),
    toolButton('delete', 'Delete'),
  );

  li.append(body, toolbar);
  return li;
}
