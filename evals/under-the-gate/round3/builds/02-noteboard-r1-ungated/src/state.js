// Pure note-list operations. Every function returns a new array.

let counter = 0;
export function newId(now = Date.now()) {
  counter += 1;
  return `n${now.toString(36)}${counter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function addNote(notes, text = '', now = Date.now(), id = newId(now)) {
  return [...notes, { id, text, pinned: false, updatedAt: now }];
}

export function updateNoteText(notes, id, text, now = Date.now()) {
  return notes.map((n) => (n.id === id && n.text !== text ? { ...n, text, updatedAt: now } : n));
}

export function togglePin(notes, id) {
  return notes.map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n));
}

export function deleteNote(notes, id) {
  return notes.filter((n) => n.id !== id);
}

export function findNote(notes, id) {
  return notes.find((n) => n.id === id) ?? null;
}

// Pinned first, then most recently updated first. Stable for ties.
export function sortedForDisplay(notes) {
  return notes
    .map((n, i) => [n, i])
    .sort(([a, ai], [b, bi]) =>
      a.pinned !== b.pinned ? (a.pinned ? -1 : 1) : b.updatedAt - a.updatedAt || ai - bi,
    )
    .map(([n]) => n);
}
