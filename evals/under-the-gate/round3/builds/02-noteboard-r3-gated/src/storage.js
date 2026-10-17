// Reading and writing the notes in a Storage-like object (localStorage in the
// browser, a fake in tests). Nothing here touches `document`.

export const STORAGE_KEY = "noteboard.notes";
// Data that could not be read is moved here so that it is never lost.
export const UNREADABLE_KEY = "noteboard.unreadable";
export const FORMAT_VERSION = 1;

function parseJson(raw) {
  // Boundary (declared in .shockharness.toml, exception = "SyntaxError"): one call.
  let value;
  try {
    value = JSON.parse(raw);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    return Object.freeze({ ok: false, reason: `it is not valid JSON (${err.message})` });
  }
  return Object.freeze({ ok: true, value });
}

function noteProblem(note, index) {
  if (typeof note !== "object" || note === null) {
    return `note ${index} is not an object`;
  }
  if (typeof note.id !== "string" || note.id.length === 0) {
    return `note ${index} has no valid id`;
  }
  if (typeof note.text !== "string") {
    return `note ${index} has no text`;
  }
  if (typeof note.pinned !== "boolean") {
    return `note ${index} has no pinned flag`;
  }
  return null;
}

function documentProblem(data) {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return "it is not a notes document";
  }
  if (data.version !== FORMAT_VERSION) {
    return `its format version ${JSON.stringify(data.version)} is not ${FORMAT_VERSION}`;
  }
  if (!Array.isArray(data.notes)) {
    return "it has no list of notes";
  }
  const problems = data.notes.map(noteProblem).filter((problem) => problem !== null);
  if (problems.length > 0) {
    return problems[0];
  }
  const ids = new Set(data.notes.map((note) => note.id));
  if (ids.size !== data.notes.length) {
    return "two notes share an id";
  }
  return null;
}

/**
 * Decodes stored text. Returns `{ ok: true, notes }` or `{ ok: false, reason }`;
 * the caller must handle both.
 */
export function decodeNotes(raw) {
  const parsed = parseJson(raw);
  if (!parsed.ok) {
    return parsed;
  }
  const problem = documentProblem(parsed.value);
  if (problem !== null) {
    return Object.freeze({ ok: false, reason: problem });
  }
  const notes = parsed.value.notes.map((note) =>
    Object.freeze({ id: note.id, text: note.text, pinned: note.pinned }),
  );
  return Object.freeze({ ok: true, notes: Object.freeze(notes) });
}

export function encodeNotes(notes) {
  return JSON.stringify({
    version: FORMAT_VERSION,
    notes: notes.map((note) => ({ id: note.id, text: note.text, pinned: note.pinned })),
  });
}

/**
 * Loads the notes. Returns `{ notes, problem }`: `problem` is null when the
 * stored data was read (or there was none), otherwise a message for the user.
 * Unreadable data is moved to UNREADABLE_KEY, so it is kept and reported once.
 */
export function loadNotes(storage) {
  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null) {
    return Object.freeze({ notes: Object.freeze([]), problem: null });
  }
  const decoded = decodeNotes(raw);
  if (decoded.ok) {
    return Object.freeze({ notes: decoded.notes, problem: null });
  }
  storage.setItem(UNREADABLE_KEY, raw);
  storage.removeItem(STORAGE_KEY);
  const problem =
    `Your saved notes could not be read because ${decoded.reason}. ` +
    `The board starts empty; the old data was kept in localStorage under "${UNREADABLE_KEY}".`;
  return Object.freeze({ notes: Object.freeze([]), problem });
}

export function saveNotes(storage, notes) {
  storage.setItem(STORAGE_KEY, encodeNotes(notes));
}
