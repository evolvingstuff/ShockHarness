// Pure operations on the list of notes. Every function returns a new frozen
// list; no function mutates its input or touches the DOM.

export class UnknownNoteError extends Error {
  constructor(id) {
    super(`no note with id ${JSON.stringify(id)}`);
    this.name = "UnknownNoteError";
    this.noteId = id;
  }
}

export function createNote(id, text) {
  if (typeof id !== "string" || id.length === 0) {
    throw new TypeError(`a note id must be a non-empty string, got ${JSON.stringify(id)}`);
  }
  if (typeof text !== "string") {
    throw new TypeError(`note text must be a string, got ${typeof text}`);
  }
  return Object.freeze({ id, text, pinned: false });
}

function indexOfNote(notes, id) {
  const index = notes.findIndex((note) => note.id === id);
  if (index === -1) {
    throw new UnknownNoteError(id);
  }
  return index;
}

function replaceAt(notes, index, note) {
  return Object.freeze(notes.map((existing, i) => (i === index ? note : existing)));
}

/** Adds a note at the top of the list. */
export function addNote(notes, note) {
  if (notes.some((existing) => existing.id === note.id)) {
    throw new Error(`a note with id ${JSON.stringify(note.id)} already exists`);
  }
  return Object.freeze([note, ...notes]);
}

export function updateText(notes, id, text) {
  if (typeof text !== "string") {
    throw new TypeError(`note text must be a string, got ${typeof text}`);
  }
  const index = indexOfNote(notes, id);
  return replaceAt(notes, index, Object.freeze({ ...notes[index], text }));
}

export function togglePin(notes, id) {
  const index = indexOfNote(notes, id);
  const note = notes[index];
  return replaceAt(notes, index, Object.freeze({ ...note, pinned: !note.pinned }));
}

export function removeNote(notes, id) {
  indexOfNote(notes, id);
  return Object.freeze(notes.filter((note) => note.id !== id));
}

export function findNote(notes, id) {
  return notes[indexOfNote(notes, id)];
}

/** Pinned notes first; within each group the stored order is kept. */
export function displayOrder(notes) {
  const ordered = [
    ...notes.filter((note) => note.pinned),
    ...notes.filter((note) => !note.pinned),
  ];
  if (ordered.length !== notes.length) {
    throw new Error("display order lost or duplicated notes");
  }
  return Object.freeze(ordered);
}
