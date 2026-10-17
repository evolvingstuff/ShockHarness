// Persistence for notes. Works against any object with the Web Storage API
// (getItem/setItem/removeItem), so it can be tested without a browser.

export const STORAGE_KEY = 'noteboard.notes';
export const BACKUP_PREFIX = 'noteboard.unreadable.';
const VERSION = 1;

function isValidNote(note) {
  return (
    note !== null &&
    typeof note === 'object' &&
    typeof note.id === 'string' &&
    note.id !== '' &&
    typeof note.text === 'string' &&
    typeof note.pinned === 'boolean' &&
    Number.isFinite(note.updatedAt)
  );
}

/** Returns the notes array if `data` is a well-formed payload, otherwise null. */
export function parsePayload(data) {
  if (data === null || typeof data !== 'object' || data.version !== VERSION) return null;
  if (!Array.isArray(data.notes) || !data.notes.every(isValidNote)) return null;
  const ids = new Set(data.notes.map((n) => n.id));
  if (ids.size !== data.notes.length) return null;
  return data.notes.map(({ id, text, pinned, updatedAt }) => ({ id, text, pinned, updatedAt }));
}

/**
 * Loads notes from storage.
 *
 * Result: { notes, error } where `error` is null on success, or an object
 * { message, backupKey } when stored data existed but could not be read.
 * Unreadable data is never thrown away: it is copied to a backup key first,
 * and only removed from the main key once the backup succeeded (so it is
 * reported once, not on every load). If the backup cannot be written the
 * original is left in place untouched.
 */
export function loadNotes(storage, { key = STORAGE_KEY, now = Date.now } = {}) {
  let raw;
  try {
    raw = storage.getItem(key);
  } catch (err) {
    return { notes: [], error: { message: `Could not access saved notes (${err.message}).`, backupKey: null } };
  }
  if (raw === null) return { notes: [], error: null };

  let notes = null;
  try {
    notes = parsePayload(JSON.parse(raw));
  } catch {
    notes = null;
  }
  if (notes) return { notes, error: null };

  let backupKey = `${BACKUP_PREFIX}${now()}`;
  try {
    // Avoid clobbering an earlier backup taken in the same millisecond.
    for (let i = 1; storage.getItem(backupKey) !== null; i++) backupKey = `${BACKUP_PREFIX}${now()}-${i}`;
    storage.setItem(backupKey, raw);
    storage.removeItem(key);
  } catch {
    backupKey = null;
  }
  const where = backupKey
    ? `A copy was kept in localStorage under "${backupKey}".`
    : `The data was left in place under "${key}" and will be overwritten by the next save.`;
  return { notes: [], error: { message: `Saved notes could not be read; starting empty. ${where}`, backupKey } };
}

/** Saves notes. Returns null on success or an error message string. */
export function saveNotes(storage, notes, { key = STORAGE_KEY } = {}) {
  try {
    storage.setItem(key, JSON.stringify({ version: VERSION, notes }));
    return null;
  } catch (err) {
    return `Could not save notes (${err.message}).`;
  }
}

/** Minimal in-memory Web Storage implementation (used by tests and as a fallback). */
export class MemoryStorage {
  constructor(entries = {}) {
    this.map = new Map(Object.entries(entries));
  }
  getItem(k) {
    return this.map.has(k) ? this.map.get(k) : null;
  }
  setItem(k, v) {
    this.map.set(k, String(v));
  }
  removeItem(k) {
    this.map.delete(k);
  }
}
