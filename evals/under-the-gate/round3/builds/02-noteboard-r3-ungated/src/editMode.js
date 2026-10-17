// Edit-mode decisions, independent of the DOM.
//
// The view describes a press or click as { noteId, onToolbar }: noteId is the
// id of the note it landed in (null if outside every note) and onToolbar is
// true when it landed on a note's toolbar.
//
// Saving happens on press (pointerdown) so that pressing anywhere outside the
// note being edited ends edit mode; entering edit mode happens on click.

/** True when a press must save the note being edited and leave edit mode. */
export function shouldSaveOnPress(editingId, press) {
  if (editingId === null) return false;
  return (press?.noteId ?? null) !== editingId;
}

/** Id of the note a click should start editing, or null. */
export function noteToEditOnClick(editingId, click) {
  const { noteId = null, onToolbar = false } = click ?? {};
  if (noteId === null || onToolbar || noteId === editingId) return null;
  return noteId;
}

/**
 * Decides what a key press means. `modalOpen` is true when a dialog owns the
 * keyboard; Escape then belongs to the dialog, not to edit mode.
 * Returns 'cancel' (leave edit mode without saving) or null.
 */
export function decideKey(editingId, key, modalOpen = false) {
  if (key === 'Escape' && editingId !== null && !modalOpen) return 'cancel';
  return null;
}

/** After a note is deleted, edit mode for it must end. */
export function editingAfterDelete(editingId, deletedId) {
  return editingId === deletedId ? null : editingId;
}
