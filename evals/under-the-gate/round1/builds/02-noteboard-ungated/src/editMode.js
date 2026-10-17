// Pure edit-mode decisions. `editingId` is the note being edited (or null).
// `targetNoteId` is the id of the note containing the pressed element,
// computed at event time (before any re-render detaches the target).
export function onPressOutcome(editingId, targetNoteId) {
  if (editingId == null) return 'none';
  return targetNoteId === editingId ? 'none' : 'save';
}

export function onKeyOutcome(editingId, key) {
  return editingId != null && key === 'Escape' ? 'cancel' : 'none';
}

// Clicking a note body enters edit mode, unless it is already being edited.
export function onNoteClickOutcome(editingId, noteId) {
  return noteId != null && noteId !== editingId ? 'edit' : 'none';
}
