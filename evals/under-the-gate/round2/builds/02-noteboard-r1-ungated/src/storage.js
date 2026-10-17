// Persistence for notes. No DOM access: the storage backend is injected
// (localStorage in the browser, an in-memory stub in tests).

export const STORAGE_KEY = 'noteboard.notes';
export const BACKUP_KEY = 'noteboard.notes.unreadable';
const VERSION = 1;

function isValidNote(n) {
  return (
    n !== null &&
    typeof n === 'object' &&
    typeof n.id === 'string' &&
    n.id !== '' &&
    typeof n.text === 'string' &&
    typeof n.pinned === 'boolean'
  );
}

/**
 * Reads notes from storage.
 * Returns { notes, error } where error is null or a user-facing message.
 * Unreadable data is copied to BACKUP_KEY so it is never lost silently.
 */
export function loadNotes(storage) {
  let raw;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch {
    return { notes: [], error: 'Saved notes could not be accessed; starting with an empty board.' };
  }
  if (raw === null || raw === undefined) return { notes: [], error: null };

  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    return unreadable(storage, raw);
  }
  if (
    data === null ||
    typeof data !== 'object' ||
    data.version !== VERSION ||
    !Array.isArray(data.notes) ||
    !data.notes.every(isValidNote)
  ) {
    return unreadable(storage, raw);
  }
  const notes = data.notes.map(({ id, text, pinned }) => ({ id, text, pinned }));
  return { notes, error: null };
}

function unreadable(storage, raw) {
  let backedUp = false;
  try {
    storage.setItem(BACKUP_KEY, raw);
    storage.removeItem(STORAGE_KEY);
    backedUp = true;
  } catch {
    // Leave the original in place if we could not back it up.
  }
  const where = backedUp ? ` The unreadable data was kept under "${BACKUP_KEY}".` : '';
  return {
    notes: [],
    error: `Saved notes could not be read; starting with an empty board.${where}`,
  };
}

/** Writes notes. Returns null on success or a user-facing error message. */
export function saveNotes(storage, notes) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ version: VERSION, notes }));
    return null;
  } catch {
    return 'Notes could not be saved.';
  }
}

/** Minimal in-memory Storage, useful for tests. */
export function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => void map.set(k, String(v)),
    removeItem: (k) => void map.delete(k),
    clear: () => map.clear(),
  };
}
