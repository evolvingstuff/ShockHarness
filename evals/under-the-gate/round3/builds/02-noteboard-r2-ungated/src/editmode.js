// Edit-mode decisions, independent of the DOM. The caller describes where a
// press/click/key happened and gets back what to do.

/**
 * A pointer press somewhere on the page.
 * @param {object} p
 * @param {string|null} p.editingId   id of the note being edited, or null
 * @param {string|null} p.noteId      id of the note the press is inside, or null
 * @param {boolean} p.inOverlay       press is inside the modal or a toast
 * @returns {'save'|'none'}
 */
export function decidePress({ editingId, noteId, inOverlay }) {
  if (editingId === null) return 'none';
  // Overlays (confirm dialog, toasts) sit above the board; interacting with
  // them must neither save nor disturb the edit.
  if (inOverlay) return 'none';
  if (noteId === editingId) return 'none';
  return 'save';
}

/**
 * A click inside the list.
 * @param {object} c
 * @param {string|null} c.editingId
 * @param {string|null} c.noteId     note the click is in
 * @param {string|null} c.action     toolbar action ('pin'|'delete') or null
 * @returns {{type:'pin'|'delete'|'edit'|'none', id?:string}}
 */
export function decideListClick({ editingId, noteId, action }) {
  if (noteId === null) return { type: 'none' };
  if (action === 'pin' || action === 'delete') return { type: action, id: noteId };
  if (noteId === editingId) return { type: 'none' };
  return { type: 'edit', id: noteId };
}

/**
 * A keydown on the page.
 * @returns {'close-modal'|'cancel-edit'|'none'}
 */
export function decideKey({ key, editingId, modalOpen }) {
  if (key !== 'Escape') return 'none';
  if (modalOpen) return 'close-modal';
  if (editingId !== null) return 'cancel-edit';
  return 'none';
}
