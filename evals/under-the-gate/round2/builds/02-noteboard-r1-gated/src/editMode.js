// Edit-mode decisions, independent of the DOM. The page classifies where a
// press landed and which key was pressed; these functions decide what happens.

export const MODE_VIEWING = "viewing";
export const MODE_EDITING = "editing";

export const VIEWING = Object.freeze({ mode: MODE_VIEWING });

export function editing(noteId) {
  return Object.freeze({ mode: MODE_EDITING, noteId });
}

// Where a press landed, as classified by the page.
export const PRESS_IN_EDITED_NOTE = "edited-note";
export const PRESS_IN_OVERLAY = "overlay"; // the modal or the toast
export const PRESS_ELSEWHERE = "elsewhere";

const PRESS_PLACES = Object.freeze([PRESS_IN_EDITED_NOTE, PRESS_IN_OVERLAY, PRESS_ELSEWHERE]);

export const ACTION_KEEP = "keep";
export const ACTION_SAVE = "save";
export const ACTION_CANCEL = "cancel";
export const ACTION_START = "start";

export const ESCAPE_KEY = "Escape";

/** A press outside the edited note saves it; presses in overlays (modal, toast) do not. */
export function decidePress(edit, place) {
  if (!PRESS_PLACES.includes(place)) {
    throw new RangeError(`unknown press place ${place}`);
  }
  if (edit.mode !== MODE_EDITING) {
    return ACTION_KEEP;
  }
  if (place === PRESS_ELSEWHERE) {
    return ACTION_SAVE;
  }
  return ACTION_KEEP;
}

/** Escape leaves edit mode without saving, unless the modal is open (it handles Escape itself). */
export function decideKey(edit, key, modalOpen) {
  if (edit.mode !== MODE_EDITING || modalOpen || key !== ESCAPE_KEY) {
    return ACTION_KEEP;
  }
  return ACTION_CANCEL;
}

/** Clicking a note's body enters edit mode for it, unless it is already being edited. */
export function decideNoteClick(edit, noteId) {
  if (edit.mode === MODE_EDITING && edit.noteId === noteId) {
    return ACTION_KEEP;
  }
  return ACTION_START;
}

/** The edit state after a note was deleted. */
export function afterDelete(edit, deletedId) {
  if (edit.mode === MODE_EDITING && edit.noteId === deletedId) {
    return VIEWING;
  }
  return edit;
}
