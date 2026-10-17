// Pure note-list operations. Every function returns a new array.

let counter = 0;
export function newId() {
  counter += 1;
  return `n${Date.now().toString(36)}${counter.toString(36)}`;
}

export function addNote(notes, text = '', id = newId()) {
  return [{ id, text, pinned: false }, ...notes];
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

/** Pinned notes first; relative order otherwise preserved. */
export function sortedForDisplay(notes) {
  return [...notes.filter((n) => n.pinned), ...notes.filter((n) => !n.pinned)];
}
