// Pure note-list operations. Every function returns a new array.

let counter = 0;
export function newId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  counter += 1;
  return `n-${Date.now().toString(36)}-${counter}`;
}

export function addNote(notes, { id = newId(), text = '', now = Date.now() } = {}) {
  return [...notes, { id, text, pinned: false, updatedAt: now }];
}

export function updateNote(notes, id, text, now = Date.now()) {
  return notes.map((n) => (n.id === id && n.text !== text ? { ...n, text, updatedAt: now } : n));
}

export function deleteNote(notes, id) {
  return notes.filter((n) => n.id !== id);
}

export function togglePin(notes, id) {
  return notes.map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n));
}

export function findNote(notes, id) {
  return notes.find((n) => n.id === id) ?? null;
}

/** Display order: pinned first, otherwise insertion order (stable). */
export function sortForDisplay(notes) {
  return notes
    .map((n, i) => [n, i])
    .sort((a, b) => Number(b[0].pinned) - Number(a[0].pinned) || a[1] - b[1])
    .map(([n]) => n);
}
