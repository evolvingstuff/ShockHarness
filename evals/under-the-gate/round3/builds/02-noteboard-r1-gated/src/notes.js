// Notes as immutable values. Every operation returns a new, frozen list.

export class UnknownNoteError extends Error {
  constructor(id) {
    super(`no note has id ${JSON.stringify(id)}`);
    this.name = "UnknownNoteError";
  }
}

export function createNote(id, text) {
  if (typeof id !== "string" || id === "") {
    throw new TypeError("a note id must be a non-empty string");
  }
  if (typeof text !== "string") {
    throw new TypeError("a note's text must be a string");
  }
  return Object.freeze({ id, text, pinned: false });
}

export function findNote(notes, id) {
  const note = notes.find((candidate) => candidate.id === id);
  if (note === undefined) {
    throw new UnknownNoteError(id);
  }
  return note;
}

export function addNote(notes, note) {
  if (notes.some((existing) => existing.id === note.id)) {
    throw new Error(`a note with id ${JSON.stringify(note.id)} already exists`);
  }
  return Object.freeze([note, ...notes]);
}

function replaceNote(notes, id, change) {
  findNote(notes, id);
  return Object.freeze(
    notes.map((note) => (note.id === id ? Object.freeze({ ...note, ...change(note) }) : note)),
  );
}

export function updateNoteText(notes, id, text) {
  return replaceNote(notes, id, () => ({ text }));
}

export function togglePin(notes, id) {
  return replaceNote(notes, id, (note) => ({ pinned: !note.pinned }));
}

export function removeNote(notes, id) {
  findNote(notes, id);
  return Object.freeze(notes.filter((note) => note.id !== id));
}

/** Pinned notes first; otherwise the stored order is kept. */
export function orderedForDisplay(notes) {
  const pinned = notes.filter((note) => note.pinned);
  const unpinned = notes.filter((note) => !note.pinned);
  return Object.freeze([...pinned, ...unpinned]);
}
