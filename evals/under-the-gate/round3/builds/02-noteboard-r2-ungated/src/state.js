// Pure note-list operations. Every function returns a new array.

let counter = 0;
export function newId(now = Date.now()) {
  counter += 1;
  return `n${now.toString(36)}${counter.toString(36)}`;
}

export function addNote(notes, note) {
  return [{ pinned: false, text: '', ...note }, ...notes];
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

/** Pinned notes first, otherwise original order (stable). */
export function displayOrder(notes) {
  return [...notes.filter((n) => n.pinned), ...notes.filter((n) => !n.pinned)];
}
