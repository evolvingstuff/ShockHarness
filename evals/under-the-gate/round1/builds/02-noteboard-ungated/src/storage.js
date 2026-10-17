export const KEY = 'noteboard.notes';

function valid(n) {
  return n && typeof n === 'object' && typeof n.id === 'string' &&
    typeof n.text === 'string' && typeof n.pinned === 'boolean';
}

// Returns { notes, error }. error is a message when stored data was unreadable.
// Unreadable data is left in place under a backup key rather than discarded.
export function loadNotes(storage) {
  let raw;
  try {
    raw = storage.getItem(KEY);
  } catch (e) {
    return { notes: [], error: 'Could not access saved notes; starting empty.' };
  }
  if (raw == null) return { notes: [], error: null };
  try {
    const data = JSON.parse(raw);
    if (!Array.isArray(data) || !data.every(valid)) throw new Error('bad shape');
    return { notes: data, error: null };
  } catch (e) {
    try { storage.setItem(KEY + '.corrupt', raw); } catch (_) { /* ignore */ }
    return { notes: [], error: 'Saved notes were unreadable; starting with an empty board (original kept as backup).' };
  }
}

export function saveNotes(storage, notes) {
  try {
    storage.setItem(KEY, JSON.stringify(notes));
    return true;
  } catch (e) {
    return false;
  }
}
