// localStorage persistence, DOM-free. The storage object is
// injected so tests can pass a fake.

export const STORAGE_KEY = 'noteboard.notes';
export const CORRUPT_KEY = 'noteboard.notes.unreadable';

function isNote(n) {
  return (
    n !== null &&
    typeof n === 'object' &&
    typeof n.id === 'string' &&
    typeof n.text === 'string' &&
    typeof n.pinned === 'boolean'
  );
}

/**
 * Load notes. Returns { notes, error }.
 * If stored data cannot be read, the raw value is moved to CORRUPT_KEY (so it
 * is not lost) and `error` describes the problem. Because the bad value is
 * moved out of STORAGE_KEY, the problem is reported only once.
 */
export function loadNotes(storage) {
  let raw;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch (e) {
    return { notes: [], error: `Could not access saved notes (${e.message}).` };
  }
  if (raw === null || raw === undefined) return { notes: [], error: null };

  let reason = null;
  let notes = null;
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) reason = 'expected a list of notes';
    else if (!parsed.every(isNote)) reason = 'some notes are malformed';
    else notes = parsed;
  } catch {
    reason = 'not valid JSON';
  }
  if (notes) return { notes, error: null };

  let kept = true;
  try {
    storage.setItem(CORRUPT_KEY, raw);
    storage.removeItem(STORAGE_KEY);
  } catch {
    kept = false;
  }
  const where = kept
    ? ` A copy was kept in localStorage under "${CORRUPT_KEY}".`
    : '';
  return {
    notes: [],
    error: `Saved notes could not be read (${reason}); starting with an empty board.${where}`,
  };
}

/** Save notes. Returns null on success or an error message. */
export function saveNotes(storage, notes) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(notes));
    return null;
  } catch (e) {
    return `Could not save notes (${e.message}).`;
  }
}
