// Edit-mode decisions, free of the DOM. A session is { editingId, draft }:
// editingId is null when no note is being edited.

import { findNote, removeNote, updateNoteText } from "./notes.js";

export const NOT_EDITING = Object.freeze({ editingId: null, draft: "" });

export const PRESS = Object.freeze({ IGNORE: "ignore", SAVE: "save" });
export const KEY = Object.freeze({ IGNORE: "ignore", CANCEL: "cancel" });
export const NOTE_CLICK = Object.freeze({ IGNORE: "ignore", BEGIN: "begin" });

export const CANCEL_KEY = "Escape";

export function isEditing(session) {
  return session.editingId !== null;
}

export function beginEdit(notes, id) {
  const note = findNote(notes, id);
  return Object.freeze({ editingId: id, draft: note.text });
}

export function withDraft(session, draft) {
  if (!isEditing(session)) {
    throw new Error("a draft can only change while a note is being edited");
  }
  return Object.freeze({ ...session, draft });
}

/**
 * A press somewhere on the page. press.noteId is the note the press landed in
 * (null outside every note); press.onFloatingControl is true for presses on the
 * modal or a toast, which handle their own presses and never end edit mode.
 */
export function decidePress(session, press) {
  if (!isEditing(session) || press.onFloatingControl) {
    return PRESS.IGNORE;
  }
  if (press.noteId === session.editingId) {
    return PRESS.IGNORE;
  }
  return PRESS.SAVE;
}

export function decideKey(session, key) {
  if (isEditing(session) && key === CANCEL_KEY) {
    return KEY.CANCEL;
  }
  return KEY.IGNORE;
}

export function decideNoteClick(session, id) {
  if (session.editingId === id) {
    return NOTE_CLICK.IGNORE;
  }
  return NOTE_CLICK.BEGIN;
}

/** Writes the draft into the edited note and leaves edit mode. */
export function commitEdit(notes, session) {
  if (!isEditing(session)) {
    throw new Error("there is no edit to save");
  }
  return Object.freeze({
    notes: updateNoteText(notes, session.editingId, session.draft),
    session: NOT_EDITING,
  });
}

/** Removes a note; deleting the note being edited ends edit mode without saving. */
export function deleteNote(notes, session, id) {
  const remaining = removeNote(notes, id);
  if (session.editingId === id) {
    return Object.freeze({ notes: remaining, session: NOT_EDITING });
  }
  return Object.freeze({ notes: remaining, session });
}
