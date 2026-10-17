// Persistence for notes. Takes a Storage-like object ({getItem, setItem,
// removeItem}) so it can be tested without a browser.

export const STORAGE_KEY = 'noteboard:notes';
export const BACKUP_KEY = 'noteboard:notes:unreadable';

function isValidNote(n) {
  return (
    n !== null &&
    typeof n === 'object' &&
    typeof n.id === 'string' &&
    n.id !== '' &&
    typeof n.text === 'string' &&
    typeof n.pinned === 'boolean' &&
    typeof n.updatedAt === 'number'
  );
}

// Returns { notes, error }. `error` is a user-facing message when stored data
// existed but could not be read. In that case the raw data is moved to
// BACKUP_KEY (so it is not lost, and so the problem is reported only once).
export function loadNotes(storage) {
  let raw;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch {
    return { notes: [], error: 'Saved notes could not be read (storage unavailable).' };
  }
  if (raw === null || raw === undefined) return { notes: [], error: null };

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = undefined;
  }
  const notes = parsed && Array.isArray(parsed.notes) ? parsed.notes : null;
  if (notes && notes.every(isValidNote)) {
    return { notes: notes.map((n) => ({ ...n })), error: null };
  }

  let backedUp = false;
  try {
    storage.setItem(BACKUP_KEY, raw);
    storage.removeItem(STORAGE_KEY);
    backedUp = true;
  } catch {
    // Leave the original data in place rather than lose it.
  }
  return {
    notes: [],
    error: backedUp
      ? `Saved notes could not be read; starting empty. The old data was kept under "${BACKUP_KEY}".`
      : 'Saved notes could not be read; starting empty.',
  };
}

// Returns { ok, error }.
export function saveNotes(storage, notes) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, notes }));
    return { ok: true, error: null };
  } catch {
    return { ok: false, error: 'Notes could not be saved (storage full or unavailable).' };
  }
}

export function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => void data.set(k, String(v)),
    removeItem: (k) => void data.delete(k),
    dump: () => Object.fromEntries(data),
  };
}
