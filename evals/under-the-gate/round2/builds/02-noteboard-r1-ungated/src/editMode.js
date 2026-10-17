// Edit-mode decisions, independent of the DOM. The board describes what was
// pressed and these functions say what should happen.

/**
 * A pointer press anywhere on the page.
 * @param {object} p
 * @param {string|null} p.editingId   note currently being edited
 * @param {string|null} p.pressedNoteId  note element containing the press target
 * @param {boolean} p.inOverlay  press landed in a modal or toast
 * @returns {'commit'|'ignore'}
 */
export function onPress({ editingId, pressedNoteId, inOverlay }) {
  if (editingId === null) return 'ignore';
  // Overlays (confirm dialog, toasts) sit above the board: interacting with
  // them must not end the edit, and must not be disturbed by it.
  if (inOverlay) return 'ignore';
  if (pressedNoteId === editingId) return 'ignore';
  return 'commit';
}

/**
 * A click on a note (not on its toolbar).
 * @returns {'enter'|'ignore'}
 */
export function onNoteClick({ editingId, clickedNoteId, onToolbar }) {
  if (onToolbar || clickedNoteId === null) return 'ignore';
  if (clickedNoteId === editingId) return 'ignore';
  return 'enter';
}

/**
 * A key press while the page has focus.
 * @returns {'cancel'|'ignore'}
 */
export function onKey({ editingId, key, modalOpen }) {
  if (editingId === null || modalOpen) return 'ignore';
  return key === 'Escape' ? 'cancel' : 'ignore';
}
