const SVG = {
  pin: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M14 3l7 7-3 1-3 3 1 5-2 2-4-6-6 5 5-6-6-4 2-2 5 1 3-3z" fill="currentColor"/></svg>',
  delete: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M6 7h12l-1 14H7zM9 3h6l1 2h4v2H4V5h4z" fill="currentColor"/></svg>',
};

function iconButton(doc, action, label) {
  const b = doc.createElement('button');
  b.type = 'button';
  b.dataset.action = action;
  b.setAttribute('aria-label', label);
  b.title = label;
  b.innerHTML = SVG[action];
  return b;
}

export function renderList(doc, listEl, notes, editingId) {
  listEl.replaceChildren();
  for (const n of notes) {
    const li = doc.createElement('li');
    li.className = 'note' + (n.pinned ? ' pinned' : '');
    li.dataset.id = n.id;
    let body;
    if (n.id === editingId) {
      body = doc.createElement('textarea');
      body.className = 'note-edit';
      body.value = n.text;
    } else {
      body = doc.createElement('div');
      body.className = 'note-text';
      body.textContent = n.text || '(empty note)';
    }
    const bar = doc.createElement('div');
    bar.className = 'toolbar';
    bar.append(iconButton(doc, 'pin', n.pinned ? 'Unpin' : 'Pin'), iconButton(doc, 'delete', 'Delete'));
    li.append(body, bar);
    listEl.appendChild(li);
  }
}
