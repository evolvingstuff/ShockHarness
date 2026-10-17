// Pure note-list operations. Notes are frozen records; every operation returns a new list.

import { isString, isNonEmptyString } from "./checks.js";

export function createNote(id, text) {
  if (!isNonEmptyString(id)) {
    throw new TypeError(`a note id must be a non-empty string, got ${String(id)}`);
  }
  if (!isString(text)) {
    throw new TypeError(`note text must be a string, got ${typeof text}`);
  }
  return Object.freeze({ id, text, pinned: false });
}

function requireNote(notes, id) {
  const note = notes.find((candidate) => candidate.id === id);
  if (note === undefined) {
    throw new RangeError(`no note with id ${id}`);
  }
  return note;
}

function replaceNote(notes, id, change) {
  requireNote(notes, id);
  return Object.freeze(
    notes.map((note) => (note.id === id ? Object.freeze({ ...note, ...change }) : note)),
  );
}

export function addNote(notes, note) {
  if (notes.some((existing) => existing.id === note.id)) {
    throw new RangeError(`a note with id ${note.id} already exists`);
  }
  return Object.freeze([note, ...notes]);
}

export function updateText(notes, id, text) {
  if (!isString(text)) {
    throw new TypeError(`note text must be a string, got ${typeof text}`);
  }
  return replaceNote(notes, id, { text });
}

export function togglePin(notes, id) {
  return replaceNote(notes, id, { pinned: !requireNote(notes, id).pinned });
}

export function deleteNote(notes, id) {
  requireNote(notes, id);
  return Object.freeze(notes.filter((note) => note.id !== id));
}

/** Pinned notes first; within each group the stored order is kept. */
export function displayOrder(notes) {
  const pinned = notes.filter((note) => note.pinned);
  const unpinned = notes.filter((note) => !note.pinned);
  return Object.freeze([...pinned, ...unpinned]);
}
