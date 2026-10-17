// Pure note-list operations. Every function returns a new array.

let counter = 0;
export function newId(now = Date.now) {
  counter += 1;
  return `n${now().toString(36)}${counter.toString(36)}`;
}

export function addNote(notes, id, text = '') {
  return [...notes, { id, text, pinned: false }];
}

export function updateText(notes, id, text) {
  return notes.map((n) => (n.id === id ? { ...n, text } : n));
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

/** Display order: pinned notes first, otherwise insertion order (stable). */
export function orderForDisplay(notes) {
  return [...notes.filter((n) => n.pinned), ...notes.filter((n) => !n.pinned)];
}
