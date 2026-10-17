// Edit-mode decisions, free of the DOM. The caller describes what was pressed;
// these functions say what the board should do.

export const NOT_EDITING = null;

export const Action = Object.freeze({
  IGNORE: "ignore",
  SAVE: "save",
  CANCEL: "cancel",
  ENTER: "enter",
});

/**
 * A pointer press anywhere on the page.
 * press: { noteId: string | null (the note under the pointer), inOverlay: boolean (modal or toast) }
 */
export function decidePress(editingId, press) {
  if (editingId === NOT_EDITING || press.inOverlay) {
    return Action.IGNORE;
  }
  if (press.noteId === editingId) {
    return Action.IGNORE;
  }
  return Action.SAVE;
}

/** A key press. key: { key: string, inOverlay: boolean } */
export function decideKey(editingId, key) {
  if (key.key !== "Escape" || key.inOverlay || editingId === NOT_EDITING) {
    return Action.IGNORE;
  }
  return Action.CANCEL;
}

/** A click on a note's body (not its toolbar). */
export function decideNoteClick(editingId, noteId) {
  if (editingId === noteId) {
    return Action.IGNORE;
  }
  return Action.ENTER;
}
