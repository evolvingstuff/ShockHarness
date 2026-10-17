// Edit-mode decisions, independent of the DOM. The editing state is either
// NOT_EDITING or { noteId, draft }.

import { isNonEmptyString } from "./checks.js";

export const NOT_EDITING = Object.freeze({ noteId: null, draft: null });

export const ACTION_NONE = "none";
export const ACTION_SAVE = "save";
export const ACTION_CANCEL = "cancel";

export function isEditing(editing) {
  return editing.noteId !== null;
}

export function startEditing(noteId, text) {
  if (!isNonEmptyString(noteId)) {
    throw new TypeError(`a note id must be a non-empty string, got ${String(noteId)}`);
  }
  return Object.freeze({ noteId, draft: text });
}

export function withDraft(editing, draft) {
  if (!isEditing(editing)) {
    throw new Error("cannot change the draft while no note is being edited");
  }
  return Object.freeze({ ...editing, draft });
}

/**
 * What a press (pointerdown) does to edit mode.
 * pressedNoteId: id of the note element under the press, or null.
 * inOverlay: the press landed in a modal dialog or toast, which sits above the
 * board and must work without disturbing the note being edited.
 */
export function pressAction(editing, pressedNoteId, inOverlay) {
  if (!isEditing(editing) || inOverlay) {
    return ACTION_NONE;
  }
  if (pressedNoteId === editing.noteId) {
    return ACTION_NONE;
  }
  return ACTION_SAVE;
}

export function keyAction(editing, key) {
  if (isEditing(editing) && key === "Escape") {
    return ACTION_CANCEL;
  }
  return ACTION_NONE;
}
