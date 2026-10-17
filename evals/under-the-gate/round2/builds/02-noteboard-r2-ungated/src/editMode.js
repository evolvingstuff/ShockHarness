// Edit-mode decisions, independent of the DOM.
//
// A "press" is described by:
//   noteId     id of the note element containing the press target, or null
//   inOverlay  true if the press landed in a modal or toast
// Overlays sit outside the list, so they must not count as "outside the note":
// otherwise pressing a modal button would save and leave edit mode under it.

export const IDLE = Object.freeze({ editingId: null });

export function startEditing(state, noteId) {
  if (state.editingId === noteId) return { state, action: null };
  // Switching notes directly saves the previous one first.
  const action = state.editingId === null ? null : { type: 'save', id: state.editingId };
  return { state: { editingId: noteId }, action };
}

export function press(state, { noteId = null, inOverlay = false } = {}) {
  if (state.editingId === null || inOverlay || noteId === state.editingId) {
    return { state, action: null };
  }
  return { state: IDLE, action: { type: 'save', id: state.editingId } };
}

export function escape(state) {
  if (state.editingId === null) return { state, action: null };
  return { state: IDLE, action: { type: 'cancel', id: state.editingId } };
}

/** A note was removed; leave edit mode without saving if it was being edited. */
export function noteRemoved(state, noteId) {
  if (state.editingId !== noteId) return { state, action: null };
  return { state: IDLE, action: { type: 'cancel', id: noteId } };
}
