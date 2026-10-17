import { readNotes, UnreadableNotesError } from "./storage.js";

/**
 * Load the board. Unreadable stored data is never dropped: it is moved to a
 * quarantine key (named with `now`) and the result carries a message for the user.
 * keys: { notes, quarantinePrefix }.
 */
export function loadBoard(storage, keys, now) {
  let notes;
  // Boundary (declared in .shockharness.toml): one read of stored notes.
  try {
    notes = readNotes(storage, keys.notes);
  } catch (err) {
    if (!(err instanceof UnreadableNotesError)) throw err;
    return quarantine(storage, keys, now, err);
  }
  return Object.freeze({ notes, problem: null });
}

function quarantine(storage, keys, now, error) {
  const quarantineKey = `${keys.quarantinePrefix}${now}`;
  storage.setItem(quarantineKey, error.raw);
  storage.removeItem(keys.notes);
  const problem =
    `Saved notes could not be read (${error.message}). ` +
    `Starting with an empty board; the old data was kept in localStorage under "${quarantineKey}".`;
  return Object.freeze({ notes: Object.freeze([]), problem });
}
