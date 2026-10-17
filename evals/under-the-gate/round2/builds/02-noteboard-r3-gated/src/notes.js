import { isString } from "./types.js";

// Board state: an immutable array of immutable notes. Every function returns a new array.

export function createNote(id, text) {
  if (!isString(id) || id === "") {
    throw new TypeError(`a note id must be a non-empty string, got ${String(id)}`);
  }
  if (!isString(text)) {
    throw new TypeError(`a note text must be a string, got ${typeof text}`);
  }
  return Object.freeze({ id, text, pinned: false });
}

function indexOfNote(notes, id) {
  const index = notes.findIndex((note) => note.id === id);
  if (index === -1) {
    throw new RangeError(`no note with id ${id}`);
  }
  return index;
}

function replaceAt(notes, index, note) {
  return Object.freeze(notes.map((existing, at) => (at === index ? note : existing)));
}

export function addNote(notes, note) {
  if (notes.some((existing) => existing.id === note.id)) {
    throw new RangeError(`a note with id ${note.id} already exists`);
  }
  return Object.freeze([note, ...notes]);
}

export function updateText(notes, id, text) {
  if (!isString(text)) {
    throw new TypeError(`a note text must be a string, got ${typeof text}`);
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
  const index = indexOfNote(notes, id);
  return Object.freeze(notes.filter((_, at) => at !== index));
}

export function findNote(notes, id) {
  return notes[indexOfNote(notes, id)];
}

/** Pinned notes first; otherwise the stored order is kept. */
export function displayOrder(notes) {
  const pinned = notes.filter((note) => note.pinned);
  const unpinned = notes.filter((note) => !note.pinned);
  return Object.freeze([...pinned, ...unpinned]);
}
