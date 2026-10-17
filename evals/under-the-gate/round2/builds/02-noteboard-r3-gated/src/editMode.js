// Edit-mode decisions. Pure: the DOM layer describes what happened, these functions decide.

export const NOT_EDITING = Object.freeze({ active: false });

export const PRESS_SAVE = "save";
export const PRESS_IGNORE = "ignore";

export const KEY_CANCEL = "cancel";
export const KEY_IGNORE = "ignore";

export const CLICK_BEGIN_EDIT = "begin-edit";
export const CLICK_IGNORE = "ignore";

const CANCEL_KEY = "Escape";

export function beginEditing(note) {
  return Object.freeze({ active: true, id: note.id, draft: note.text });
}

export function withDraft(editing, draft) {
  if (!editing.active) {
    throw new Error("cannot change the draft when no note is being edited");
  }
  return Object.freeze({ ...editing, draft });
}

/**
 * A press anywhere on the page. `press.noteId` is the id of the note the press landed in,
 * or null; `press.inDialog` tells whether it landed in a dialog, which is a separate layer
 * and never ends edit mode.
 */
export function decidePress(editing, press) {
  if (!editing.active || press.inDialog || press.noteId === editing.id) {
    return PRESS_IGNORE;
  }
  return PRESS_SAVE;
}

/** A key press; while a dialog is open its own Escape handling wins. */
export function decideKey(editing, keyEvent) {
  if (editing.active && !keyEvent.dialogOpen && keyEvent.key === CANCEL_KEY) {
    return KEY_CANCEL;
  }
  return KEY_IGNORE;
}

/** A click on a note's body (not on its toolbar). */
export function decideNoteClick(editing, noteId) {
  if (editing.active && editing.id === noteId) {
    return CLICK_IGNORE;
  }
  return CLICK_BEGIN_EDIT;
}

/** The edit state after the note `removedId` was deleted. */
export function afterRemoval(editing, removedId) {
  if (editing.active && editing.id === removedId) {
    return NOT_EDITING;
  }
  return editing;
}
