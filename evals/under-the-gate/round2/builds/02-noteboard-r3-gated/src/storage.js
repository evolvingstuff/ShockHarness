import { isString } from "./types.js";

// Persistence in a Storage-like object (localStorage in the browser, a stand-in in tests).

export const STORAGE_KEY = "noteboard.notes";
export const UNREADABLE_KEY_PREFIX = "noteboard.notes.unreadable.";

export const LOAD_OK = "ok";
export const LOAD_UNREADABLE = "unreadable";

const DECODED = "decoded";
const DECODE_FAILED = "failed";

const NO_PROBLEM = "";

function decodeJson(raw) {
  // Boundary (declared in .shockharness.toml): stored text is external input.
  let value;
  try {
    value = JSON.parse(raw);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    return Object.freeze({ status: DECODE_FAILED, error: err });
  }
  return Object.freeze({ status: DECODED, value });
}

function noteProblem(value, at) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return `entry ${at} is not an object`;
  }
  if (!isString(value.id) || value.id === "") {
    return `entry ${at} has no valid id`;
  }
  if (!isString(value.text)) {
    return `entry ${at} has no text`;
  }
  if (typeof value.pinned !== "boolean") {
    return `entry ${at} has no pinned flag`;
  }
  return NO_PROBLEM;
}

function shapeProblem(value) {
  if (!Array.isArray(value)) {
    return "the stored value is not a list";
  }
  for (const [at, entry] of value.entries()) {
    const problem = noteProblem(entry, at);
    if (problem !== NO_PROBLEM) {
      return problem;
    }
  }
  if (new Set(value.map((entry) => entry.id)).size !== value.length) {
    return "two entries share an id";
  }
  return NO_PROBLEM;
}

/** Moves unreadable data aside (never discards it) and describes what happened. */
function setAside(storage, raw, reason, nowMs) {
  const keptUnder = `${UNREADABLE_KEY_PREFIX}${nowMs}`;
  storage.setItem(keptUnder, raw);
  storage.removeItem(STORAGE_KEY);
  return Object.freeze({
    status: LOAD_UNREADABLE,
    notes: Object.freeze([]),
    keptUnder,
    message: `Saved notes could not be read (${reason}). They were kept in localStorage under "${keptUnder}" and the board starts empty.`,
  });
}

/**
 * Reads the notes. Unreadable data is moved to a timestamped key and reported in the result
 * as LOAD_UNREADABLE with a message for the user; the next load then starts cleanly.
 */
export function loadNotes(storage, nowMs) {
  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null) {
    return Object.freeze({ status: LOAD_OK, notes: Object.freeze([]) });
  }
  const decoded = decodeJson(raw);
  if (decoded.status === DECODE_FAILED) {
    return setAside(storage, raw, `not valid JSON: ${decoded.error.message}`, nowMs);
  }
  const problem = shapeProblem(decoded.value);
  if (problem !== NO_PROBLEM) {
    return setAside(storage, raw, problem, nowMs);
  }
  const notes = decoded.value.map((entry) =>
    Object.freeze({ id: entry.id, text: entry.text, pinned: entry.pinned }),
  );
  return Object.freeze({ status: LOAD_OK, notes: Object.freeze(notes) });
}

export function saveNotes(storage, notes) {
  const problem = shapeProblem(notes);
  if (problem !== NO_PROBLEM) {
    throw new TypeError(`refusing to save invalid notes: ${problem}`);
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(notes));
}
