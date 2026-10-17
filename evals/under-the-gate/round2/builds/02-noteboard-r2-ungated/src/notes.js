// Pure operations on the notes array. Every function returns a new array.

export function newId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function addNote(notes, { id = newId(), text = '', now = Date.now() } = {}) {
  return [...notes, { id, text, pinned: false, updatedAt: now }];
}

export function updateNoteText(notes, id, text, now = Date.now()) {
  return notes.map((n) => (n.id === id ? { ...n, text, updatedAt: now } : n));
}

export function togglePin(notes, id) {
  return notes.map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n));
}

export function deleteNote(notes, id) {
  return notes.filter((n) => n.id !== id);
}

/** Display order: pinned notes first, otherwise original order (stable). */
export function sortForDisplay(notes) {
  return [...notes.filter((n) => n.pinned), ...notes.filter((n) => !n.pinned)];
}
