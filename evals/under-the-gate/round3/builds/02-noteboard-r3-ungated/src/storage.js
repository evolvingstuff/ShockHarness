// Persistence of notes in a Storage-like object (localStorage in the browser).
// No DOM access here so it can be tested under plain Node.

export const STORAGE_KEY = 'noteboard.notes';
export const BACKUP_PREFIX = 'noteboard.unreadable.';

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

/** Parses a stored value. Throws if it is not a valid notes array. */
export function parseNotes(raw) {
  const data = JSON.parse(raw);
  if (!Array.isArray(data)) throw new Error('stored notes are not a list');
  const ids = new Set();
  for (const n of data) {
    if (!isValidNote(n)) throw new Error('stored notes contain an invalid entry');
    if (ids.has(n.id)) throw new Error('stored notes contain a duplicate id');
    ids.add(n.id);
  }
  return data.map((n) => ({ id: n.id, text: n.text, pinned: n.pinned }));
}

/**
 * Loads notes. Returns { notes, error }.
 * - Nothing stored: { notes: [], error: null }.
 * - Unreadable data: the raw value is moved to a backup key (so it is never
 *   discarded), the main key is reset, and `error` describes the problem
 *   including the backup key. Because the main key is reset, the problem is
 *   reported only once rather than on every load.
 * - Storage itself unavailable: { notes: [], error } without touching anything.
 */
export function loadNotes(storage, now = Date.now) {
  let raw;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch (e) {
    return { notes: [], error: `Saved notes could not be read (${e.message}).` };
  }
  if (raw === null || raw === undefined) return { notes: [], error: null };
  try {
    return { notes: parseNotes(raw), error: null };
  } catch (e) {
    const backupKey = BACKUP_PREFIX + now();
    try {
      storage.setItem(backupKey, raw);
      storage.setItem(STORAGE_KEY, '[]');
    } catch {
      // Could not back up: leave the original data in place untouched.
      return {
        notes: [],
        error: `Saved notes could not be read (${e.message}); starting empty. The original data was left in storage.`,
        backupKey: null,
      };
    }
    return {
      notes: [],
      error: `Saved notes could not be read (${e.message}); starting empty. The original data was kept under "${backupKey}".`,
      backupKey,
    };
  }
}

/** Saves notes. Returns null on success or an error message. */
export function saveNotes(storage, notes) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(notes));
    return null;
  } catch (e) {
    return `Notes could not be saved (${e.message}).`;
  }
}
