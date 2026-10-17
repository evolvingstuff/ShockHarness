// Edit-mode decisions, kept free of the DOM. The caller describes where an
// event happened; these functions say what the board should do.

/**
 * A press (pointerdown) somewhere on the page.
 *   editingId:    id of the note being edited, or null
 *   targetNoteId: id of the note element the press landed in, or null
 *   inOverlay:    true if the press landed in the modal or a toast; those sit
 *                 on top of the board and must not end editing as a side effect
 *   modalOpen:    true while the confirm dialog is open
 * Returns 'save' (commit the draft and leave edit mode) or 'none'.
 */
export function decidePress({ editingId, targetNoteId, inOverlay, modalOpen }) {
  if (editingId == null) return 'none';
  if (inOverlay || modalOpen) return 'none';
  if (targetNoteId === editingId) return 'none';
  return 'save';
}

/**
 * A key press. Returns 'cancel' (leave edit mode, discard draft) or 'none'.
 * While the modal is open, Escape belongs to the modal.
 */
export function decideKey({ key, editingId, modalOpen }) {
  if (key !== 'Escape' || editingId == null || modalOpen) return 'none';
  return 'cancel';
}

/**
 * A click on a note (not on a toolbar button). Returns 'edit' to start
 * editing that note, or 'none' if it is already being edited.
 */
export function decideNoteClick({ editingId, noteId }) {
  if (noteId == null || noteId === editingId) return 'none';
  return 'edit';
}
