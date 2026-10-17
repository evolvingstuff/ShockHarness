// Persistence of notes in a Web Storage object (localStorage in the page, a
// fake in tests). Nothing here touches `document`.

import { isString } from "./checks.js";

export const STORAGE_KEY = "noteboard.notes";
export const UNREADABLE_KEY_PREFIX = "noteboard.unreadable.";

export const READ_OK = "ok";
export const READ_UNREADABLE = "unreadable";

function decodeJson(text) {
  // Boundary (declared in .shockharness.toml): one JSON.parse of stored text.
  // A syntax error becomes a first-class "unreadable" result the caller must
  // report; it is never turned into an empty board here.
  let value;
  try {
    value = JSON.parse(text);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    return Object.freeze({ ok: false, reason: `not valid JSON (${err.message})` });
  }
  return Object.freeze({ ok: true, value });
}

/** Lists what is wrong with a decoded value; an empty list means it is a valid notes array. */
export function describeShapeProblems(value) {
  if (!Array.isArray(value)) {
    return [`expected an array of notes, found ${typeof value}`];
  }
  const problems = [];
  const ids = new Set();
  value.forEach((note, index) => {
    if (note === null || typeof note !== "object" || Array.isArray(note)) {
      problems.push(`note ${index} is not an object`);
      return;
    }
    if (!isString(note.id) || note.id === "") {
      problems.push(`note ${index} has no string id`);
    } else if (ids.has(note.id)) {
      problems.push(`note ${index} repeats id ${note.id}`);
    }
    ids.add(note.id);
    if (!isString(note.text)) {
      problems.push(`note ${index} has no string text`);
    }
    if (typeof note.pinned !== "boolean") {
      problems.push(`note ${index} has no boolean pinned flag`);
    }
  });
  return problems;
}

function freezeNotes(value) {
  return Object.freeze(
    value.map((note) => Object.freeze({ id: note.id, text: note.text, pinned: note.pinned })),
  );
}

function unreadable(raw, reason) {
  return Object.freeze({ status: READ_UNREADABLE, raw, reason });
}

/**
 * Reads the stored notes. Returns `{ status: "ok", notes }` (no stored notes
 * yields an empty list) or `{ status: "unreadable", raw, reason }` when stored
 * data exists but cannot be used.
 */
export function readStoredNotes(storage) {
  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null) {
    return Object.freeze({ status: READ_OK, notes: Object.freeze([]) });
  }
  const decoded = decodeJson(raw);
  if (!decoded.ok) {
    return unreadable(raw, decoded.reason);
  }
  const problems = describeShapeProblems(decoded.value);
  if (problems.length > 0) {
    return unreadable(raw, problems.join("; "));
  }
  return Object.freeze({ status: READ_OK, notes: freezeNotes(decoded.value) });
}

/**
 * Moves unreadable stored data aside under a new key so that it is kept, not
 * discarded, and is reported only once. Returns the key it was kept under.
 */
export function setAsideUnreadable(storage, raw, timestamp) {
  const key = `${UNREADABLE_KEY_PREFIX}${timestamp}`;
  if (storage.getItem(key) !== null) {
    throw new Error(`refusing to overwrite kept data under ${key}`);
  }
  storage.setItem(key, raw);
  if (storage.getItem(key) !== raw) {
    throw new Error(`stored data could not be kept under ${key}`);
  }
  storage.removeItem(STORAGE_KEY);
  return key;
}

export function writeNotes(storage, notes) {
  const problems = describeShapeProblems(notes);
  if (problems.length > 0) {
    throw new TypeError(`refusing to store invalid notes: ${problems.join("; ")}`);
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(notes));
}
