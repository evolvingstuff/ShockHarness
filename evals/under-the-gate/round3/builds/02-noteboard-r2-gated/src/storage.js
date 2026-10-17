// Reading and writing the notes in a Storage-like object (getItem/setItem/removeItem).
// No DOM access: the caller passes the storage in.

export const STORAGE_FORMAT_VERSION = 1;

export class UnreadableNotesError extends Error {
  constructor(message, raw, options) {
    super(message, options);
    this.name = "UnreadableNotesError";
    this.raw = raw;
  }
}

function parseJson(raw) {
  // Boundary (declared in .shockharness.toml): one JSON.parse of stored text.
  try {
    return JSON.parse(raw);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    throw new UnreadableNotesError(`stored notes are not valid JSON: ${err.message}`, raw, {
      cause: err,
    });
  }
}

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNote(value) {
  return (
    isPlainObject(value) &&
    typeof value.id === "string" &&
    typeof value.text === "string" &&
    typeof value.pinned === "boolean" &&
    Number.isFinite(value.createdAt)
  );
}

/** Parse stored text into a frozen note list; throws UnreadableNotesError on any defect. */
export function parseNotes(raw) {
  const data = parseJson(raw);
  if (!isPlainObject(data) || data.version !== STORAGE_FORMAT_VERSION) {
    throw new UnreadableNotesError(
      `stored notes do not have format version ${STORAGE_FORMAT_VERSION}`,
      raw,
    );
  }
  if (!Array.isArray(data.notes) || !data.notes.every(isNote)) {
    throw new UnreadableNotesError("stored notes contain an entry that is not a note", raw);
  }
  const ids = new Set(data.notes.map((note) => note.id));
  if (ids.size !== data.notes.length) {
    throw new UnreadableNotesError("stored notes contain duplicate ids", raw);
  }
  return Object.freeze(
    data.notes.map((note) =>
      Object.freeze({ id: note.id, text: note.text, pinned: note.pinned, createdAt: note.createdAt }),
    ),
  );
}

export function serializeNotes(notes) {
  return JSON.stringify({ version: STORAGE_FORMAT_VERSION, notes });
}

/** Nothing stored yet means an empty board; stored text that cannot be read throws. */
export function readNotes(storage, key) {
  const raw = storage.getItem(key);
  if (raw === null) {
    return Object.freeze([]);
  }
  return parseNotes(raw);
}

export function writeNotes(storage, key, notes) {
  storage.setItem(key, serializeNotes(notes));
}
