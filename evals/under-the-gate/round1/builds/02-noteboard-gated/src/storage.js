// Persistence of notes. No DOM; takes any object shaped like localStorage.

export const STORAGE_KEYS = Object.freeze({
  notes: "noteboard.notes",
  backup: "noteboard.notes.unreadable",
});

// Boundary (declared in .shockharness.toml): one JSON.parse of stored text.
// Returns { value, problem }; problem is null when the text parsed.
function readJson(text) {
  let value;
  try {
    value = JSON.parse(text);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    return { value: null, problem: `stored notes are not valid JSON: ${err.message}` };
  }
  return { value, problem: null };
}

function isNote(value) {
  return (
    typeof value === "object" &&
    value !== null &&
    Number.isInteger(value.id) &&
    typeof value.text === "string" &&
    typeof value.pinned === "boolean"
  );
}

export function describeProblem(value) {
  if (!Array.isArray(value)) return "stored notes are not a list";
  if (!value.every(isNote)) return "stored notes have an unexpected shape";
  const ids = new Set(value.map((note) => note.id));
  if (ids.size !== value.length) return "stored notes have duplicate ids";
  return null;
}

export function saveNotes(storage, notes) {
  storage.setItem(STORAGE_KEYS.notes, JSON.stringify(notes));
}

function unreadable(storage, raw, problem) {
  storage.setItem(STORAGE_KEYS.backup, raw);
  return Object.freeze({ notes: Object.freeze([]), problem });
}

// Returns { notes, problem }. problem is null, or says why the stored data was
// not used; the unreadable text is kept under STORAGE_KEYS.backup.
export function loadNotes(storage) {
  const raw = storage.getItem(STORAGE_KEYS.notes);
  if (raw === null) return Object.freeze({ notes: Object.freeze([]), problem: null });
  const parsed = readJson(raw);
  if (parsed.problem !== null) return unreadable(storage, raw, parsed.problem);
  const problem = describeProblem(parsed.value);
  if (problem !== null) return unreadable(storage, raw, problem);
  const notes = Object.freeze(parsed.value.map((note) => Object.freeze({ ...note })));
  return Object.freeze({ notes, problem: null });
}
