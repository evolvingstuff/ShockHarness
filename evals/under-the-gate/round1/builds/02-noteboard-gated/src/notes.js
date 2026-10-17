// Pure note list operations; every function returns a new frozen list.

function freezeAll(notes) {
  return Object.freeze(notes.map((note) => Object.freeze({ ...note })));
}

export function nextId(notes) {
  return notes.reduce((highest, note) => Math.max(highest, note.id), 0) + 1;
}

export function addNote(notes, text) {
  const note = { id: nextId(notes), text, pinned: false };
  return freezeAll([...notes, note]);
}

function requireNote(notes, id) {
  if (!notes.some((note) => note.id === id)) {
    throw new RangeError(`no note with id ${id}`);
  }
}

export function updateText(notes, id, text) {
  requireNote(notes, id);
  return freezeAll(notes.map((note) => (note.id === id ? { ...note, text } : note)));
}

export function togglePin(notes, id) {
  requireNote(notes, id);
  return freezeAll(notes.map((note) => (note.id === id ? { ...note, pinned: !note.pinned } : note)));
}

export function removeNote(notes, id) {
  requireNote(notes, id);
  return freezeAll(notes.filter((note) => note.id !== id));
}

export function displayOrder(notes) {
  return [...notes.filter((note) => note.pinned), ...notes.filter((note) => !note.pinned)];
}

export function findNote(notes, id) {
  const note = notes.find((candidate) => candidate.id === id);
  if (note === undefined) {
    throw new RangeError(`no note with id ${id}`);
  }
  return note;
}
