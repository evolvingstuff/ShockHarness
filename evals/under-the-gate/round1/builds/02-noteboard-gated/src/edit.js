// Edit-mode decisions. No DOM. A transition says which note is edited next and
// which note (if any) must be saved first.

export const NOT_EDITING = null;
export const NO_NOTE = null;

function transition(editingId, saveId) {
  return Object.freeze({ editingId, saveId });
}

export function beginEdit(currentId, noteId) {
  if (currentId === NOT_EDITING || currentId === noteId) {
    return transition(noteId, NOT_EDITING);
  }
  return transition(noteId, currentId);
}

export function pressOutside(currentId, pressedNoteId) {
  if (currentId === NOT_EDITING || currentId === pressedNoteId) {
    return transition(currentId, NOT_EDITING);
  }
  return transition(NOT_EDITING, currentId);
}

export function cancelEdit() {
  return transition(NOT_EDITING, NOT_EDITING);
}
