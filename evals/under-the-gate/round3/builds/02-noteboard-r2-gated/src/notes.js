// Pure note-list operations. Every function returns a new frozen list; inputs are never mutated.

export function createNote(id, text, createdAt) {
  return Object.freeze({ id, text, pinned: false, createdAt });
}

function requireNote(notes, id) {
  if (!notes.some((note) => note.id === id)) {
    throw new RangeError(`no note with id ${id}`);
  }
}

export function addNote(notes, note) {
  if (notes.some((existing) => existing.id === note.id)) {
    throw new RangeError(`a note with id ${note.id} already exists`);
  }
  return Object.freeze([...notes, note]);
}

export function updateText(notes, id, text) {
  requireNote(notes, id);
  return Object.freeze(
    notes.map((note) => (note.id === id ? Object.freeze({ ...note, text }) : note)),
  );
}

export function togglePin(notes, id) {
  requireNote(notes, id);
  return Object.freeze(
    notes.map((note) => (note.id === id ? Object.freeze({ ...note, pinned: !note.pinned }) : note)),
  );
}

export function removeNote(notes, id) {
  requireNote(notes, id);
  return Object.freeze(notes.filter((note) => note.id !== id));
}

function compareForDisplay(a, b) {
  if (a.pinned !== b.pinned) {
    return Number(b.pinned) - Number(a.pinned);
  }
  return a.createdAt - b.createdAt;
}

/** Pinned notes first, then oldest first. */
export function displayOrder(notes) {
  return Object.freeze([...notes].sort(compareForDisplay));
}
