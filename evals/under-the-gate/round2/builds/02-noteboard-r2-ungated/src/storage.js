// Persistence for notes. Takes a Storage-like object (getItem/setItem) so it
// can be tested without a browser.

export const STORAGE_KEY = 'noteboard:v1';
export const BACKUP_PREFIX = 'noteboard:unreadable:';

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

function parse(raw) {
  const data = JSON.parse(raw);
  if (data === null || typeof data !== 'object' || !Array.isArray(data.notes)) {
    throw new Error('unexpected format');
  }
  if (!data.notes.every(isValidNote)) {
    throw new Error('a note has an unexpected format');
  }
  return data.notes.map((n) => ({
    id: n.id,
    text: n.text,
    pinned: n.pinned,
    updatedAt: typeof n.updatedAt === 'number' ? n.updatedAt : 0,
  }));
}

/**
 * Load notes. Never throws.
 * Returns { notes, error } where error is null or a user-facing message.
 * Unreadable data is copied to a backup key before the board starts empty, so
 * it is not lost when the next save overwrites the main key.
 */
export function loadNotes(storage, now = Date.now()) {
  let raw;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch {
    return { notes: [], error: 'Saved notes could not be read (storage unavailable). Starting with an empty board.' };
  }
  if (raw === null || raw === undefined) return { notes: [], error: null };

  try {
    return { notes: parse(raw), error: null };
  } catch {
    const backupKey = BACKUP_PREFIX + now;
    try {
      storage.setItem(backupKey, raw);
      storage.removeItem(STORAGE_KEY);
      return {
        notes: [],
        error: `Saved notes could not be read. Starting with an empty board; the old data was kept in localStorage under "${backupKey}".`,
      };
    } catch {
      return {
        notes: [],
        error: 'Saved notes could not be read and could not be backed up. Starting with an empty board; saving will overwrite the old data.',
      };
    }
  }
}

/** Save notes. Returns null on success or a user-facing error message. */
export function saveNotes(storage, notes) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ notes }));
    return null;
  } catch {
    return 'Notes could not be saved.';
  }
}
