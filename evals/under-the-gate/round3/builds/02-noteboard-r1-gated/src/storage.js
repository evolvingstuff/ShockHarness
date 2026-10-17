// Persistence of notes in a Storage (localStorage in the page). No DOM access.

export class StoredNotesError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "StoredNotesError";
  }
}

export function encodeNotes(notes) {
  return JSON.stringify(notes.map(({ id, text, pinned }) => ({ id, text, pinned })));
}

function parseJson(text) {
  // Boundary (declared in .shockharness.toml): decoding stored, external text.
  try {
    return JSON.parse(text);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    throw new StoredNotesError(`stored notes are not valid JSON: ${err.message}`, { cause: err });
  }
}

function decodeNote(item, index) {
  if (typeof item !== "object" || item === null || Array.isArray(item)) {
    throw new StoredNotesError(`stored note ${index} is not an object`);
  }
  if (typeof item.id !== "string" || item.id === "") {
    throw new StoredNotesError(`stored note ${index} has no valid id`);
  }
  if (typeof item.text !== "string") {
    throw new StoredNotesError(`stored note ${index} has no text`);
  }
  if (typeof item.pinned !== "boolean") {
    throw new StoredNotesError(`stored note ${index} has no pinned flag`);
  }
  return Object.freeze({ id: item.id, text: item.text, pinned: item.pinned });
}

export function decodeNotes(text) {
  const data = parseJson(text);
  if (!Array.isArray(data)) {
    throw new StoredNotesError("stored notes are not a list");
  }
  const notes = Object.freeze(data.map(decodeNote));
  if (new Set(notes.map((note) => note.id)).size !== notes.length) {
    throw new StoredNotesError("stored notes have duplicate ids");
  }
  return notes;
}

export function saveNotes(storage, key, notes) {
  storage.setItem(key, encodeNotes(notes));
}

/**
 * Reads the stored notes. Unreadable data is never dropped silently: it is moved
 * to a backup key named after the time it was found, and the returned problem
 * describes it so the page can tell the user (once: the main key is cleared).
 * Returns { notes, problem }, where problem is null when nothing went wrong.
 */
export function openNotes(storage, key, foundAt) {
  const raw = storage.getItem(key);
  if (raw === null) {
    return Object.freeze({ notes: Object.freeze([]), problem: null });
  }
  let notes;
  // Boundary (declared in .shockharness.toml): unreadable stored data is
  // reported to the user instead of loaded.
  try {
    notes = decodeNotes(raw);
  } catch (err) {
    if (!(err instanceof StoredNotesError)) throw err;
    return setAsideUnreadable(storage, key, raw, foundAt, err);
  }
  return Object.freeze({ notes, problem: null });
}

function setAsideUnreadable(storage, key, raw, foundAt, err) {
  const backupKey = `${key}.unreadable.${foundAt.toISOString()}`;
  storage.setItem(backupKey, raw);
  storage.removeItem(key);
  const problem =
    `Your saved notes could not be read (${err.message}). ` +
    `The board starts empty; the unreadable data was kept in localStorage under "${backupKey}".`;
  return Object.freeze({ notes: Object.freeze([]), problem });
}
