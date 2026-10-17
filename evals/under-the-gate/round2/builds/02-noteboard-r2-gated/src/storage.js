// Persistence of notes in a Storage-like object (localStorage in the browser).
// loadNotes never discards unreadable data silently: it returns a "corrupt"
// result that the caller must report, carrying the raw text and the reason.

import { isString, isNonEmptyString } from "./checks.js";

export const LOAD_OK = "ok";
export const LOAD_CORRUPT = "corrupt";

export class InvalidNotesError extends Error {}

function parseJson(raw) {
  // Boundary (declared in .shockharness.toml, exception = "SyntaxError"): one JSON.parse
  // of text read from localStorage, which is outside the program's control.
  let value;
  try {
    value = JSON.parse(raw);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    return Object.freeze({ ok: false, reason: `not valid JSON: ${err.message}` });
  }
  return Object.freeze({ ok: true, value });
}

function invalidNoteReason(item, index) {
  if (item === null || typeof item !== "object" || Array.isArray(item)) {
    return `entry ${index} is not an object`;
  }
  if (!isNonEmptyString(item.id)) {
    return `entry ${index} has no valid id`;
  }
  if (!isString(item.text)) {
    return `entry ${index} has no text`;
  }
  if (typeof item.pinned !== "boolean") {
    return `entry ${index} has no pinned flag`;
  }
  return null;
}

function validationReason(value) {
  if (!Array.isArray(value)) {
    return "stored value is not a list of notes";
  }
  const reasons = value.map(invalidNoteReason).filter((reason) => reason !== null);
  if (reasons.length > 0) {
    return reasons[0];
  }
  if (new Set(value.map((item) => item.id)).size !== value.length) {
    return "note ids are not unique";
  }
  return null;
}

function corrupt(raw, reason) {
  return Object.freeze({ status: LOAD_CORRUPT, raw, reason });
}

/** Returns { status: LOAD_OK, notes } or { status: LOAD_CORRUPT, raw, reason }. */
export function loadNotes(storage, key) {
  const raw = storage.getItem(key);
  if (raw === null) {
    return Object.freeze({ status: LOAD_OK, notes: Object.freeze([]) });
  }
  const parsed = parseJson(raw);
  if (!parsed.ok) {
    return corrupt(raw, parsed.reason);
  }
  const reason = validationReason(parsed.value);
  if (reason !== null) {
    return corrupt(raw, reason);
  }
  const notes = parsed.value.map((item) =>
    Object.freeze({ id: item.id, text: item.text, pinned: item.pinned }),
  );
  return Object.freeze({ status: LOAD_OK, notes: Object.freeze(notes) });
}

export function saveNotes(storage, key, notes) {
  const reason = validationReason(notes);
  if (reason !== null) {
    throw new InvalidNotesError(`refusing to save notes: ${reason}`);
  }
  storage.setItem(key, JSON.stringify(notes));
}

/**
 * Moves unreadable stored data to backupKey and starts an empty list under key,
 * so the data is kept and is reported only once.
 */
export function quarantineCorrupt(storage, key, backupKey, raw) {
  storage.setItem(backupKey, raw);
  storage.setItem(key, JSON.stringify([]));
}
